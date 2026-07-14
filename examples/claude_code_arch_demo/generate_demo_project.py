#!/usr/bin/env python3
"""Generate a theme demo project for Claude Code architecture analysis."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ppt_master.svg_layouts import LayoutSpec, render_layout  # noqa: E402
from scripts.validate_project_contract import confirmation_digest, default_visual_profile  # noqa: E402


CANVAS_W = 1280
CANVAS_H = 720
OUTPUT_DIR = Path(__file__).resolve().parent
SVG_DIR = OUTPUT_DIR / "svg_output"
NOTES_DIR = OUTPUT_DIR / "notes"


def page_schema(slide: dict[str, object], slide_id: str) -> dict[str, object]:
    legacy = str(slide["density"])
    density = {"anchor": "balanced", "dense": "dense", "breathing": "breathing"}[legacy]
    rhythm_role = {"anchor": "anchor", "dense": "continuity", "breathing": "transition"}[legacy]
    archetype = str(slide["layout_archetype"])
    purpose = {
        "layered_arch": "architecture",
        "waterfall": "process",
        "swimlane": "process",
        "flywheel": "process",
        "iceberg": "summary",
        "pyramid": "summary",
    }.get(archetype, "summary")
    emphasis = "single-focal" if legacy == "anchor" else "distributed" if legacy == "dense" else "ranked"
    items = [str(item) for item in slide["items"]]
    result: dict[str, object] = {
        "schema": "ghb.page-schema.v1",
        "slide_id": slide_id,
        "page_purpose": purpose,
        "layout_variant": f"{archetype}/default",
        "density": density,
        "rhythm_role": rhythm_role,
        "emphasis": emphasis,
        "budgets": {"max_text_chars": min(240, 100 + sum(map(len, items))), "max_nodes": len(items)},
    }
    if emphasis == "single-focal":
        result["focal_target"] = "primary-structure"
    return result


SLIDES = [
    {
        "file": "01_stack-overview.svg",
        "title": "Claude Code 工作栈",
        "part": "Part 1 · Stack",
        "message": "Claude Code 的输出不是单次回答，而是由规划、工具、工作区和验证共同构成的执行栈。",
        "layout_archetype": "layered_arch",
        "density": "anchor",
        "items": ["用户目标", "计划与推理", "工具调用", "工作区改动", "验证与交付"],
        "reason": "主题是稳定的能力分层，用 layered_arch 最直观。",
        "alternatives": ["pyramid", "staircase"],
        "notes": "先建立总图：用户看到的是对话，真正的运行结构是一个带约束的执行栈。",
        "side": [
            ("约束", "权限、脏工作树、验证门槛会改写执行路径"),
            ("结果", "交付必须以真实文件和验证证据为准"),
        ],
    },
    {
        "file": "02_request-waterfall.svg",
        "title": "请求如何收敛成改动",
        "part": "Part 2 · Flow",
        "message": "从模糊需求到最终补丁，Claude Code 会把任务逐步收敛成可执行的局部动作。",
        "layout_archetype": "waterfall",
        "density": "dense",
        "items": ["理解需求", "检查上下文", "定位改动", "实施验证", "形成交付"],
        "reason": "主题是单向收敛流程，用 waterfall 表达阶段推进最贴切。",
        "alternatives": ["funnel", "timeline"],
        "notes": "强调不是直接写代码，而是逐步缩小问题空间，直到能安全编辑和验证。",
        "side": [
            ("关键判断", "何时搜索、何时测试、何时必须停下确认"),
            ("风险点", "过早动手通常直接放大返工成本"),
        ],
    },
    {
        "file": "03_collaboration-swimlane.svg",
        "title": "用户 / Agent / 工具 协同",
        "part": "Part 3 · Roles",
        "message": "Claude Code 的效率来自角色分工：用户定目标，Agent 决策，工具提供真实环境反馈。",
        "layout_archetype": "swimlane",
        "density": "dense",
        "items": ["用户", "主 Agent", "Shell / Git"],
        "reason": "这是典型的角色 × 流程关系，swimlane 是正确结构。",
        "alternatives": ["matrix", "waterfall"],
        "notes": "这一页帮助理解为什么工具输出不是附属品，而是决策闭环的一部分。",
        "side": [
            ("用户负责", "定义标准、授权边界、确认关键选择"),
            ("Agent负责", "建上下文、做取舍、组织结果"),
        ],
        "overlay": "swimlane_flow",
    },
    {
        "file": "04_feedback-flywheel.svg",
        "title": "观察 - 改动 - 验证 飞轮",
        "part": "Part 4 · Feedback",
        "message": "高质量结果来自持续反馈：每一轮验证都会反过来塑造下一轮修改。",
        "layout_archetype": "flywheel",
        "density": "breathing",
        "items": ["读取现状", "形成假设", "实施改动", "运行验证", "修正结论"],
        "reason": "主题强调正反馈闭环，flywheel 比线性流程更准确。",
        "alternatives": ["timeline", "waterfall"],
        "notes": "这页解释为什么验证不是结尾动作，而是驱动下一轮更准修改的核心机制。",
        "side": [
            ("飞轮中心", "真实反馈，而不是主观自信"),
            ("常见误区", "跳过验证会在后续轮次放大错误"),
        ],
    },
    {
        "file": "05_hidden-cost-iceberg.svg",
        "title": "表层效率 vs 深层成本",
        "part": "Part 5 · Constraints",
        "message": "表面上看是快速改文件，水面以下其实是权限、状态和风险控制的系统成本。",
        "layout_archetype": "iceberg",
        "density": "anchor",
        "items": ["快速响应", "上下文构建", "状态核对", "安全验证"],
        "reason": "主题明确区分表层感知与深层约束，iceberg 最合适。",
        "alternatives": ["layered_arch", "pyramid"],
        "notes": "这一页解释 Claude Code 为什么必须看 git 状态、看真实文件、跑验证，而不是凭空回答。",
        "side": [
            ("表层感知", "用户通常只看到回复速度和修改结果"),
            ("深层代价", "真正耗时的是消除状态不确定性"),
        ],
    },
    {
        "file": "06_delivery-timeline.svg",
        "title": "一次交付的时间序列",
        "part": "Part 6 · Delivery",
        "message": "完整交付通常遵循固定节奏：读、想、改、测、交付，每一步都留下可核对痕迹。",
        "layout_archetype": "timeline",
        "density": "breathing",
        "items": ["读取代码", "制定计划", "编辑实现", "测试验证", "总结交付"],
        "reason": "主题本质是时间序列，timeline 最直接。",
        "alternatives": ["waterfall", "staircase"],
        "notes": "最后一页把前面拆开的结构重新拉回到用户最关心的结果视角：一次可靠交付是怎样形成的。",
        "side": [
            ("证据链", "改动、测试、状态检查共同构成交付证据"),
            ("落脚点", "不是看起来完成，而是被验证完成"),
        ],
    },
]


def wrap_text(text: str, width: int) -> list[str]:
    text = str(text).strip()
    if not text:
        return []
    lines: list[str] = []
    while len(text) > width:
        lines.append(text[:width])
        text = text[width:]
    lines.append(text)
    return lines


def render_multiline_text(x: int, y: int, lines: list[str], size: int, fill: str) -> str:
    parts = []
    for idx, line in enumerate(lines):
        parts.append(
            f'<text x="{x}" y="{y + idx * (size + 5)}" font-size="{size}" fill="{fill}" '
            f'font-family="\'Microsoft YaHei\', Arial, sans-serif">{line}</text>'
        )
    return "\n  ".join(parts)


def render_overlay(slide: dict[str, object]) -> str:
    if slide.get("overlay") != "swimlane_flow":
        return ""
    cells = [
        (336, 339, "提出目标"),
        (552, 339, "确认边界"),
        (768, 339, "验收结果"),
        (336, 450, "建上下文"),
        (552, 450, "选策略"),
        (768, 450, "组织交付"),
        (336, 560, "读状态"),
        (552, 560, "跑命令"),
        (768, 560, "给证据"),
    ]
    parts = []
    for x, y, label in cells:
        parts.append(
            f'<text x="{x}" y="{y}" font-size="16" font-weight="bold" fill="#2B2B2B" '
            f'font-family="\'Microsoft YaHei\', Arial, sans-serif">{label}</text>'
        )
    return "\n  ".join(parts)


def build_page(index: int, slide: dict[str, object]) -> str:
    fragment = render_layout(
        LayoutSpec(
            archetype=str(slide["layout_archetype"]),
            items=[str(item) for item in slide["items"]],
            title="",
            x=120,
            y=268,
            width=820,
            height=322,
        )
    )
    side = slide["side"]
    side_blocks = []
    for idx, (label, text) in enumerate(side):
        y = 292 + idx * 128
        side_blocks.append(
            f'<rect x="978" y="{y}" width="190" height="86" rx="14" fill="#FFFFFF" stroke="#E0E0E0" stroke-width="1"/>'
        )
        side_blocks.append(
            f'<text x="996" y="{y + 28}" font-size="15" font-weight="bold" fill="#AB1F29" '
            f'font-family="\'Microsoft YaHei\', Arial, sans-serif">{label}</text>'
        )
        side_blocks.append(render_multiline_text(996, y + 54, wrap_text(text, 14), 14, "#2B2B2B"))
    side_svg = "\n  ".join(side_blocks)
    overlay_svg = render_overlay(slide)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_W}" height="{CANVAS_H}" viewBox="0 0 {CANVAS_W} {CANVAS_H}">
  <g id="bg"><rect width="{CANVAS_W}" height="{CANVAS_H}" fill="#FFFFFF"/></g>
  <g id="bg-surface">
    <rect x="56" y="96" width="1168" height="608" rx="12" fill="#FFFFFF" fill-opacity="0.92" stroke="#E0E0E0" stroke-width="1"/>
  </g>
  <g id="header">
    <rect x="88" y="132" width="6" height="40" fill="#AB1F29"/>
    <text x="108" y="162" font-size="30" font-weight="bold" fill="#2B2B2B" font-family="'Arial Black', 'Microsoft YaHei', Arial, sans-serif">Claude Code 架构解析</text>
    <line x1="88" y1="190" x2="1192" y2="190" stroke="#E0E0E0" stroke-width="1"/>
    <text x="1192" y="162" text-anchor="end" font-size="14" fill="#AB1F29" font-family="'Microsoft YaHei', Arial, sans-serif">{slide["part"]}</text>
  </g>
  <g id="content-lead">
    <text x="120" y="228" font-size="24" font-weight="bold" fill="#2B2B2B" font-family="'Microsoft YaHei', Arial, sans-serif">{slide["title"]}</text>
    <text x="120" y="254" font-size="17" fill="#6E6E73" font-family="'Microsoft YaHei', Arial, sans-serif">{slide["message"]}</text>
  </g>
  {fragment}
  <g id="content-overlay">
  {overlay_svg}
  </g>
  <g id="side-notes">
  {side_svg}
  </g>
  <g id="footer">
    <text x="1192" y="696" text-anchor="end" font-size="13" fill="#999999" font-family="'Microsoft YaHei', Arial, sans-serif">{index:02d} / 06</text>
  </g>
</svg>
"""


