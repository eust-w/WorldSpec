---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/pipelines/ingestion.md
last-verified: 2026-07-28
---

# 资产接入

所有输入先生成 `SourceBundle`，包含文件 Digest、格式探测、权利声明、扫描报告、单位/坐标线索和 Native Payload 索引；随后生成 `AssetDraft`，不得直接生成认证 WorldDefinition。

## Profile

| Profile | 输入 | 主要动作 | 典型待确认项 |
|---|---|---|---|
| Mesh | GLB、OBJ | 节点、Mesh、纹理、材质、单位推断 | 尺度、法线、空心/实心 |
| Robot | URDF、MJCF | Link/Body、Joint、惯量、Mesh、原生扩展 | 控制器、传动、闭环 |
| CAD | STEP、IGES | 装配、B-Rep、tessellation、PMI payload | 单位、特征历史、GD&T |
| OpenUSD | USD family | Prim、材质、物理 schema、variants payload | 专有 schema、插件 |

## 阶段

```text
quarantine -> fingerprint -> parse -> normalize draft
-> extract resources -> map canonical fields
-> preserve native payload -> diagnose -> AssetDraft
```

单位、Up/Forward、手性和四元数顺序必须显式记录。推断值是 Claim，不得伪装为源声明。源文件保持只读，任何修复产生新 Blob 与 Derivation。

“支持输入”与“完全理解输入”必须分开报告。

## 当前实现证据

Rust Forge 已实现解析器之前的源扫描：大小上限、ZIP/归档隔离门、XML 外部实体拒绝、远程/路径穿越引用拒绝；ROS `package://` 仅作为受控包内引用保留。OBJ Doctor 已实现顶点、面、包围盒、退化面和畸形行诊断，以及“移除退化面”的不可变修复。修复前后资源分别进入 CAS，并生成带源/输出 Digest 的 Derivation。

这只是 OBJ 参考切片，不代表 GLB、机器人、CAD 或 OpenUSD 已完成语义接入。USDZ 等归档当前会被隔离门拒绝，直到受限展开 Worker 完成。
