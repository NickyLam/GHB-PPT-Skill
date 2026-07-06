#!/usr/bin/env python3
"""merge_template_master.py — Unify a SVG-generated content deck onto a user
template's slide master, so EVERY slide inherits the template's background /
theme / decorations, while keeping the SVG content visuals.

Input:
  --content      SVG-generated PPTX (white background rects already removed
                 from the source SVGs, so slides are transparent)
  --template     Original user template PPTX (source of master / layouts /
                 theme / background images)
  --cover        Filled cover PPTX produced by ppt-master template-fill
                 (clones the template cover slide with new text)
  --content-layout  Template slideLayout index to drive content-page background
                 (e.g. 2 = the chapter / content layout whose decorations you
                 want behind every content page). Default 2.
  --ending-slide Template slide index to append as the ending (thank-you) page
                 (default: last slide of the template). Cloned with its layout
                 + images, hung on the template master, appended last.
  --no-ending    Do not append the template ending slide.
  --output       Final unified PPTX.

What it does:
  1. Injects the template's slideMaster (trimmed to 2 layouts) + the cover
     layout + the chosen content layout + theme + all background images as
     ADDITIONAL parts inside the content PPTX.
  2. Re-points every content slide's layout relationship to the injected
     content layout (so content pages inherit the template master + its
     background decorations).
  3. Prepends the filled cover slide (which uses the injected cover layout).
  Result: all slides share the template master; cover looks like the template
  cover, content pages look like the template's chosen layout with SVG content
  on top.

Assumptions (true for ppt-master svg_to_pptx output):
  - content PPTX has exactly one slideMaster (slideMaster1) and one theme
    (theme1); injected parts are named slideMaster2 / theme2.
  - content slides reference slideLayoutK.xml via ../slideLayouts/slideLayoutK.xml.
"""

import argparse
import zipfile
import re
import os

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFF = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def read_zip(path):
    parts = {}
    with zipfile.ZipFile(path, "r") as z:
        for i in z.infolist():
            parts[i.filename] = z.read(i.filename)
    return parts


def must(d, k):
    if k not in d:
        raise KeyError(f"missing part: {k}")
    return d[k]


def parse_rels(rels_xml: str):
    """Return list of (id, type_tail, target)."""
    out = []
    for m in re.finditer(
        r'<Relationship\s+Id="([^"]*)"\s+Type="([^"]*)"\s+Target="([^"]*)"\s*/?>',
        rels_xml,
    ):
        out.append((m.group(1), m.group(2).rsplit("/", 1)[-1], m.group(3)))
    return out


def max_layout_index(parts):
    ns = []
    for k in parts:
        m = re.match(r"ppt/slideLayouts/slideLayout(\d+)\.xml$", k)
        if m:
            ns.append(int(m.group(1)))
    return max(ns) if ns else 0


def max_rid(rels_xml: str):
    ns = [int(x) for x in re.findall(r'Id="rId(\d+)"', rels_xml)]
    return max(ns) if ns else 0


