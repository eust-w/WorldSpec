---
status: Accepted
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0006-generation-and-corpus.md
last-verified: 2026-07-28
---

# ADR-0006：生成适配器与 Corpus

## 决策

生成后端可插拔。单图参考后端为能输出 PBR GLB、MIT 许可的 [TRELLIS.2](https://github.com/microsoft/TRELLIS.2)；多视角/视频使用 [Nerfstudio](https://github.com/nerfstudio-project/nerfstudio) 类重建适配器。

Conformance Corpus 由自制合成基准和一个权利状态确认的真实厨房端到端案例构成。

## 后果

模型/权重/数据许可分别锁定。真实厨房在权利确认前只放 Manifest 和证据占位。性能、显存和处理成本进入 Benchmark，不写假指标。
