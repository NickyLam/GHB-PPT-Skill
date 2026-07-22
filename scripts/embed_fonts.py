#!/usr/bin/env python3
"""Embed subsetted fonts into a PowerPoint deck so CJK fidelity travels with it.

Rendering fidelity in this pipeline otherwise depends on the *target* machine
having ``Source Han Sans SC`` installed. This module optionally bakes a
subsetted copy of the required fonts into the ``.pptx`` itself:

* collect every character actually used in the deck (stdlib only),
* subset each font to those glyphs with ``fontTools`` (required; never skipped),
* refuse fonts whose ``OS/2.fsType`` forbids embedding (license guard),
* inject the font parts and wire ``[Content_Types].xml`` /
  ``ppt/presentation.xml`` / its rels (stdlib only).

The OOXML wiring and character collection are pure-stdlib and independently
testable; only the subsetting/licence steps need ``fontTools``. When
``fontTools`` or a requested font file is missing, we fail fast with an
actionable message rather than pretend the deck is self-contained.
"""

from __future__ import annotations

import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

FONT_CONTENT_TYPE = "application/x-fontdata"
FONT_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"
# fsType bit 1 (0x0002) = Restricted License: embedding is not permitted.
FS_TYPE_RESTRICTED = 0x0002
FS_TYPE_NO_SUBSETTING = 0x0100
FS_TYPE_BITMAP_ONLY = 0x0200


class FontEmbedError(RuntimeError):
    """Actionable failure while embedding fonts."""


@dataclass(frozen=True)
class EmbeddedFont:
    typeface: str
    data: bytes
    subsetted: bool = True


def collect_used_characters(pptx_path: Path) -> set[str]:
    """Return every character used in slide/master/layout text runs."""
    chars: set[str] = set()
    text_pattern = re.compile(r"<a:t>(.*?)</a:t>", re.DOTALL)
    with zipfile.ZipFile(pptx_path) as archive:
        for name in archive.namelist():
            if not (
                name.startswith("ppt/slides/")
                or name.startswith("ppt/slideMasters/")
                or name.startswith("ppt/slideLayouts/")
                or name.startswith("ppt/notesSlides/")
            ):
                continue
            if not name.endswith(".xml"):
                continue
            xml = archive.read(name).decode("utf-8", errors="ignore")
            for run in text_pattern.findall(xml):
                chars.update(
                    run.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                )
    return chars