def max_sldid(pres_xml: str):
    ns = [int(x) for x in re.findall(r'<p:sldId\s+id="(\d+)"', pres_xml)]
    return max(ns) if ns else 256


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--cover", required=True)
    ap.add_argument("--content-layout", type=int, default=2)
    ap.add_argument(
        "--ending-slide",
        type=int,
        default=None,
        help="Template slide index to append as ending page (default: last slide)",
    )
    ap.add_argument(
        "--no-ending",
        action="store_true",
        help="Do not append the template ending slide",
    )
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    content = read_zip(args.content)
    template = read_zip(args.template)
    cover = read_zip(args.cover)

    # --- locate the cover slide file inside cover.pptx (single slide) ---
    cover_slide_files = sorted(
        k for k in cover if re.match(r"ppt/slides/slide\d+\.xml$", k)
    )
    if not cover_slide_files:
        raise SystemExit("cover pptx has no slide")
    cover_slide_file = cover_slide_files[0]
    cover_slide_rels = (
        cover_slide_file.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
    )

    # --- which template layout does the cover use? ---
    cover_layout_n = None
    if cover_slide_rels in cover:
        for _id, _t, tgt in parse_rels(cover[cover_slide_rels].decode("utf-8")):
            m = re.search(r"slideLayouts/slideLayout(\d+)\.xml", tgt)
            if m:
                cover_layout_n = int(m.group(1))
                break
    if cover_layout_n is None:
        raise SystemExit("could not determine cover layout from cover slide rels")
    content_layout_n = args.content_layout
    print(
        f"[info] cover layout: slideLayout{cover_layout_n} | "
        f"content layout: slideLayout{content_layout_n}"
    )

    # --- new part names inside content ---
    M = max_layout_index(content)
    cover_layout_new = M + 1
    content_layout_new = M + 2
    master_new = "slideMaster2"
    theme_new = "theme2"
    print(
        f"[info] inject: {master_new}, slideLayout{cover_layout_new} (cover), "
        f"slideLayout{content_layout_new} (content), {theme_new}"
    )

    # --- parse template master rels: rId -> (type_tail, target) ---
    m_rels = parse_rels(
        must(template, "ppt/slideMasters/_rels/slideMaster1.xml.rels").decode("utf-8")
    )
    theme_rid = None
    master_image_targets = []
    layout_rid_to_n = {}
    for rid, ttail, tgt in m_rels:
        if ttail == "theme":
            theme_rid = rid
        elif ttail == "image":
            master_image_targets.append(tgt)
        elif ttail == "slideLayout":
            mm = re.search(r"slideLayout(\d+)\.xml", tgt)
            if mm:
                layout_rid_to_n[rid] = int(mm.group(1))
    keep_rids = {
        rid
        for rid, n in layout_rid_to_n.items()
        if n in (cover_layout_n, content_layout_n)
    }
    keep_rids.add(theme_rid)
    for rid, _t, _tg in m_rels:
        if _t == "image":
            keep_rids.add(rid)

    # --- collect all images needed (master + 2 layouts) ---
    needed_images = set(os.path.basename(t) for t in master_image_targets)
    for lay_n in (cover_layout_n, content_layout_n):
        lr = must(
            template, f"ppt/slideLayouts/_rels/slideLayout{lay_n}.xml.rels"
        ).decode("utf-8")
        for _id, _t, tgt in parse_rels(lr):
            if _t == "image":
                needed_images.add(os.path.basename(tgt))
    print(f"[info] background images: {sorted(needed_images)}")

    # === 1. master (trim sldLayoutIdLst to kept layout rIds) ===
    m_xml = must(template, "ppt/slideMasters/slideMaster1.xml").decode("utf-8")

    def keep_sldLayoutId(match):
        inner = match.group(1)
        kept = "".join(
            e
            for e in re.findall(r"<p:sldLayoutId[^>]*/>", inner)
            if re.search(r'r:id="(rId\d+)"', e).group(1) in keep_rids
        )
        return f"<p:sldLayoutIdLst>{kept}</p:sldLayoutIdLst>"

    m_xml = re.sub(
        r"<p:sldLayoutIdLst>(.*?)</p:sldLayoutIdLst>",
        keep_sldLayoutId,
        m_xml,
        count=1,
        flags=re.S,
    )
    # also trim sldLayoutIdLst that may have explicit ids — keep verbatim entries that pass filter (already done)
    content[f"ppt/slideMasters/{master_new}.xml"] = m_xml.encode("utf-8")

    # master rels: kept rIds, rewire layout targets to new names + theme to theme_new
    new_m_rels = [
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{REL_NS}">'
    ]
    for rid, ttail, tgt in m_rels:
        if rid not in keep_rids:
            continue
        if ttail == "theme":
            new_tgt = f"../theme/{theme_new}.xml"
        elif ttail == "slideLayout":
            n = layout_rid_to_n[rid]
            new_n = cover_layout_new if n == cover_layout_n else content_layout_new
            new_tgt = f"../slideLayouts/slideLayout{new_n}.xml"
        else:  # image
            new_tgt = tgt  # keep image path (we copy with same basename)
        new_m_rels.append(
            f'<Relationship Id="{rid}" Type="{OFF}{ttail}" Target="{new_tgt}"/>'
        )
    new_m_rels.append("</Relationships>")
    content[f"ppt/slideMasters/_rels/{master_new}.xml.rels"] = "".join(
        new_m_rels
    ).encode("utf-8")

    # === 2. cover + content layouts (verbatim; rels rewire master + keep images) ===
    for lay_n, lay_new in (
        (cover_layout_n, cover_layout_new),
        (content_layout_n, content_layout_new),
    ):
        content[f"ppt/slideLayouts/slideLayout{lay_new}.xml"] = must(
            template, f"ppt/slideLayouts/slideLayout{lay_n}.xml"
        )
        lr = must(
            template, f"ppt/slideLayouts/_rels/slideLayout{lay_n}.xml.rels"
        ).decode("utf-8")
        lr = lr.replace("slideMaster1.xml", f"{master_new}.xml")
        content[f"ppt/slideLayouts/_rels/slideLayout{lay_new}.xml.rels"] = lr.encode(
            "utf-8"
        )

    # === 3. theme + images ===
    content[f"ppt/theme/{theme_new}.xml"] = must(template, "ppt/theme/theme1.xml")
    for img in needed_images:
        content[f"ppt/media/{img}"] = must(template, f"ppt/media/{img}")

    # === 4. cover slide -> slide{N+1}; keep tags rels, drop notesSlide, rewire layout ===
    N = len([k for k in content if re.match(r"ppt/slides/slide\d+\.xml$", k)])
    cover_new = N + 1
    content[f"ppt/slides/slide{cover_new}.xml"] = must(cover, cover_slide_file)
    new_c_rels = [
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{REL_NS}">'
    ]
    for _id, ttail, tgt in parse_rels(cover[cover_slide_rels].decode("utf-8")):
        if ttail == "notesSlide":
            continue  # drop cover notes (acceptable)
        if ttail == "slideLayout":
            new_tgt = f"../slideLayouts/slideLayout{cover_layout_new}.xml"
        elif ttail == "tags":
            # copy the tags part verbatim into content
            tgt_basename = os.path.basename(tgt)
            content[f"ppt/tags/{tgt_basename}"] = must(
                cover, f"ppt/tags/{tgt_basename}"
            )
            new_tgt = f"../tags/{tgt_basename}"
        else:
            new_tgt = tgt
        new_c_rels.append(
            f'<Relationship Id="{_id}" Type="{OFF}{ttail}" Target="{new_tgt}"/>'
        )
    new_c_rels.append("</Relationships>")
    content[f"ppt/slides/_rels/slide{cover_new}.xml.rels"] = "".join(new_c_rels).encode(
        "utf-8"
    )

    # === 5. re-point every content slide's layout -> content_layout_new ===
    repl = f'Target="../slideLayouts/slideLayout{content_layout_new}.xml"'
    for k in list(content):
        m = re.match(r"ppt/slides/_rels/slide(\d+)\.xml\.rels$", k)
        if not m or int(m.group(1)) == cover_new:
            continue
        r = content[k].decode("utf-8")
        r2 = re.sub(r'Target="\.\./slideLayouts/slideLayout\d+\.xml"', repl, r)
        content[k] = r2.encode("utf-8")

    # === 5b. ending slide (致谢页): clone template's ending slide + its layout ===
    has_ending = False
    ending_new = None
    ending_layout_new = M + 3
    if not args.no_ending:
        if args.ending_slide:
            ending_slide_file = f"ppt/slides/slide{args.ending_slide}.xml"
        else:
            end_files = sorted(
                (k for k in template if re.match(r"ppt/slides/slide\d+\.xml$", k)),
                key=lambda s: int(re.search(r"slide(\d+)\.xml", s).group(1)),
            )
            ending_slide_file = end_files[-1]
        ending_slide_rels = (
            ending_slide_file.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
        )
        ending_layout_n = None
        for _id, _t, tgt in parse_rels(template[ending_slide_rels].decode("utf-8")):
            m = re.search(r"slideLayouts/slideLayout(\d+)\.xml", tgt)
            if m:
                ending_layout_n = int(m.group(1))
                break
        if ending_layout_n is None:
            raise SystemExit("could not determine ending layout from ending slide rels")
        # reuse an already-injected layout if the ending shares cover/content layout
        if ending_layout_n == cover_layout_n:
            ending_layout_new = cover_layout_new
        elif ending_layout_n == content_layout_n:
            ending_layout_new = content_layout_new
        print(
            f"[info] ending: slide {os.path.basename(ending_slide_file)} "
            f"(layout {ending_layout_n} -> slideLayout{ending_layout_new})"
        )
        if ending_layout_new not in (cover_layout_new, content_layout_new):
            content[f"ppt/slideLayouts/slideLayout{ending_layout_new}.xml"] = must(
                template, f"ppt/slideLayouts/slideLayout{ending_layout_n}.xml"
            )
            elr = must(
                template,
                f"ppt/slideLayouts/_rels/slideLayout{ending_layout_n}.xml.rels",
            ).decode("utf-8")
            elr = elr.replace("slideMaster1.xml", f"{master_new}.xml")
            content[
                f"ppt/slideLayouts/_rels/slideLayout{ending_layout_new}.xml.rels"
            ] = elr.encode("utf-8")
            for _id, _t, tgt in parse_rels(elr):
                if _t == "image":
                    needed_images.add(os.path.basename(tgt))
        # clone ending slide as slide{N+2}
        ending_new = N + 2
        content[f"ppt/slides/slide{ending_new}.xml"] = must(template, ending_slide_file)
        new_e_rels = [
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Relationships xmlns="{REL_NS}">'
        ]
        for _id, ttail, tgt in parse_rels(template[ending_slide_rels].decode("utf-8")):
            if ttail == "notesSlide":
                continue
            if ttail == "slideLayout":
                new_tgt = f"../slideLayouts/slideLayout{ending_layout_new}.xml"
            elif ttail == "image":
                needed_images.add(os.path.basename(tgt))
                new_tgt = tgt
            elif ttail == "tags":
                tgt_basename = os.path.basename(tgt)
                content[f"ppt/tags/{tgt_basename}"] = must(
                    template, f"ppt/tags/{tgt_basename}"
                )
                new_tgt = f"../tags/{tgt_basename}"
            else:
                new_tgt = tgt
            new_e_rels.append(
                f'<Relationship Id="{_id}" Type="{OFF}{ttail}" Target="{new_tgt}"/>'
            )
        new_e_rels.append("</Relationships>")
        content[f"ppt/slides/_rels/slide{ending_new}.xml.rels"] = "".join(
            new_e_rels
        ).encode("utf-8")
        has_ending = True

    # copy any images newly needed by the ending layout/slide
    for img in needed_images:
        if f"ppt/media/{img}" not in content:
            content[f"ppt/media/{img}"] = must(template, f"ppt/media/{img}")

    # === 6. presentation.xml: add master + prepend cover slide (+ append ending) ===
    pres = must(content, "ppt/presentation.xml").decode("utf-8")
    pres_rels = must(content, "ppt/_rels/presentation.xml.rels").decode("utf-8")
    rmaster = max_rid(pres_rels) + 1
    rslide = rmaster + 1
    sldid = max_sldid(pres) + 1
    pres = pres.replace(
        "<p:sldMasterIdLst>",
        f'<p:sldMasterIdLst><p:sldMasterId id="2147483649" r:id="rId{rmaster}"/>',
        1,
    )
    pres = pres.replace(
        "<p:sldIdLst>", f'<p:sldIdLst><p:sldId id="{sldid}" r:id="rId{rslide}"/>', 1
    )
    add = (
        f'<Relationship Id="rId{rmaster}" Type="{OFF}slideMaster" '
        f'Target="slideMasters/{master_new}.xml"/>'
        f'<Relationship Id="rId{rslide}" Type="{OFF}slide" '
        f'Target="slides/slide{cover_new}.xml"/>'
    )
    if has_ending:
        rending = rslide + 1
        ending_sldid = sldid + 1
        pres = pres.replace(
            "</p:sldIdLst>",
            f'<p:sldId id="{ending_sldid}" r:id="rId{rending}"/></p:sldIdLst>',
            1,
        )
        add += (
            f'<Relationship Id="rId{rending}" Type="{OFF}slide" '
            f'Target="slides/slide{ending_new}.xml"/>'
        )
    content["ppt/presentation.xml"] = pres.encode("utf-8")
    pres_rels = pres_rels.replace("</Relationships>", add + "</Relationships>")
    content["ppt/_rels/presentation.xml.rels"] = pres_rels.encode("utf-8")

    # === 7. [Content_Types].xml ===
    ct = must(content, "[Content_Types].xml").decode("utf-8")
    if 'Extension="png"' not in ct:
        ct = re.sub(
            r"(<(?:\w+:)?Types\b[^>]*>)",
            r'\1<Default Extension="png" ContentType="image/png"/>',
            ct,
            count=1,
        )
    ov = (
        f'<Override PartName="/ppt/slideMasters/{master_new}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        f'<Override PartName="/ppt/slideLayouts/slideLayout{cover_layout_new}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        f'<Override PartName="/ppt/slideLayouts/slideLayout{content_layout_new}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        f'<Override PartName="/ppt/theme/{theme_new}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        f'<Override PartName="/ppt/slides/slide{cover_new}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
    )
    if has_ending:
        if ending_layout_new not in (cover_layout_new, content_layout_new):
            ov += (
                f'<Override PartName="/ppt/slideLayouts/slideLayout{ending_layout_new}.xml" '
                f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
            )
        ov += (
            f'<Override PartName="/ppt/slides/slide{ending_new}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        )
    # tags overrides for any tags parts we copied
    for k in content:
        m = re.match(r"ppt/tags/(.+\.xml)$", k)
        if m and f"/ppt/tags/{m.group(1)}" not in ct:
            ov += (
                f'<Override PartName="/ppt/tags/{m.group(1)}" '
                f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.tags+xml"/>'
            )
    if "</ns0:Types>" in ct:
        ct = ct.replace("</ns0:Types>", ov + "</ns0:Types>")
    else:
        ct = ct.replace("</Types>", ov + "</Types>")
    content["[Content_Types].xml"] = ct.encode("utf-8")

    # === 8. write ===
    if os.path.exists(args.output):
        os.remove(args.output)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in content.items():
            z.writestr(name, data)
    total = N + 1 + (1 if has_ending else 0)
    print(f"[OK] -> {args.output}")
    print(
        f"     slides: {total} (1 cover + {N} content"
        f"{' + 1 ending' if has_ending else ''}) | all on template master"
    )


if __name__ == "__main__":
    main()
