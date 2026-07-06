# Template Analysis — 如何分析一个 PPTX 模板

> Phase 0 的详细操作手册。目标是搞清模板结构，确定 3 件事：① 封面是哪页；② 正文页用哪个版式做背景；③ 品牌色与字体。

## 1. 解包

```bash
mkdir -p /tmp/tpl && cd /tmp/tpl && unzip -oq "$TEMPLATE"
```

## 2. 总览：页数 / 母版 / 版式 / 主题 / 图片

```bash
echo "slides:   $(ls ppt/slides/*.xml | wc -l)"
echo "masters:  $(ls ppt/slideMasters/*.xml | wc -l)"
echo "layouts:  $(ls ppt/slideLayouts/*.xml | wc -l)"
echo "themes:   $(ls ppt/theme/*.xml | wc -l)"
echo "media:    $(ls ppt/media/ 2>/dev/null | wc -l) files"
ls ppt/media/ 2>/dev/null
```

## 3. 各 slide 用的 layout

```bash
for i in $(ls ppt/slides/*.xml | sed 's|.*/slide||;s|\.xml||'); do
  lay=$(grep -o 'slideLayout[0-9]*\.xml' ppt/slides/_rels/slide$i.xml.rels 2>/dev/null | head -1)
  echo "slide$i -> $lay"
done
```

→ 找出**封面页**（通常 slide1 → slideLayout1）和**章节/内容页**（如 slide2/3 → slideLayout2，作正文背景候选）。

## 4. 各 layout / master 引用了哪些图片

```bash
for f in ppt/slideLayouts/_rels/*.xml.rels ppt/slideMasters/_rels/*.xml.rels; do
  echo "--- $(echo $f | sed 's|ppt/||;s|/_rels/||;s|.xml.rels||') ---"
  grep -o 'Target="[^"]*media[^"]*"\|Target="[^"]*slideMaster[^"]*"\|Target="[^"]*theme[^"]*"' "$f"
done
```

→ 确定候选正文版式 + 其母版引用的背景装饰图（这些图会出现在每张正文页背后）。

## 5. slide 是否有幻灯片级图片（非版式继承）

```bash
python3 -c "
import re,glob
for f in sorted(glob.glob('ppt/slides/slide*.xml')):
    n=f.split('slide')[-1].split('.')[0]
    pics=re.findall(r'<p:pic>(.*?)</p:pic>', open(f).read(), re.S)
    print(f'slide{n}: {len(pics)} pic shape(s)')
"
```

→ 若章节页的装饰图是**幻灯片级** `<p:pic>`（而非版式/母版级），则仅靠"改版式引用"无法让正文页获得该装饰，需把那些 pic 形状也复制到正文页（少见；多数模板装饰图在版式/母版级）。

## 6. 品牌色（theme + 封面文本色）

```bash
# 主题色方案
python3 -c "
import re
x=open('ppt/theme/theme1.xml').read()
m=re.search(r'<a:clrScheme[^>]*name=\"([^\"]*)\"[^>]*>(.*?)</a:clrScheme>', x, re.S)
print('Scheme:', m.group(1))
for cm in re.finditer(r'<a:(\w+)>\s*<a:(srgbClr|sysClr)\s+(?:val|lastClr)=\"([^\"]*)\"', m.group(2)):
    print(f'  {cm.group(1):12s} = #{cm.group(3)}')
"
```

封面/标题实际用的色（可能≠主题 accent，如模板用自定义品牌红）：

```bash
python3 -c "
import re
x=open('ppt/slides/slide1.xml').read()   # 封面
for m in re.finditer(r'<p:sp>(.*?)</p:sp>', x, re.S):
    sp=m.group(1)
    colors=re.findall(r'<a:srgbClr val=\"([0-9A-Fa-f]{6})\"', sp)
    sizes=re.findall(r'sz=\"(\d+)\"', sp)
    texts=re.findall(r'<a:t>([^<]*)</a:t>', sp)
    if texts: print('texts=',texts,'sizes=',sizes,'colors=',colors)
"
```

→ 取标题文本的色作 `spec_lock.colors.primary`（如 `#AB1F29`）。

## 7. 字体（theme）

```bash
python3 -c "
import re
x=open('ppt/theme/theme1.xml').read()
m=re.search(r'<a:fontScheme[^>]*name=\"([^\"]*)\"[^>]*>(.*?)</a:fontScheme>', x, re.S)
for label,blk in [('Major(标题)','<a:majorFont>'),('Minor(正文)','<a:minorFont>')]:
    mm=re.search(blk+r'(.*?)</a:'+(blk[3:-1])+r'>', m.group(2), re.S)
    if mm:
        latin=re.search(r'<a:latin typeface=\"([^\"]*)\"', mm.group(1))
        print(f'{label}: latin={latin.group(1) if latin else None}')
"
```

→ SVG `typography` 字体栈：标题/正文用模板字（如 Arial Black / Arial），中文加 `Microsoft YaHei`，结尾 PPT-safe：
`font_family: "'Microsoft YaHei', Arial, sans-serif"`

## 8. 决策汇总

完成 Phase 0 后应得到：

| 项 | 值（示例） | 用途 |
|----|-----------|------|
| 封面页 | slide1 → slideLayout1 | template-fill 克隆目标 |
| 正文背景版式 | slideLayout2（章节页用） | `--content-layout 2` |
| 背景装饰图 | image1, image2, image6 | 合并脚本自动注入 |
| 品牌色 | #AB1F29 | `spec_lock.colors.primary` |
| 字体 | Arial Black / Arial / Microsoft YaHei | `spec_lock.typography` |

把这些填入 Phase 1–4 的命令与 spec_lock 即可。
