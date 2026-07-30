# WorldSpec（工作名）

WorldSpec 是面向具身资产的规范语义模型、证据模型与跨仿真器编译中间层。目标是把现有资产或图像/视频生成结果整理为可追溯、可验证、损失透明的 SimReady 资产。

> 当前仓库状态：包含 v0.1 双语文档、91 个 JSON Schema、正负示例、Rust
> Core/Validator、Canonical Digest、文件 CAS、SQLite WAL 作业索引、CLI 与
> loopback 异步 API。MuJoCo/Three.js 参考编译、Digest 绑定的 L2
> Conformance/Certificate、L3 TaskRun/RuntimeRecord 证据核验、Reference
> Predicate Engine、真实 MuJoCo 3.6.0 加载与步进、真实
> Chromium/Three.js 0.185.1 加载与截图及产物篡改拒绝已有本地执行证据；
> macOS arm64 本地 Profile 达到 L2，但尚无 Linux x86_64 参考 Profile 的
> L2 证书。H1 + 右手 Robotiq 的 A800 训练链已经完成站立、过渡、Capture、
> 任务载荷和正式 100M 阶段；100M Checkpoint 因零命令站立回归失败保持
> `non_publishable`。冻结 Supervisor 的十项门通过后，单次完整厨房暴露了
> 步行后操作平衡问题；mixed-reset-v3 达到静态 `5/5`，但修正后的
> post-walk-biased-v4 纯分布评测只有步行后 `3/5`；
> on-policy-continuation-v5 继续得到步行后 `3/5`、静态 `5/5`，但其归档
> 保留七个尚未逐项正式评估的 Checkpoint。当前只放行
> checkpoint-portfolio-v6 与 memory-isolated-v7 均保存七个候选，但逐候选
> 评估仍在正式门前因同进程设备内存生命周期 OOM；锁定 v10 已验证独立
> 派生模型目录和全新评估进程，但第一个候选在切换至 `from_rest` 套件时仍因
> 评估进程内设备状态累积 OOM。suite-isolated-v11 已在真实 A800 上完成
> 七候选训练与 14/14 隔离评测，关闭了运行链路问题；但最佳候选的步行后
> 套件仅 4/5，正式操作平衡门失败，策略保持 `non_publishable`。
> v13 在真实 A800 上完成七候选和 14/14 隔离评测，但所有候选都在同一个
> 步行后状态失败，最终仍为步行后 `4/5`、静态 `5/5`。v14 随后使用 50%
> 静态、25% 固定困难状态索引 565、25% 均匀冻结状态库完成真实 A800 训练
> 和全部 14/14 隔离评测；七个候选仍全部为步行后 `4/5`、静态 `5/5`。
> 固定困难测试的六项指标虽改善，但正式操作平衡门未改变，策略仍为
> `non_publishable`。下一步必须先形成新的控制设计 ADR；当前不允许自动
> 重试、启动完整厨房单次、厨房 5/5、100M 或声明
> L3。真实
> A800/H100 图像/视频生成、完整 CAD/USD 原生运行、授权明确的真实厨房联合
> 证据和 H1 厨房 5/5 均未完成，所以产品 v0.1 尚未整体验收。

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
python3 scripts/validate_h1_composition.py --bundle <bundle> --output <report>
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