def write_source() -> None:
    content = """# Claude Code架构解析

## 目标

说明 Claude Code 如何把用户请求转化为可验证的工作区改动，以及为什么高质量交付依赖真实工具反馈。

## 大纲

1. Claude Code 工作栈
2. 请求如何收敛成改动
3. 用户 / Agent / 工具 协同
4. 观察 - 改动 - 验证 飞轮
5. 表层效率 vs 深层成本
6. 一次交付的时间序列
"""
    (OUTPUT_DIR / "source.md").write_text(content, encoding="utf-8")
    sources_dir = OUTPUT_DIR / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / "source.md").write_text(content, encoding="utf-8")


def write_design_spec() -> None:
    content = """# Claude Code架构解析 Demo 设计说明

- 目的：验证 `svg_layouts.py` 的多版式组件可以承载真实技术主题，而不是只适合抽象商务话题。
- 受众：技术负责人、工程师、对 Agent 工具链感兴趣的内部分享听众。
- mode：instructional
- 配图策略：无图，仅用 GHB 模板色板、结构版式和注释卡片完成信息表达。
- 重点验证：
  - 同一主题下能否自然使用 6 种不同结构版式
  - `iceberg` 是否能表达“表层感知 vs 深层约束”
  - `swimlane`、`flywheel`、`layered_arch` 是否能组成完整架构叙事
"""
    (OUTPUT_DIR / "design_spec.md").write_text(content, encoding="utf-8")


