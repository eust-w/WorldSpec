# WorldSpec（工作名）

WorldSpec 是面向具身资产的规范语义模型、证据模型与跨仿真器编译中间层。目标是把现有资产或图像/视频生成结果整理为可追溯、可验证、损失透明的 SimReady 资产。

> 当前仓库状态：包含 v0.1 文档、29 个 JSON Schema、示例、Rust Core/Validator、Canonical Digest、文件 CAS、SQLite WAL 作业索引、CLI 与 loopback 异步 API。已实现 MuJoCo/Three.js 参考编译、Digest 绑定的 L2 Conformance/Certificate、真实 MuJoCo 3.6.0 加载与步进、真实 Chromium/Three.js 0.185.1 加载与截图，以及产物篡改拒绝；这些在当前 macOS arm64 本地 Profile 下达到 L2。还实现 OBJ 不可变修复、最小 URDF/MJCF 运动学接入、CAD/OpenUSD 隔离检查骨架，以及 TRELLIS.2/Nerfstudio 生成 Worker 的 Fail-Closed 门控。尚无 Linux x86_64 参考 Profile 的 L2 证书、真实 A800/H100 生成、完整 CAD/USD 原生运行或 H1 厨房 L3 证据，因此产品 v0.1 尚未整体验收。

## 快速入口

- [中文文档（规范真源）](docs/zh-CN/index.md)
- [English documentation (official translation)](docs/en/index.md)
- [产品需求 v0.1](docs/zh-CN/product/prd-v0.1.md)
- [架构总览](docs/zh-CN/architecture/overview.md)
- [决策登记](docs/zh-CN/decision-register.md)
- [Validator 实现边界](docs/zh-CN/implementation/validator.md)
- [JSON Schema 0.1](schemas/0.1/)
- [OpenAPI v1](openapi/worldspec-v1.yaml)
- [最小示例](examples/)

## 基线范围

```text
SourceBundle -> AssetDraft -> WorldDefinition
WorldDefinition + TargetProfile + BuildIntent
    -> ArtifactBundle + LossReport + BuildManifest
    -> ConformanceReport + Certificate
```

v0.1 计划认证 MuJoCo 与 Three.js。OpenUSD 仅作为输入和原生载荷保留 Profile，不代表 Isaac Sim 已获运行认证。

## 验证

```bash
python3 scripts/validate_baseline.py
python3 scripts/validate_compilers.py
python3 scripts/validate_robot_ingestion.py
python3 scripts/validate_l2_certification.py
python3 scripts/validate_l2_threejs.py
git diff --check
```

前两个 L2 脚本分别需要真实 MuJoCo 3.6.0 和 Playwright Chromium。它们生成与当前 OS/架构匹配的本地 TargetProfile，签发 unsigned L2 Certificate，并验证 Bundle 被篡改后签发必然失败。仓库中的 Linux x86_64 参考 TargetProfile 不会因本地 Mac 测试而被冒充通过。

Rust Validator：

```bash
cargo run --quiet -p worldspec-cli -- \
  validate examples/minimal-cube/world.json --output json

cargo test --workspace
```

`worldspec validate` 当前执行 Draft 2020-12 Schema 校验，以及已登记的跨对象不变量。`worldspec-server` 默认只监听 `127.0.0.1:8090`；该 API 还没有账号、多租户或远程网络安全边界。

## 许可状态

已接受的产品策略是 `AGPL-3.0 + 商业许可 + CLA`。正式商业许可、CLA 及完整法律文件仍待法务确认；当前仓库中的说明不能替代法律意见。参见 [许可治理](docs/zh-CN/governance/licensing.md)。
