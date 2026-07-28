---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/pipelines/generation.md
last-verified: 2026-07-28
---

# 图像与视频生成

生成是 Forge 的可插拔适配器，不进入 Core。统一接口：

```text
GenerationRequest
  -> BackendPlan
  -> RawGenerationArtifacts
  -> GenerationClaims
  -> AssetDraft
```

## 路由

- 单图：TRELLIS.2 参考适配器输出 PBR GLB 与质量报告。
- 多视角/视频：Nerfstudio 1.1.5 参考适配器输出 NeRF Checkpoint、相机、3DGS 与质量报告；v0.1 暂不宣称自动导出可认证 Mesh。
- 已有几何：跳过生成，进入 Ingestion/Doctor。

后端能力通过 Profile 声明，不允许把某一模型的私有字段写入 Core。

## 已实现的执行门

真实生成 Job 必须同时满足：

- 运行容器声明的 OCI Digest 与 `GenerationProfile.containerDigest` 完全一致；
- Job 显式申请 GPU，且 Worker 检测到 CUDA；
- 后端、版本、模态、输入数量和输出能力与 Profile 一致；
- TRELLIS.2 权重来自只读内容寻址缓存；Manifest、每个文件 SHA-256/大小、未声明文件和符号链接均被校验；
- Nerfstudio 可执行文件和 Python 包版本与锁定 Profile 一致；
- 命令使用参数数组执行，不经过 Shell；作业有超时限制。

只设置环境变量不是远程可信证明；它是由受控 Worker 启动器注入并写入报告的本地运行绑定。更强的远程证明属于后续 Profile。

生成产物写入 CAS，并附带源、模型、容器和输出 Digest。所有产物必须重新进入标准 Ingestion/Doctor；适配器禁止直接签发 Certificate。

## 证据边界

- 可见区域可标记 `reconstructed` 或 `generated`；隐藏结构必须有不确定性。
- 尺度需要标尺、相机标定、CAD 或人工尺寸证据；否则保持未知/估计。
- PBR 贴图由模型生成时保持 `generated`。
- 质量、摩擦、关节与可动性不得从视觉合理性直接升级为已测事实。

生成资产默认最高 L2。任务 Profile 与行为测试可使 Bundle 达到 L3，但不会提升上述 Claim 的权威等级。

## 当前证据状态

适配器代码、Fail-Closed 门控与模型文件篡改测试已经完成。当前仓库尚无真实 A800/H100 TRELLIS.2 或 Nerfstudio 运行证据，因此 GPU 执行状态仍为 `not_executed`，不能据此宣称生成质量、显存、时延或 L2/L3 验收完成。
