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
