# Workflow Modes

本文件是 Quick / Standard / Strict 的权威定义。模式只改变作者合同和治理
强度，不改变 GHB 模板保真、正文可编辑和最终文件必须可打开的底线。

## Quick

必需输入：

- `sources/source.md`
- `svg_output/*.svg`

适合草稿和内部预览。跳过确认合同、内容模型、视觉画像、证据清单和强制
视觉评审。仍需完成 SVG/PPTX 基础结构和一次渲染检查，不能作为正式发布。

## Standard

默认正式模式。作者只维护：

### brief.json

```json
{
  "schema": "ghb.brief.v1",
  "status": "confirmed",
  "confirmation_source": "user",
  "confirmed_at": "2026-07-22T00:00:00Z",
  "audience": "技术与业务管理人员",
  "purpose": "内部技术分享",
  "duration_minutes": 30,
  "page_count": "18-22",
  "mode": "briefing",
  "visual_style": "professional-modern",
  "template": "GHB default",
  "assets": {"image_source": "provided", "icon_set": "phosphor"}
}
```

### deck_plan.json

```json
{
  "schema": "ghb.deck-plan.v1",
  "story": {
    "opening": "为什么需要企业级 Agent Skill",
    "development": "设计方法、执行流程和质量保障",
    "ending": "落地建议与行动计划"
  },
  "style": {"tone": "专业、现代、技术感", "density": "balanced", "variation": "high"},
  "slides": [
    {
      "page": 1,
      "id": "body-01",
      "type": "process",
      "message": "Skill 执行由四个连续阶段组成",
      "layout": "horizontal-process",
      "visual_priority": "流程关系",
      "source_refs": ["sources/source.md#流程"]
    }
  ]
}
```

`style.content_profile` 是可选字段，未设置时不改变 Standard 的当前行为。用户明确需要
“结论先行、证据比较、业务含义”的内容组织方式时，可写入：

```json
{"content_profile": "consulting-evidence-cn-v1"}
```

它是内容档案，不是 `brief.json.visual_style` 的替代品；详细规则见
[content-styles/consulting-evidence-cn-v1.md](content-styles/consulting-evidence-cn-v1.md)。

`style.visual_profile` 也是可选字段。用户明确要求将“咨询研究报告式”视觉落到正文时，
可与内容档案组合填写：

```json
{
  "content_profile": "consulting-evidence-cn-v1",
  "visual_profile": "consulting-research-cn-v1"
}
```

它锁定以 `KaiTi` 为默认意图的研究式内容、细分隔线、蓝/灰证据图和来源页脚，同时保留 GHB
左上 Logo、右上原生章节标题框（可见右边线贴齐页面边界）和模板正文底版；封面与致谢页仍沿用 GHB。字段缺失时不会改变任何默认 GHB 视觉。详见
[visual-styles/consulting-research-cn-v1.md](visual-styles/consulting-research-cn-v1.md)。构建报告必须记录实际写入 PPTX 的字体；不能把缺失的 `KaiTi` 静默渲染为无衬线字体。

`ghb_ppt.py plan --workflow-mode standard` 会投影 `confirmation.json`、
`content_model.json`、`layout_plan.json`、`design_spec.md` 和 `spec_lock.md`，
供现有转换器兼容使用。投影文件不要求用户逐份维护。

Standard 硬门：确认、来源覆盖、可编辑性、结构/溢出、最终渲染和人工逐页
检查。详细语义标记、全局视觉画像、完整证据 manifest 和 warning waiver
不是作者合同。

## Strict

适合外部发布、合规或审计场景。使用完整合同和证据生命周期。Strict
release 必须同时传入 `--review --require-review`；评审未通过或被跳过即失败。

## 视觉构图边界

所有模式都保留模板页眉、页脚和画布边界。正文默认使用安全区而不是固定
内容矩形：`x=64..1216, y=170..680`。只有 Strict 或模板 profile 明确要求时，
才强制某个固定 `body_surface` 矩形。