def read_fs_type(font_path: Path) -> int:
    """Return the font's ``OS/2.fsType`` embedding-permission bits."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise FontEmbedError(
            "fontTools is required to embed fonts; install it (pip install fonttools) "
            "or drop --embed-fonts"
        ) from exc
    try:
        font = TTFont(str(font_path), lazy=True)
        os2 = font.get("OS/2")
    except Exception as exc:  # noqa: BLE001 - surface any parse failure
        raise FontEmbedError(f"cannot read font {font_path}: {exc}") from exc
    return int(getattr(os2, "fsType", 0)) if os2 is not None else 0


def is_embeddable(fs_type: int) -> bool:
    return not (fs_type & (FS_TYPE_RESTRICTED | FS_TYPE_BITMAP_ONLY))


def probe_embeddability(font_path: Path) -> dict[str, object]:
    """Non-raising embeddability probe for ``doctor``.

    Never raises: reports whether ``fontTools`` is available and, when it is,
    the font's ``fsType`` and whether embedding is permitted.
    """
    try:
        fs_type = read_fs_type(font_path)
    except FontEmbedError as exc:
        note = str(exc)
        fonttools = "fontTools is required" not in note
        return {"fonttools": fonttools, "fsType": None, "embeddable": None, "note": note}
    return {
        "fonttools": True,
        "fsType": fs_type,
        "embeddable": is_embeddable(fs_type),
        "note": None,
    }


def subset_font(font_path: Path, characters: set[str]) -> bytes:
    """Return a subsetted TrueType/OpenType binary containing ``characters``."""
    try:
        from fontTools import subset
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise FontEmbedError(
            "fontTools is required to subset fonts; install it (pip install fonttools)"
        ) from exc
    options = subset.Options()
    options.layout_features = ["*"]
    options.notdef_outline = True
    options.recalc_bounds = True
    text = "".join(sorted(characters)) or " "
    try:
        font = subset.load_font(str(font_path), options)
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(text=text)
        subsetter.subset(font)
        buffer = tempfile.SpooledTemporaryFile()
        subset.save_font(font, buffer, options)
        buffer.seek(0)
        return buffer.read()
    except FontEmbedError:
        raise
    except Exception as exc:  # noqa: BLE001 - subsetting failures are actionable
        raise FontEmbedError(f"failed to subset {font_path}: {exc}") from exc


def _content_types_with_fntdata(xml: str) -> str:
    if 'Extension="fntdata"' in xml:
        return xml
    default = f'<Default Extension="fntdata" ContentType="{FONT_CONTENT_TYPE}"/>'
    if "</Types>" not in xml:
        raise FontEmbedError("[Content_Types].xml is malformed: missing </Types>")
    return xml.replace("</Types>", f"{default}</Types>", 1)


def _rels_with_fonts(xml: str, entries: list[tuple[str, str]]) -> str:
    """Add font relationships. ``entries`` is a list of (rel_id, part_name)."""
    if "</Relationships>" not in xml:
        raise FontEmbedError("presentation.xml.rels is malformed: missing </Relationships>")
    additions = "".join(
        f'<Relationship Id="{rid}" Type="{FONT_REL_TYPE}" Target="{target}"/>'
        for rid, target in entries
    )
    return xml.replace("</Relationships>", f"{additions}</Relationships>", 1)


def _next_rel_ids(rels_xml: str, count: int) -> list[str]:
    used = {int(m) for m in re.findall(r'Id="rId(\d+)"', rels_xml)}
    ids: list[str] = []
    candidate = 1
    while len(ids) < count:
        if candidate not in used:
            ids.append(f"rId{candidate}")
            used.add(candidate)
        candidate += 1
    return ids


def _presentation_with_embedded_fonts(
    xml: str,
    fonts: list[tuple[str, str]],
    *,
    save_subsets: bool,
) -> str:
    """Set embed attributes and insert ``<p:embeddedFontLst>``.

    ``fonts`` is a list of (typeface, rel_id).
    """
    if "embeddedFontLst" in xml:
        raise FontEmbedError(
            "presentation already contains embedded fonts; rebuild from the unembedded deck"
        )
    match = re.search(r"<p:presentation\b[^>]*>", xml)
    if not match:
        raise FontEmbedError("presentation.xml is malformed: missing <p:presentation>")
    open_tag = match.group(0)
    updated_tag = open_tag
    for attr, value in (
        ("embedTrueTypeFonts", "1"),
        ("saveSubsetFonts", "1" if save_subsets else "0"),
    ):
        if attr not in updated_tag:
            updated_tag = updated_tag[:-1] + f' {attr}="{value}"' + updated_tag[-1]
    xml = xml.replace(open_tag, updated_tag, 1)

    entries = "".join(
        f'<p:embeddedFont><p:font typeface="{xml_escape(typeface, {chr(34): "&quot;"})}"/>'
        f'<p:regular r:id="{rid}"/></p:embeddedFont>'
        for typeface, rid in fonts
    )
    block = f"<p:embeddedFontLst>{entries}</p:embeddedFontLst>"
    # Schema order places embeddedFontLst after notesSz; fall back to just
    # before the closing tag when notesSz is absent.
    notes = re.search(r"<p:notesSz\b[^>]*/>", xml)
    if notes:
        insert_at = notes.end()
        return xml[:insert_at] + block + xml[insert_at:]
    return xml.replace("</p:presentation>", f"{block}</p:presentation>", 1)


def inject_embedded_fonts(pptx_path: Path, fonts: list[EmbeddedFont], output_path: Path) -> None:
    """Rewrite ``pptx_path`` into ``output_path`` with ``fonts`` embedded.

    Reads the whole archive before writing so ``pptx_path`` and ``output_path``
    may be the same file (in-place embedding).
    """
    if not fonts:
        raise FontEmbedError("no fonts to embed")
    with zipfile.ZipFile(pptx_path) as archive:
        infos = archive.infolist()
        blobs = {info.filename: archive.read(info.filename) for info in infos}
    names = set(blobs)
    if "[Content_Types].xml" not in names:
        raise FontEmbedError("[Content_Types].xml is missing")
    if "ppt/presentation.xml" not in names:
        raise FontEmbedError("ppt/presentation.xml is missing")
    rels_name = "ppt/_rels/presentation.xml.rels"
    if rels_name not in names:
        raise FontEmbedError("presentation relationships part is missing")
    content_types = blobs["[Content_Types].xml"].decode("utf-8")
    presentation = blobs["ppt/presentation.xml"].decode("utf-8")
    rels = blobs[rels_name].decode("utf-8")

    rel_ids = _next_rel_ids(rels, len(fonts))
    part_names = [f"ppt/fonts/font{index + 1}.fntdata" for index in range(len(fonts))]
    rel_entries = [(rel_ids[i], f"fonts/font{i + 1}.fntdata") for i in range(len(fonts))]
    font_entries = [(fonts[i].typeface, rel_ids[i]) for i in range(len(fonts))]

    rewritten = {
        "[Content_Types].xml": _content_types_with_fntdata(content_types).encode("utf-8"),
        "ppt/presentation.xml": _presentation_with_embedded_fonts(
            presentation,
            font_entries,
            save_subsets=all(font.subsetted for font in fonts),
        ).encode("utf-8"),
        rels_name: _rels_with_fonts(rels, rel_entries).encode("utf-8"),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for info in infos:
            out.writestr(info, rewritten.get(info.filename, blobs[info.filename]))
        for part_name, font in zip(part_names, fonts):
            out.writestr(part_name, font.data)
    tmp.replace(output_path)


def embed_fonts(
    pptx_path: Path,
    *,
    font_paths: list[Path],
    output_path: Path,
    subset: bool = True,
) -> dict[str, object]:
    """Subset and embed ``font_paths`` into ``pptx_path`` -> ``output_path``.

    Returns a report describing what was embedded. Raises :class:`FontEmbedError`
    when fontTools is unavailable, a font file is missing, or a font's licence
    forbids embedding.
    """
    if not pptx_path.is_file():
        raise FontEmbedError(f"deck not found: {pptx_path}")
    if not font_paths:
        raise FontEmbedError("no --font provided for embedding")
    characters = collect_used_characters(pptx_path)
    embedded: list[EmbeddedFont] = []
    names: list[str] = []
    subsetted_names: list[str] = []
    full_names: list[str] = []
    fs_type_ok = True
    for font_path in font_paths:
        if not font_path.is_file():
            raise FontEmbedError(f"font file not found: {font_path}")
        fs_type = read_fs_type(font_path)
        if not is_embeddable(fs_type):
            fs_type_ok = False
            raise FontEmbedError(
                f"{font_path.name} has OS/2.fsType={fs_type:#06x} which forbids embedding; "
                "choose an embeddable font or drop --embed-fonts"
            )
        try:
            from fontTools.ttLib import TTFont

            typeface = TTFont(str(font_path), lazy=True)["name"].getDebugName(1) or font_path.stem
        except Exception:  # noqa: BLE001 - fall back to the file stem
            typeface = font_path.stem
        subset_this_font = subset and not (fs_type & FS_TYPE_NO_SUBSETTING)
        data = subset_font(font_path, characters) if subset_this_font else font_path.read_bytes()
        embedded.append(
            EmbeddedFont(typeface=typeface, data=data, subsetted=subset_this_font)
        )
        names.append(typeface)
        (subsetted_names if subset_this_font else full_names).append(typeface)
    inject_embedded_fonts(pptx_path, embedded, output_path)
    return {
        "schema": "ghb.font-embed-report.v1",
        "fonts_embedded": len(embedded),
        "embedded_font_names": names,
        "subsetted_font_names": subsetted_names,
        "full_font_names": full_names,
        "fsType_ok": fs_type_ok,
        "characters": len(characters),
        "output": str(output_path),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--font", type=Path, action="append", required=True, dest="fonts")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-subset", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = embed_fonts(
            args.pptx,
            font_paths=args.fonts,
            output_path=args.output,
            subset=not args.no_subset,
        )
    except FontEmbedError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"[OK] embedded {report['fonts_embedded']} font(s): {report['embedded_font_names']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
