---
status: Accepted
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0004-inputs-and-native-payload.md
last-verified: 2026-07-28
---

# ADR-0004：输入与原生载荷

## 决策

v0.1 输入范围为 GLB、OBJ、URDF、MJCF、STEP、IGES、OpenUSD、单图、多视角和视频。

CAD/USD 使用“Profile 完备 + Native Payload 保留”：已知字段进入可编辑 Core；PMI、GD&T、特征历史、专有 Schema 和未知字段按源 Blob/Digest 保存。

## 后果

接受输入不等于理解全部语义。原生载荷不能覆盖 Core，不能被静默删除；跨目标不能应用时写入 LossReport。
