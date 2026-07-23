#!/usr/bin/env python3
"""Merge editable SVG body slides onto a selected template master.

This is the GHB-owned OOXML seam.  It keeps the existing architecture (filled
template cover + editable SVG body + template ending) while allocating parts,
IDs, relationships, tags, and media without fixed names or string-regex XML
mutation.  The public output is replaced atomically only after relationship
targets have been checked.
"""

from __future__ import annotations

import argparse
import copy
import mimetypes
import os
import posixpath
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}
for prefix in ("a", "p", "r"):
    ET.register_namespace(prefix, NS[prefix])
ET.register_namespace("", NS["rel"])

OFF = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CONTENT_TYPES = {
    "master": "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml",
    "layout": "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml",
    "slide": "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
    "theme": "application/vnd.openxmlformats-officedocument.theme+xml",
    "tags": "application/vnd.openxmlformats-officedocument.presentationml.tags+xml",
}
MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "svg": "image/svg+xml",
    "emf": "image/x-emf",
    "wmf": "image/x-wmf",
}
SECTION_LABEL_SHAPE = "template-section-label"
SECTION_FRAME_SHAPE = "GHB Template Section Frame"
SECTION_FRAME_PLACEHOLDER = "XXX"
SECTION_FRAME_FONT = "Source Han Sans SC"


class MergeError(RuntimeError):
    """Raised for a malformed or unsupported package graph."""


@dataclass(frozen=True)
class MergeResult:
    output: Path
    body_count: int
    has_ending: bool
    master_part: str
    cover_layout_part: str
    content_layout_part: str
    ending_layout_part: str | None


