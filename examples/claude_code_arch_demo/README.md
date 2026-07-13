# Claude Code 架构解析 Demo

这个示例项目用于验证 `GHB-PPT-SKILL` 新增的结构型 SVG 版式，主题为“Claude Code 架构解析”。

默认假设：

- 受众：技术负责人 / 工程师
- mode：`instructional`
- 配图：无图，纯结构表达
- 验证目标：版式多样性 + SVG 技术安全性

生成与验证：

```bash
python3 examples/claude_code_arch_demo/generate_demo_project.py
python3 scripts/ppt_master/svg_quality_checker.py examples/claude_code_arch_demo
python3 scripts/ppt_master/check_layout_diversity.py examples/claude_code_arch_demo
```

主要产物：

- `source.md`
- `design_spec.md`
- `spec_lock.md`
- `layout_plan.json`
- `notes/total.md`
- `svg_output/*.svg`
