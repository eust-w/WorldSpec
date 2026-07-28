---
status: Accepted
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0005-targets-and-certification.md
last-verified: 2026-07-28
---

# ADR-0005：目标后端与认证

## 决策

v0.1 认证后端为 MuJoCo 与 Three.js。OpenUSD 只是输入/保留 Profile，不承诺 Isaac Sim 运行认证。

自动生成资产默认最高 L2 Target Loadable。绑定任务 Profile 并通过行为测试后可达 L3 Task Validated，但 Generated/Estimated 证据等级不自动提升。

## 后果

认证绑定版本化 Profile、Bundle、报告和运行环境。Three.js 不绑定物理后端时只认证视觉/交互加载。禁止跨后端逐帧一致和无损互转表述。