def write_spec_lock() -> None:
    content = """canvas: viewBox 0 0 1280 720 / PPT 16:9
mode: instructional
visual_style: swiss-minimal
colors:
  primary: #AB1F29
  secondary_accent: #44546A
  success: #2E7D32
  warning: #B26A00
  text: #2B2B2B
  text_secondary: #6E6E73
  muted: #999999
  border: #E0E0E0
  surface_alt: #F6F6F7
  bg: #FFFFFF
typography:
  font_family: "'Microsoft YaHei', Arial, sans-serif"
  title_family: "'Arial Black', 'Microsoft YaHei', Arial, sans-serif"
  code_family: "Consolas, 'Courier New', monospace"
  body: 18
  title: 30
  subtitle: 22
  annotation: 13
images:
  source: none
  icons: none
  attribution: auto
"""
    (OUTPUT_DIR / "spec_lock.md").write_text(content, encoding="utf-8")


def write_notes() -> None:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    blocks = []
    for idx, slide in enumerate(SLIDES, start=1):
        blocks.append(
            f"# {idx:02d}_{slide['title']}\n\n{slide['notes']}\n"
        )
    (NOTES_DIR / "total.md").write_text("\n---\n\n".join(blocks) + "\n", encoding="utf-8")


def main() -> int:
    SVG_DIR.mkdir(parents=True, exist_ok=True)
    write_source()
    write_design_spec()
    write_spec_lock()
    write_notes()

    layout_plan = []
    claims = []
    for index, slide in enumerate(SLIDES, start=1):
        svg_path = SVG_DIR / str(slide["file"])
        svg_path.write_text(build_page(index, slide), encoding="utf-8")
        claim_id = f"claim-{index:02d}"
        claims.append(
            {
                "id": claim_id,
                "statement": slide["message"],
                "must_include": True,
                "source_reference": f"sources/source.md#{index}",
            }
        )
        row = {
                "slide": index,
                "slide_id": f"body-{index:02d}",
                "purpose": slide["title"],
                "key_message": slide["message"],
                "message": slide["message"],
                "audience": "技术负责人、工程师、Agent 工具链内部分享听众",
                "content_density": slide["density"],
                "rhythm": slide["density"],
                "layout_type": slide["layout_archetype"],
                "layout_archetype": slide["layout_archetype"],
                "density": slide["density"],
                "visual_encoding": slide["reason"],
                "editable_elements": ["title", "labels", "shapes"],
                "image_requirement": "none",
                "source_reference": f"sources/source.md#{index}",
                "speaker_note": slide["notes"],
                "items": slide["items"],
                "reason": slide["reason"],
                "alternatives": slide["alternatives"],
                "claim_ids": [claim_id],
                "page_schema": page_schema(slide, f"body-{index:02d}"),
            }
        if slide["layout_archetype"] == "swimlane":
            row["owners"] = slide["items"]
        elif slide["layout_archetype"] == "flywheel":
            row["loop_closure"] = "修正结论回到读取现状，驱动下一轮"
        elif slide["layout_archetype"] == "timeline":
            row["order_signal"] = "读、想、改、测、交付的固定先后顺序"
        layout_plan.append(row)
    (OUTPUT_DIR / "layout_plan.json").write_text(
        json.dumps(layout_plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "visual_profile.json").write_text(
        json.dumps(default_visual_profile(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "content_model.json").write_text(
        json.dumps({"schema": "ghb.content-model.v1", "claims": claims}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    confirmation = {
                "schema": "ghb.confirmation.v1",
                "status": "confirmed",
                "confirmation_source": "fixture",
                "confirmed_at": "2026-07-13T00:00:00Z",
                "decisions": {
                    "audience": "技术负责人、工程师、Agent 工具链内部分享听众",
                    "page_range": "6 body slides",
                    "mode": "instructional",
                    "outline": [
                        {"title": slide["message"], "rhythm": slide["density"]}
                        for slide in SLIDES
                    ],
                    "content_tradeoffs": {"expand": ["工具反馈闭环"], "omit": [], "combine": []},
                    "visual_assets": {"image_source": "none", "icon_set": "none"},
                },
            }
    confirmation["decision_digest"] = confirmation_digest(confirmation["decisions"])
    (OUTPUT_DIR / "confirmation.json").write_text(
        json.dumps(
            confirmation,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
