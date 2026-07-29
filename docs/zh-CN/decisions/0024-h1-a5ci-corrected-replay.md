---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0024-h1-a5ci-corrected-replay.md
last-verified: 2026-07-30
---

# ADR-0024：A5-CI 修正重放与失败产物优先交接

## 背景

固定 Attempt `a5-ci-20260730-termination-replay-01` 已在一张 Drobodata
A800 上执行，但诊断后处理错误 `KeyError: 'control'` 发生在正式 Report 和产物
交接之前。该 Attempt 不能证明本次重放或旧 A5-C 的控制终止原因。

用户随后明确授权“继续修正，通过为止”。该授权只扩展 A5-CI 的诊断修正，
不自动授权 A5、5/5、100M 或把失败 Controller 发布为候选。

## 决策

1. 以 `formalDiagnosticReplayGate=passed` 作为本轮“通过”的目标；
   `formalControlGate` 继续独立记录，不作为诊断实现正确性的替代。
2. 每次修正必须使用新的源码提交、不可变 OCI Digest、Replay Profile 和
   Attempt ID；禁止 Kubernetes 自动重试。
3. 只在实现缺陷导致诊断门失败时继续修正；每次重放前重新执行源码、证据、
   集群容量和空 Namespace 预检。
4. 入口脚本新增 `artifact_failure_ready`：后处理失败时先生成失败索引，
   保持 Pod 可读取，等待 Launcher 分块回传已经生成的 Controller、Trace 或
   Equivalence 产物，再以原始失败码退出。
5. Launcher 只允许回传固定文件名，并校验大小和 SHA-256；未知路径、Digest
   不一致或 Attempt 不一致时 fail closed。
6. 诊断门通过后停止自动推进并归档结果。若 `formalControlGate=failed`，
   其精确终止原因用于下一份控制设计 ADR；不得直接进入 A5 或 100M。

## 边界

- 已失败的 Attempt-01 保持不可变，不因代码修复而追溯性通过；
- 失败产物交接提高可诊断性，不等于控制行为通过；
- 再次修改控制器、门槛、策略、场景、种子或容量会失去等价重放资格。

## Attempt-02 结果

Attempt-02 在 Drobodata A800 上完成了等价重放，诊断完备性和静态语义
等价性均通过；重放终止原因定位为 `joint_limit`，终止关节为
`right_hip_yaw`，正式控制门失败，Controller 保持 `non_publishable`。

Launcher 已复制 Report、Controller、Trace 和 Equivalence，但在生成 Receipt
时因缺少 `datetime` 导入而失败。由于 Receipt 和最终 Schema 审计未完成，
Attempt-02 的正式诊断门按失败处理，不能仅凭 Pod Report 中的 `passed` 字段
宣称完成。

修正方案不再使用内嵌 Receipt Python 片段，改为独立、可单测、先验证产物
身份再原子写入的 Finalizer。Attempt-02 仍保持不可变，修正使用新提交、新
镜像和新 Attempt。
