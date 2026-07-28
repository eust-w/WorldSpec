---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/product/prd-v0.1.md
last-verified: 2026-07-28
---

# 产品需求 v0.1

## 整体版本目标

v0.1 作为一个整体版本同时验收三条闭环：

1. **规范编译器**：WorldDefinition 编译为 MuJoCo Bundle 和 Three.js Bundle。
2. **Existing Asset → SimReady**：接入已有 Mesh/机器人/CAD/USD，生成 AssetDraft、WorldDefinition、报告和证书。
3. **Image/Video → AssetDraft**：单图、多视角和视频通过可插拔后端生成带 PBR/重建表示的草稿，再进入同一 Doctor/Compiler 流程。

三条线共享 Schema、EvidenceGraph、Manifest、LossReport 与认证等级，不允许各自形成隐式格式。

## 输入

v0.1 接受 GLB、OBJ、URDF、MJCF、STEP、IGES、OpenUSD、单图、多视角图片和视频。格式“接受”仅表示存在计划中的 Ingestion Profile；不代表所有原生能力都能映射到 Core。

## 用户流程

```text
ingest/generate
  -> AssetDraft
  -> inspect/resolve
  -> WorldDefinition
  -> validate
  -> compile(target profile)
  -> bundle
  -> certify
```

未知原生字段和源 Blob 必须保留；任何降级必须写入 LossReport。

## 功能需求

- CLI 与异步 Job API 提供 `ingest`、`generate`、`validate`、`compile`、`certify`、`inspect`、`bundle`。
- 本地内容寻址保存源、派生资源、Manifest、Lockfile、报告和证书。
- MuJoCo 编译输出可原生加载的 MJCF Bundle。
- Three.js 编译输出 GLB、场景 Manifest 与预览/调试 Bundle。
- 生成后端可插拔；单图参考适配器为 TRELLIS.2，多视角/视频参考适配器为 Nerfstudio 类重建后端。
- CAD/OpenUSD 使用 Profile 完备与 Native Payload 保存，不静默丢失未知字段。
- 自动生成资产默认最高 L2；只有绑定 Task Profile 并通过行为测试才可达到 L3。

## 非功能需求

- Linux + NVIDIA 80GB GPU（参考 A800/H100）是 v0.1 参考生成环境。
- 同输入、工具、Profile 和 Lockfile 应生成相同内容 Digest；跨硬件只承诺行为或统计复现。
- 所有报告可机器读取，引用不可变 Digest 和精确工具版本。
- 不可信资产按数据处理；可执行插件必须隔离，默认不执行。
- 性能、显存、成本和 CoACD 参数必须通过 Benchmark/Spike 获得，不在规范中虚构。

## 产品入口

v0.1 不建设正式 Web 工作台。Three.js Bundle 只承担预览、检查和调试，不自动成为物理评测后端。
