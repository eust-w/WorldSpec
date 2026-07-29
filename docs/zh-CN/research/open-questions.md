---
status: Research
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/research/open-questions.md
last-verified: 2026-07-30
---

# 开放技术问题

这些问题需要 Spike/Benchmark，不得在规范正文中写成已解决。

1. **生成质量**：TRELLIS.2 类后端在目标品类的几何、PBR、显存、延迟和许可成本。
2. **视频/多视角**：Nerfstudio 类重建到可编辑 Mesh/3DGS 的质量与人工分钟数。
3. **尺度与隐藏面**：最小补拍/标尺/深度证据如何降低不确定性。
4. **物理推断**：类别与材料先验对质量、惯量、摩擦的误差分布。
5. **碰撞选择**：primitive、CoACD 与任务感知代理的准确度/性能前沿。
6. **行为一致性**：MuJoCo 与后续 Isaac/Genesis Profile 的任务相关容差。
7. **Predicate**：semantic truth 与 execution truth 的偏差检测。
8. **成本**：Time-to-SimReady、Human Minutes、GPU Cost、Certification Pass Rate。
9. **CAD/USD**：PMI、GD&T、特征历史和专有 Schema 的 round-trip 可验证范围。
10. **H1 全身控制**：在新 ADR 授权任何后续 A800 Attempt 前，如何让诊断产物在
    运行后处理失败时仍可交接，以及如何重新获得 `joint_limit`、`fall_height`、
    `fall_upright`、`nonfinite` 的真实终止证据。

每个实验必须冻结输入 Corpus、工具版本、硬件、指标和失败样本。
