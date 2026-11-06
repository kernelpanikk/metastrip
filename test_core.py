"""Self-check: builds a tagged JPG and a 'Canva' PDF in a temp dir, strips them, asserts nothing leaks."""
import subprocess
import tempfile
from pathlib import Path

import core

WHERE = "com.apple.metadata:kMDItemWhereFroms"
ICC = "/System/Library/ColorSync/Profiles/sRGB Profile.icc"


def loose(items):
    return [i for i in items if not i["protected"]]


def sh(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


with tempfile.TemporaryDirectory() as d:
    d = Path(d)

    # JPG with EXIF/XMP/GPS + "downloaded from" xattr
    jpg = d / "photo.jpg"
    sh("sips", "-s", "format", "jpeg", "/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/GenericDocumentIcon.icns", "--out", str(jpg))
    sh("exiftool", "-overwrite_original", "-Artist=Mario", "-DateTimeOriginal=2020:01:01 10:00:00",
       "-GPSLatitude=45.4", "-GPSLatitudeRef=N", "-XMP:CreatorTool=Canva", "-Orientation#=6", f"-ICC_Profile<={ICC}", str(jpg))
    sh("xattr", "-w", WHERE, "https://example.com/img.jpg", str(jpg))

    keys = [i["key"] for i in core.inspect(jpg)]
    assert "IFD0:Artist" in keys and core.XATTR + WHERE in keys, keys

    # partial strip: keep Artist
    res = core.strip(jpg, [k for k in keys if k != "IFD0:Artist"], overwrite=False)
    out = Path(res["output"])
    assert out.name == "photo_clean.jpg" and jpg.exists()
    assert [i["key"] for i in loose(res["remaining"])] == ["IFD0:Artist"], res["remaining"]

    # edit instead of remove: a list value round-trips through ", "
    sh("exiftool", "-overwrite_original", "-XMP-dc:Subject=a", "-XMP-dc:Subject=b", str(jpg))
    keys = [i["key"] for i in core.inspect(jpg)]
    res = core.strip(jpg, keys, overwrite=False, edits={"XMP-xmp:CreatorTool": "Word", "XMP-dc:Subject": "x, y"})
    left = {i["key"]: i["value"] for i in loose(res["remaining"])}
    assert left == {"XMP-xmp:CreatorTool": "Word", "XMP-dc:Subject": "x, y"}, left

    # full strip in place
    res = core.strip(jpg, keys, overwrite=True)  # keys include protected ones: must be ignored
    assert loose(res["remaining"]) == [], res["remaining"]
    assert {i["name"] for i in res["remaining"]} >= {"Orientation", "ICC profile"}
    kept = core._tags(jpg)
    assert kept["IFD0:Orientation"] == "Rotate 90 CW" and "ICC_Profile:ProfileDescription" in kept, kept
    assert core.strip(jpg, [], overwrite=False)["output"].endswith("photo_clean3.jpg")

    # PNG: gamma/chromaticity chunks are structural and must survive
    png = d / "shot.png"
    sh("sips", "-s", "format", "png", "/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/GenericDocumentIcon.icns", "--out", str(png))
    sh("exiftool", "-overwrite_original", "-PNG:Artist=Mario", "-XMP:CreatorTool=Canva", str(png))
    res = core.strip(png, [i["key"] for i in core.inspect(png)], overwrite=True)
    assert loose(res["remaining"]) == [], res["remaining"]
    assert "PNG:Gamma" in core._tags(png) and b"Mario" not in png.read_bytes()

    # PDF "made with Canva"
    pdf = d / "cv.pdf"
    sh("qpdf", "--empty", str(pdf))
    sh("exiftool", "-overwrite_original", "-Producer=Canva", "-Creator=Canva", "-Author=Mario",
       "-CreateDate=2024:05:05 10:00:00", "-XMP:CreatorTool=Canva", str(pdf))
    core._rewrite_pdf(pdf, "it-IT")
    keys = [i["key"] for i in core.inspect(pdf)]
    assert "PDF:Producer" in keys and "PDF:Language" in keys, keys
    res = core.strip(pdf, keys, overwrite=False, edits={"PDF:Language": "en-US", "PDF:Author": "Anon"})
    left = {i["key"]: i["value"] for i in loose(res["remaining"])}
    assert left == {"PDF:Language": "en-US", "PDF:Author": "Anon"}, left
    res = core.strip(pdf, keys, overwrite=True)
    assert loose(res["remaining"]) == [], res["remaining"]
    raw = pdf.read_bytes()
    assert b"Canva" not in raw and b"Mario" not in raw and b"it-IT" not in raw, "old metadata still recoverable in PDF bytes"

print("ok")
