#!/usr/bin/env python3
"""fix_cover_font.py — 把封面 PPTX 中的字体替换为微软雅黑（Microsoft YaHei）。

GHB_PPT_模板的封面文本原用楷体，与正文 SVG（Microsoft YaHei）不一致。
template-fill 克隆封面时会保留楷体，故 apply 之后跑本脚本统一改成微软雅黑。

用法:
    python3 scripts/fix_cover_font.py exports/cover.pptx
    python3 scripts/fix_cover_font.py exports/cover.pptx "Microsoft YaHei"

幂等：已是微软雅黑则无变化。
"""

import re
import shutil
import sys
import zipfile


def main():
    if len(sys.argv) < 2:
        print("usage: fix_cover_font.py <cover.pptx> [font]")
        sys.exit(1)
    path = sys.argv[1]
    font = sys.argv[2] if len(sys.argv) > 2 else "Microsoft YaHei"

    with zipfile.ZipFile(path, "r") as z:
        data = {n: z.read(n) for n in z.namelist()}

    slides = sorted(n for n in data if re.match(r"ppt/slides/slide\d+\.xml$", n))
    changed = 0
    # 长串先替换，避免被短串误伤（带引号精确匹配，顺序其实无关）
    for old in ("Arial Unicode MS", "Arial Black", "楷体", "Arial"):
        needle = f'typeface="{old}"'
        repl = f'typeface="{font}"'
        for s in slides:
            x = data[s].decode("utf-8")
            if needle in x:
                data[s] = x.replace(needle, repl).encode("utf-8")
                changed += 1

    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in data.items():
            z.writestr(n, d)
    shutil.move(tmp, path)
    print(f"[OK] cover font -> {font} (touched {changed} slide part(s))")


if __name__ == "__main__":
    main()