def qn(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


def xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def content_types_bytes(root: ET.Element) -> bytes:
    """Serialize OPC Content Types with the namespace as the default.

    The XML namespace is semantically identical when ElementTree emits an
    ``ns0:`` prefix, but LibreOffice rejects such packages with a generic
    "source file could not be loaded" error.  OPC producers conventionally use
    the Content Types namespace as the default, so preserve that wire format.
    """
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    text = payload.decode("utf-8")
    text = text.replace(
        '<ns0:Types xmlns:ns0="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        1,
    )
    text = text.replace("</ns0:Types>", "</Types>")
    text = text.replace("<ns0:", "<").replace("</ns0:", "</")
    return text.encode("utf-8")


def load_package(path: Path) -> dict[str, bytes]:
    if not path.is_file():
        raise MergeError(f"PPTX not found: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                raise MergeError(f"corrupt ZIP member in {path}: {bad}")
            return {
                info.filename: archive.read(info.filename)
                for info in archive.infolist()
                if not info.is_dir()
            }
    except zipfile.BadZipFile as exc:
        raise MergeError(f"invalid PPTX ZIP: {path}") from exc


def require(parts: dict[str, bytes], name: str) -> bytes:
    try:
        return parts[name]
    except KeyError as exc:
        raise MergeError(f"missing part: {name}") from exc


def rels_name(part: str) -> str:
    path = PurePosixPath(part)
    return str(path.parent / "_rels" / f"{path.name}.rels")


def resolve_target(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))


def relative_target(source_part: str, target_part: str) -> str:
    return posixpath.relpath(target_part, posixpath.dirname(source_part))


def relation_type(rel: ET.Element) -> str:
    return rel.get("Type", "").rsplit("/", 1)[-1]


def parse_rels(parts: dict[str, bytes], part: str) -> ET.Element:
    name = rels_name(part)
    data = require(parts, name)
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise MergeError(f"invalid relationships XML: {name}: {exc}") from exc


def find_template_section_frame(
    template: dict[str, bytes],
    template_slides: list[str],
    content_layout: str,
    *,
    left_inset_px: float = 0.0,
) -> ET.Element:
    """Return the native top-level title-frame group for the content layout."""
    matches: list[ET.Element] = []
    for slide_part in template_slides:
        if slide_layout_part(template, slide_part) != content_layout:
            continue
        slide = ET.fromstring(require(template, slide_part))
        tree = slide.find("p:cSld/p:spTree", NS)
        if tree is None:
            continue
        for shape in list(tree):
            if shape.tag != qn("p", "grpSp"):
                continue
            texts = [node.text or "" for node in shape.findall(".//a:t", NS)]
            if SECTION_FRAME_PLACEHOLDER in texts:
                matches.append(shape)
    if not matches:
        raise MergeError(
            f"template content slides have no native section frame containing "
            f"{SECTION_FRAME_PLACEHOLDER!r}"
        )
    frame = copy.deepcopy(matches[0])
    presentation = ET.fromstring(require(template, "ppt/presentation.xml"))
    slide_size = presentation.find("p:sldSz", NS)
    frame_xfrm = frame.find("p:grpSpPr/a:xfrm", NS)
    frame_off = frame_xfrm.find("a:off", NS) if frame_xfrm is not None else None
    frame_ext = frame_xfrm.find("a:ext", NS) if frame_xfrm is not None else None
    if slide_size is None or frame_off is None or frame_ext is None:
        raise MergeError("template section frame or slide size has no geometry")
    slide_width = int(slide_size.get("cx", "0"))
    frame_width = int(frame_ext.get("cx", "0"))
    frame_x = int(frame_off.get("x", "0"))
    if left_inset_px < 0:
        raise MergeError("section frame left inset must not be negative")
    if frame_x + frame_width > slide_width:
        # The reference template intentionally bleeds this group a few pixels
        # past the right edge. Body-slide quality gates treat that as an error,
        # so preserve its size and appearance while right-aligning it in-frame.
        frame_off.set("x", str(max(0, slide_width - frame_width)))
    if left_inset_px:
        # Consulting pages use a slightly narrower title band. Anchor the
        # native group to the physical right edge first, then move only its
        # left edge right so the branded frame remains flush with the slide.
        inset = round(left_inset_px * slide_width / 1280)
        if inset >= frame_width:
            raise MergeError("section frame left inset leaves no visible title frame")
        frame_off.set("x", str(max(0, slide_width - frame_width) + inset))
        frame_ext.set("cx", str(frame_width - inset))
    # PowerPoint attached authoring tags to the placeholder shape. They are
    # slide-specific metadata, not visual content, so carrying their r:id into
    # another slide would create a dangling relationship. Remove that metadata
    # while preserving all geometry, fills, lines, and editable text.
    frame_parents = {child: parent for parent in frame.iter() for child in parent}
    for tags in frame.findall(".//p:tags", NS):
        custom_data = frame_parents.get(tags)
        while custom_data is not None and custom_data.tag != qn("p", "custDataLst"):
            custom_data = frame_parents.get(custom_data)
        custom_data_parent = frame_parents.get(custom_data) if custom_data is not None else None
        if custom_data is not None and custom_data_parent is not None:
            custom_data_parent.remove(custom_data)
    relationship_attrs = [
        key
        for node in frame.iter()
        for key in node.attrib
        if key.startswith(f"{{{NS['r']}}}")
    ]
    if relationship_attrs:
        raise MergeError("template section frame contains unsupported relationship references")
    return frame


def move_section_label_into_template_frame(
    slide_payload: bytes,
    template_frame: ET.Element,
    *,
    section_frame_font: str = SECTION_FRAME_FONT,
) -> bytes:
    """Replace a semantic SVG label with a cloned, editable template title frame."""
    slide = ET.fromstring(slide_payload)
    tree = slide.find("p:cSld/p:spTree", NS)
    if tree is None:
        raise MergeError("body slide has no shape tree")

    parent_map = {child: parent for parent in slide.iter() for child in parent}
    markers = [
        node
        for node in slide.findall(".//p:cNvPr", NS)
        if node.get("name") == SECTION_LABEL_SHAPE
    ]
    if not markers:
        return slide_payload
    if len(markers) != 1:
        raise MergeError(f"body slide must contain at most one {SECTION_LABEL_SHAPE!r} shape")

    marker = markers[0]
    shape = parent_map.get(marker)
    while shape is not None and shape.tag != qn("p", "sp"):
        shape = parent_map.get(shape)
    if shape is None:
        raise MergeError(f"{SECTION_LABEL_SHAPE!r} is not attached to a text shape")
    label = "".join(node.text or "" for node in shape.findall(".//a:t", NS)).strip()
    if not label:
        raise MergeError(f"{SECTION_LABEL_SHAPE!r} has no text")
    shape_parent = parent_map.get(shape)
    if shape_parent is None:
        raise MergeError(f"cannot remove {SECTION_LABEL_SHAPE!r} from body slide")
    shape_parent.remove(shape)

    frame = copy.deepcopy(template_frame)
    placeholders = [
        node for node in frame.findall(".//a:t", NS) if (node.text or "") == SECTION_FRAME_PLACEHOLDER
    ]
    if len(placeholders) != 1:
        raise MergeError("template section frame must contain exactly one title placeholder")
    placeholders[0].text = label
    for font in frame.findall(".//a:latin", NS) + frame.findall(".//a:ea", NS) + frame.findall(".//a:cs", NS):
        font.set("typeface", section_frame_font)

    top_properties = frame.find("p:nvGrpSpPr/p:cNvPr", NS)
    if top_properties is None:
        raise MergeError("template section frame group has no non-visual properties")
    top_properties.set("name", SECTION_FRAME_SHAPE)

    existing_ids = [
        int(node.get("id", "0"))
        for node in slide.findall(".//p:cNvPr", NS)
        if node.get("id", "").isdigit()
    ]
    next_id = max(existing_ids, default=0) + 1
    for properties in frame.findall(".//p:cNvPr", NS):
        properties.set("id", str(next_id))
        next_id += 1
    tree.append(frame)
    return xml_bytes(slide)


def max_index(parts: dict[str, bytes], pattern: str) -> int:
    regex = re.compile(pattern)
    values = [int(match.group(1)) for name in parts if (match := regex.fullmatch(name))]
    return max(values, default=0)


def allocate_indexed_part(parts: dict[str, bytes], directory: str, stem: str, suffix: str = ".xml") -> str:
    pattern = rf"{re.escape(directory)}/{re.escape(stem)}(\d+){re.escape(suffix)}"
    index = max_index(parts, pattern) + 1
    while f"{directory}/{stem}{index}{suffix}" in parts:
        index += 1
    return f"{directory}/{stem}{index}{suffix}"


def allocate_rid(root: ET.Element) -> str:
    values = []
    for rel in root:
        match = re.fullmatch(r"rId(\d+)", rel.get("Id", ""))
        if match:
            values.append(int(match.group(1)))
    return f"rId{max(values, default=0) + 1}"


def add_relationship(root: ET.Element, rel_type: str, target: str, *, rid: str | None = None, external: bool = False) -> str:
    rid = rid or allocate_rid(root)
    if any(rel.get("Id") == rid for rel in root):
        raise MergeError(f"duplicate relationship ID allocation: {rid}")
    attrs = {"Id": rid, "Type": OFF + rel_type, "Target": target}
    if external:
        attrs["TargetMode"] = "External"
    ET.SubElement(root, qn("rel", "Relationship"), attrs)
    return rid


def copy_collision_safe(
    destination: dict[str, bytes],
    source: dict[str, bytes],
    source_part: str,
    *,
    preferred: str | None = None,
) -> str:
    payload = require(source, source_part)
    candidate = preferred or source_part
    if candidate not in destination:
        destination[candidate] = payload
        return candidate
    if destination[candidate] == payload:
        return candidate
    path = PurePosixPath(candidate)
    for index in range(2, 10000):
        renamed = str(path.with_name(f"{path.stem}_ghb{index}{path.suffix}"))
        if renamed not in destination:
            destination[renamed] = payload
            return renamed
        if destination[renamed] == payload:
            return renamed
    raise MergeError(f"unable to allocate collision-safe part for {source_part}")


def presentation_slide_parts(parts: dict[str, bytes]) -> list[str]:
    pres = ET.fromstring(require(parts, "ppt/presentation.xml"))
    rels = ET.fromstring(require(parts, "ppt/_rels/presentation.xml.rels"))
    rel_map = {rel.get("Id"): rel for rel in rels}
    output: list[str] = []
    for slide_id in pres.findall(".//p:sldId", NS):
        rid = slide_id.get(qn("r", "id"))
        rel = rel_map.get(rid)
        if rel is None or relation_type(rel) != "slide":
            raise MergeError(f"presentation slide relationship missing: {rid}")
        output.append(resolve_target("ppt/presentation.xml", rel.get("Target", "")))
    return output


def slide_layout_part(parts: dict[str, bytes], slide_part: str) -> str:
    rels = parse_rels(parts, slide_part)
    layouts = [rel for rel in rels if relation_type(rel) == "slideLayout"]
    if len(layouts) != 1:
        raise MergeError(f"{slide_part}: expected one slideLayout relationship, found {len(layouts)}")
    return resolve_target(slide_part, layouts[0].get("Target", ""))


def copy_media_relation(
    destination: dict[str, bytes],
    source: dict[str, bytes],
    source_owner: str,
    destination_owner: str,
    rel: ET.Element,
) -> None:
    source_part = resolve_target(source_owner, rel.get("Target", ""))
    preferred = f"ppt/media/{PurePosixPath(source_part).name}"
    copied = copy_collision_safe(destination, source, source_part, preferred=preferred)
    rel.set("Target", relative_target(destination_owner, copied))


def copy_tag_relation(
    destination: dict[str, bytes],
    source: dict[str, bytes],
    source_owner: str,
    destination_owner: str,
    rel: ET.Element,
) -> str:
    source_part = resolve_target(source_owner, rel.get("Target", ""))
    preferred = f"ppt/tags/{PurePosixPath(source_part).name}"
    copied = copy_collision_safe(destination, source, source_part, preferred=preferred)
    rel.set("Target", relative_target(destination_owner, copied))
    return copied


def content_types_root(parts: dict[str, bytes]) -> ET.Element:
    try:
        return ET.fromstring(require(parts, "[Content_Types].xml"))
    except ET.ParseError as exc:
        raise MergeError(f"invalid [Content_Types].xml: {exc}") from exc


def add_override(root: ET.Element, part: str, content_type: str) -> None:
    part_name = "/" + part.lstrip("/")
    matches = [node for node in root.findall(qn("ct", "Override")) if node.get("PartName") == part_name]
    if matches:
        if any(node.get("ContentType") != content_type for node in matches):
            raise MergeError(f"conflicting content type for {part}")
        for extra in matches[1:]:
            root.remove(extra)
        return
    ET.SubElement(root, qn("ct", "Override"), {"PartName": part_name, "ContentType": content_type})


def add_media_defaults(root: ET.Element, parts: dict[str, bytes]) -> None:
    existing = {node.get("Extension", "").lower(): node for node in root.findall(qn("ct", "Default"))}
    for name in parts:
        if not name.startswith("ppt/media/") or "." not in name:
            continue
        ext = name.rsplit(".", 1)[-1].lower()
        if ext in existing:
            continue
        content_type = MEDIA_TYPES.get(ext) or mimetypes.guess_type(f"x.{ext}")[0]
        if not content_type:
            raise MergeError(f"unknown media content type: {name}")
        ET.SubElement(root, qn("ct", "Default"), {"Extension": ext, "ContentType": content_type})
        existing[ext] = root[-1]


def verify_relationship_targets(parts: dict[str, bytes]) -> None:
    problems: list[str] = []
    for name, payload in parts.items():
        if not name.endswith(".rels"):
            continue
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            problems.append(f"{name}: invalid XML ({exc})")
            continue
        if "/_rels/" in name:
            prefix, filename = name.split("/_rels/", 1)
            owner = f"{prefix}/{filename[:-5]}"
        elif name.startswith("_rels/"):
            owner = name[len("_rels/") : -5]
        else:
            continue
        ids = [rel.get("Id", "") for rel in root]
        for rid in sorted({rid for rid in ids if ids.count(rid) > 1}):
            problems.append(f"{name}: duplicate {rid}")
        for rel in root:
            if rel.get("TargetMode") == "External":
                continue
            target = resolve_target(owner, rel.get("Target", ""))
            if target not in parts:
                problems.append(f"{name}: {rel.get('Id')} -> missing {target}")
    if problems:
        raise MergeError("relationship validation failed:\n  - " + "\n  - ".join(problems))


def merge_pptx(
    *,
    content_path: Path,
    template_path: Path,
    cover_path: Path,
    output_path: Path,
    content_layout_index: int = 2,
    ending_slide_index: int | None = None,
    no_ending: bool = False,
    section_frame_font: str = SECTION_FRAME_FONT,
    section_frame_left_inset_px: float = 0.0,
) -> MergeResult:
    content = load_package(content_path)
    template = load_package(template_path)
    cover = load_package(cover_path)

    body_slides = presentation_slide_parts(content)
    if not body_slides:
        raise MergeError("content PPTX has no slides")
    cover_slides = presentation_slide_parts(cover)
    if not cover_slides:
        raise MergeError("cover PPTX has no slides")
    cover_source_slide = cover_slides[0]
    cover_source_layout = slide_layout_part(cover, cover_source_slide)
    template_content_layout = f"ppt/slideLayouts/slideLayout{content_layout_index}.xml"
    require(template, template_content_layout)

    template_slides = presentation_slide_parts(template)
    ending_source_slide: str | None = None
    ending_source_layout: str | None = None
    if not no_ending:
        index = ending_slide_index or len(template_slides)
        if index < 1 or index > len(template_slides):
            raise MergeError(f"ending slide index out of range: {index} (template has {len(template_slides)})")
        ending_source_slide = template_slides[index - 1]
        ending_source_layout = slide_layout_part(template, ending_source_slide)

    template_master = slide_layout_part(template, template_slides[0])
    # slide_layout_part returns a layout; follow it to its master.
    template_master_rels = parse_rels(template, template_master)
    master_rel = next((rel for rel in template_master_rels if relation_type(rel) == "slideMaster"), None)
    if master_rel is None:
        raise MergeError(f"template layout has no slideMaster relationship: {template_master}")
    template_master = resolve_target(template_master, master_rel.get("Target", ""))

    master_part = allocate_indexed_part(content, "ppt/slideMasters", "slideMaster")
    selected_layouts: list[str] = []
    for part in (cover_source_layout, template_content_layout, ending_source_layout):
        if part and part not in selected_layouts:
            selected_layouts.append(part)
    layout_map: dict[str, str] = {}
    for source_layout in selected_layouts:
        destination_layout = allocate_indexed_part(content, "ppt/slideLayouts", "slideLayout")
        content[destination_layout] = require(template if source_layout in template else cover, source_layout)
        layout_map[source_layout] = destination_layout

    # Copy and rewire selected layout relationship parts.
    copied_tags: set[str] = set()
    for source_layout, destination_layout in layout_map.items():
        source_package = template if source_layout in template else cover
        rels = parse_rels(source_package, source_layout)
        for rel in list(rels):
            kind = relation_type(rel)
            if kind == "slideMaster":
                rel.set("Target", relative_target(destination_layout, master_part))
            elif kind == "image":
                copy_media_relation(content, source_package, source_layout, destination_layout, rel)
            elif rel.get("TargetMode") == "External":
                continue
            else:
                raise MergeError(f"unsupported layout relationship {kind}: {source_layout}")
        content[rels_name(destination_layout)] = xml_bytes(rels)

    # Copy master XML, retain only selected layout IDs, and rewire its rels.
    master_xml = ET.fromstring(require(template, template_master))
    master_rels = parse_rels(template, template_master)
    layout_rel_map: dict[str, str] = {}
    theme_part: str | None = None
    for rel in list(master_rels):
        kind = relation_type(rel)
        if kind == "slideLayout":
            source_target = resolve_target(template_master, rel.get("Target", ""))
            if source_target not in layout_map:
                master_rels.remove(rel)
                continue
            rel.set("Target", relative_target(master_part, layout_map[source_target]))
            layout_rel_map[rel.get("Id", "")] = source_target
        elif kind == "theme":
            source_target = resolve_target(template_master, rel.get("Target", ""))
            theme_part = allocate_indexed_part(content, "ppt/theme", "theme")
            content[theme_part] = require(template, source_target)
            rel.set("Target", relative_target(master_part, theme_part))
        elif kind == "image":
            copy_media_relation(content, template, template_master, master_part, rel)
        elif rel.get("TargetMode") == "External":
            continue
        else:
            raise MergeError(f"unsupported master relationship {kind}: {template_master}")
    if theme_part is None:
        raise MergeError("template master has no theme relationship")

    layout_id_list = master_xml.find("p:sldLayoutIdLst", NS)
    if layout_id_list is None:
        raise MergeError("template master has no sldLayoutIdLst")
    for node in list(layout_id_list):
        if node.get(qn("r", "id")) not in layout_rel_map:
            layout_id_list.remove(node)
    registered = {node.get(qn("r", "id")) for node in layout_id_list}
    if registered != set(layout_rel_map):
        raise MergeError("master layout ID list does not match selected layout relationships")
    content[master_part] = xml_bytes(master_xml)
    content[rels_name(master_part)] = xml_bytes(master_rels)

    def clone_slide(source_package: dict[str, bytes], source_slide: str, layout_part: str) -> tuple[str, set[str]]:
        destination_slide = allocate_indexed_part(content, "ppt/slides", "slide")
        content[destination_slide] = require(source_package, source_slide)
        rels = parse_rels(source_package, source_slide)
        slide_tags: set[str] = set()
        for rel in list(rels):
            kind = relation_type(rel)
            if kind == "notesSlide":
                rels.remove(rel)
            elif kind == "slideLayout":
                rel.set("Target", relative_target(destination_slide, layout_part))
            elif kind == "image":
                copy_media_relation(content, source_package, source_slide, destination_slide, rel)
            elif kind == "tags":
                slide_tags.add(copy_tag_relation(content, source_package, source_slide, destination_slide, rel))
            elif rel.get("TargetMode") == "External":
                continue
            else:
                raise MergeError(f"unsupported slide relationship {kind}: {source_slide}")
        content[rels_name(destination_slide)] = xml_bytes(rels)
        return destination_slide, slide_tags

    cover_slide, tags = clone_slide(cover, cover_source_slide, layout_map[cover_source_layout])
    copied_tags.update(tags)
    ending_slide: str | None = None
    if ending_source_slide and ending_source_layout:
        ending_slide, tags = clone_slide(template, ending_source_slide, layout_map[ending_source_layout])
        copied_tags.update(tags)

    # Repoint every original body slide to the injected content layout. When
    # an SVG author marks its section label semantically, move that text into
    # the template's native, editable title frame before packaging the slide.
    template_section_frame: ET.Element | None = None
    for body_slide in body_slides:
        body_xml = ET.fromstring(require(content, body_slide))
        has_section_label = any(
            node.get("name") == SECTION_LABEL_SHAPE
            for node in body_xml.findall(".//p:cNvPr", NS)
        )
        if has_section_label:
            if template_section_frame is None:
                template_section_frame = find_template_section_frame(
                    template,
                    template_slides,
                    template_content_layout,
                    left_inset_px=section_frame_left_inset_px,
                )
            content[body_slide] = move_section_label_into_template_frame(
                content[body_slide],
                template_section_frame,
                section_frame_font=section_frame_font,
            )
        rels = parse_rels(content, body_slide)
        layouts = [rel for rel in rels if relation_type(rel) == "slideLayout"]
        if len(layouts) != 1:
            raise MergeError(f"{body_slide}: expected one layout relationship")
        layouts[0].set("Target", relative_target(body_slide, layout_map[template_content_layout]))
        content[rels_name(body_slide)] = xml_bytes(rels)

    # Add the master and cover/ending slides to the presentation graph.
    pres = ET.fromstring(require(content, "ppt/presentation.xml"))
    pres_rels = ET.fromstring(require(content, "ppt/_rels/presentation.xml.rels"))
    master_list = pres.find("p:sldMasterIdLst", NS)
    slide_list = pres.find("p:sldIdLst", NS)
    if master_list is None or slide_list is None:
        raise MergeError("content presentation is missing master or slide ID list")
    master_ids = [int(node.get("id", "0")) for node in master_list]
    slide_ids = [int(node.get("id", "0")) for node in slide_list]
    master_rid = add_relationship(pres_rels, "slideMaster", relative_target("ppt/presentation.xml", master_part))
    ET.SubElement(
        master_list,
        qn("p", "sldMasterId"),
        {"id": str(max(master_ids, default=2147483647) + 1), qn("r", "id"): master_rid},
    )
    next_slide_id = max(slide_ids, default=255) + 1
    cover_rid = add_relationship(pres_rels, "slide", relative_target("ppt/presentation.xml", cover_slide))
    cover_id_node = ET.Element(qn("p", "sldId"), {"id": str(next_slide_id), qn("r", "id"): cover_rid})
    slide_list.insert(0, cover_id_node)
    if ending_slide:
        ending_rid = add_relationship(pres_rels, "slide", relative_target("ppt/presentation.xml", ending_slide))
        ET.SubElement(
            slide_list,
            qn("p", "sldId"),
            {"id": str(next_slide_id + 1), qn("r", "id"): ending_rid},
        )
    content["ppt/presentation.xml"] = xml_bytes(pres)
    content["ppt/_rels/presentation.xml.rels"] = xml_bytes(pres_rels)

    ct = content_types_root(content)
    add_override(ct, master_part, CONTENT_TYPES["master"])
    add_override(ct, theme_part, CONTENT_TYPES["theme"])
    for layout in layout_map.values():
        add_override(ct, layout, CONTENT_TYPES["layout"])
    add_override(ct, cover_slide, CONTENT_TYPES["slide"])
    if ending_slide:
        add_override(ct, ending_slide, CONTENT_TYPES["slide"])
    for tag in copied_tags:
        add_override(ct, tag, CONTENT_TYPES["tags"])
    add_media_defaults(ct, content)
    content["[Content_Types].xml"] = content_types_bytes(ct)

    verify_relationship_targets(content)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in content.items():
                archive.writestr(name, payload)
        with zipfile.ZipFile(temp_path) as archive:
            bad = archive.testzip()
            if bad:
                raise MergeError(f"merged package contains corrupt member: {bad}")
        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return MergeResult(
        output=output_path,
        body_count=len(body_slides),
        has_ending=ending_slide is not None,
        master_part=master_part,
        cover_layout_part=layout_map[cover_source_layout],
        content_layout_part=layout_map[template_content_layout],
        ending_layout_part=layout_map.get(ending_source_layout) if ending_source_layout else None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--cover", type=Path, required=True)
    parser.add_argument("--content-layout", type=int, default=2)
    parser.add_argument("--section-frame-font", default=SECTION_FRAME_FONT)
    parser.add_argument("--section-frame-left-inset-px", type=float, default=0.0)
    parser.add_argument("--ending-slide", type=int)
    parser.add_argument("--no-ending", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = merge_pptx(
            content_path=args.content,
            template_path=args.template,
            cover_path=args.cover,
            output_path=args.output,
            content_layout_index=args.content_layout,
            ending_slide_index=args.ending_slide,
            no_ending=args.no_ending,
            section_frame_font=args.section_frame_font,
            section_frame_left_inset_px=args.section_frame_left_inset_px,
        )
    except (OSError, ET.ParseError, MergeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    print(f"[OK] -> {result.output}")
    print(
        f"     slides: {result.body_count + 1 + int(result.has_ending)} "
        f"(1 cover + {result.body_count} content"
        f"{' + 1 ending' if result.has_ending else ''}) | all on template master"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
