"""Read and strip file metadata: embedded tags via exiftool, macOS extended attributes via xattr."""
import json
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path

XATTR = "xattr:"
# Not real metadata: exiftool's own info, filesystem stats, derived values, PDF structure.
SKIP_GROUPS = {"ExifTool", "File", "System", "Composite"}
SKIP_TAGS = {"PDF:PDFVersion", "PDF:Linearized", "PDF:PageCount"}
# Set by macOS itself on every file an app writes; opaque ID, not removable.
SKIP_XATTRS = {"com.apple.provenance"}
# Catalog /Lang: exiftool can only read it, so qpdf writes it.
PDF_LANG = "PDF:Language"
# Structural: needed to display the image correctly, shown as protected and never removed.
KEEP_GROUP_PREFIXES = ("ICC", "JFIF", "PNG-pHYs")
KEEP_NAMES = {
    "Orientation", "ColorSpace", "Gamma", "SRGBRendering", "InteropIndex", "XResolution", "YResolution",
    "ResolutionUnit", "YCbCrPositioning", "ComponentsConfiguration", "ExifVersion", "ExifImageWidth",
    "ExifImageHeight", "ImageWidth", "ImageHeight", "BitDepth", "ColorType", "Compression", "Filter",
    "Interlace", "WhitePointX", "WhitePointY", "RedX", "RedY", "GreenX", "GreenY", "BlueX", "BlueY",
}


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def _xattr_value(name, path):
    raw = bytes.fromhex(run(["xattr", "-px", name, path]).replace("\n", "").replace(" ", ""))
    try:
        val = plistlib.loads(raw)  # e.g. kMDItemWhereFroms is a binary plist list of URLs
        return ", ".join(map(str, val)) if isinstance(val, list) else str(val)
    except Exception:
        return raw.decode("utf-8", "replace")


def _is_structural(key):
    group, name = key.split(":")[0], key.split(":")[-1]
    return group.startswith(KEEP_GROUP_PREFIXES) or name in KEEP_NAMES


def _tags(path):
    data = json.loads(run(["exiftool", "-j", "-G1", "-a", "-s", str(path)]))[0]
    return {k: v for k, v in data.items() if ":" in k and k.split(":")[0] not in SKIP_GROUPS and k not in SKIP_TAGS}


def inspect(path):
    path = str(path)
    tags = _tags(path)
    items = [
        {"key": k, "group": k.split(":")[0], "name": k.split(":")[-1], "protected": _is_structural(k),
         "value": ", ".join(map(str, v)) if isinstance(v, list) else str(v)}
        for k, v in tags.items()
        if not k.startswith("ICC")
    ]
    if any(k.startswith("ICC") for k in tags):  # one row for the whole profile, not its ~20 internal tags
        desc = tags.get("ICC_Profile:ProfileDescription", "embedded")
        items.append({"key": "ICC_Profile", "group": "ICC_Profile", "name": "ICC profile", "value": str(desc), "protected": True})
    for name in set(run(["xattr", path]).split()) - SKIP_XATTRS:
        items.append({"key": XATTR + name, "group": "macOS", "name": name, "value": _xattr_value(name, path), "protected": False})
    return items


def _copy_target(src):
    dst, n = src.with_name(f"{src.stem}_clean{src.suffix}"), 2
    while dst.exists():
        dst, n = src.with_name(f"{src.stem}_clean{n}{src.suffix}"), n + 1
    return dst


def _tag_args(tags, tag_keys):
    # Wipe whole groups when fully selected (some tags can only go as a group), unless they hold structural tags (never in `tags`).
    # XMP is one block: wiping its subgroups one by one makes exiftool re-add XMPToolkit.
    group = lambda k: "XMP" if k.startswith("XMP-") else k.split(":")[0]
    args = []
    for g in {group(k) for k in tags}:
        in_group = {k for k in tag_keys if group(k) == g}
        args += [f"-{g}:all="] if in_group <= tags else [f"-{k}=" for k in in_group & tags]
    return args


def _qpdf(*args):
    r = subprocess.run(["qpdf", *args], capture_output=True, text=True)
    if r.returncode not in (0, 3):  # 3 = succeeded with warnings
        raise RuntimeError(r.stderr)


def _rewrite_pdf(path, lang=None):
    """Full rewrite; lang: None leaves /Lang alone, "" removes it, otherwise sets it."""
    if lang is None:
        return _qpdf("--replace-input", str(path))
    doc = json.loads(run(["qpdf", "--json=2", "--json-key=qpdf", str(path)]))["qpdf"]
    root = doc[1]["trailer"]["value"]["/Root"]
    catalog = doc[1][f"obj:{root}"]["value"]
    catalog.pop("/Lang", None)
    if lang:
        catalog["/Lang"] = "u:" + lang
    with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
        json.dump({"qpdf": [doc[0], {f"obj:{root}": {"value": catalog}}]}, f)
        f.flush()
        _qpdf(f"--update-from-json={f.name}", "--replace-input", str(path))


def strip(path, keys, overwrite, edits=None):
    """keys: fields to remove; edits: {key: new value} for fields to rewrite instead ("" removes)."""
    src = Path(path)
    tag_keys = set(_tags(src))
    edits = {k: v for k, v in (edits or {}).items() if k in tag_keys and not _is_structural(k)}
    tags = {k for k in keys if not k.startswith(XATTR) and not _is_structural(k)} - edits.keys()
    dst = src if overwrite else _copy_target(src)
    if not overwrite:
        shutil.copyfile(src, dst)  # content only: no dates, no xattrs

    args = _tag_args(tags - {PDF_LANG}, tag_keys - {PDF_LANG})
    args += [f"-{k}={v}" for k, v in edits.items() if k != PDF_LANG]
    if args:
        run(["exiftool", "-overwrite_original", "-q", "-m", "-sep", ", ", *args, str(dst)])
    if dst.suffix.lower() == ".pdf" and (args or PDF_LANG in tags or PDF_LANG in edits):
        # exiftool edits PDFs incrementally (old values stay recoverable); a full rewrite drops them
        _rewrite_pdf(dst, edits.get(PDF_LANG, "" if PDF_LANG in tags else None))

    for k in keys:
        if k.startswith(XATTR):
            subprocess.run(["xattr", "-d", k[len(XATTR):], str(dst)], capture_output=True)

    return {"output": str(dst), "remaining": inspect(dst)}
