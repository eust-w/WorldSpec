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

## Attempt-03 结果

Attempt-03 的 A800 重放、四类产物回传、Receipt 生成和摘要交叉校验均已
完成；诊断仍稳定定位为 `right_hip_yaw` 的 `joint_limit`，正式控制门失败。

最后的离线 Schema 审计发现 Report 实现使用
`basis/failedChecks/dynamicComparisonIsInformational`，而冻结 Schema 要求
`staticSemanticEquivalent`。因此正式诊断门仍按失败处理，不放宽 Schema。
修正后的结构已经使用 Attempt-03 的真实产物在本地完成 Report、
Equivalence 和 Receipt 三份 Schema 验证；下一次仍使用新提交、镜像和
Attempt。

## Attempt-04 结果

Attempt-04 的 A800 重放、四类产物回传、Receipt、诊断完备性和静态等价性
均完成；重放仍终止于 `right_hip_yaw` 的 `joint_limit`，正式控制门失败。

本地逐行 Trace Schema 审计在第 181 行发现 `activePolicy=blend`，而诊断
Schema 只列出 `motion/capture/stand`。`blend` 是冻结 A4 Supervisor 已有的
五步策略混合状态，不是本轮引入的控制变化，因此这是诊断契约枚举遗漏。
Attempt-04 正式诊断门仍按失败归档。修正只把 `blend` 加入诊断 Trace 的
活动策略枚举，不修改控制器、门槛、策略、场景、种子或运行参数；后续使用
新提交、新镜像和新 Attempt。

## Attempt-05 结果

Attempt-05 在 Drobodata A800 上完成单次等价诊断重放。远端源码、不可变
OCI、三份策略 Checkpoint、旧 A5-C 证据和包锁均通过启动前身份校验；
Report、Controller、225 条诊断 Trace、Equivalence 和 Receipt 完整回传并
通过独立 SHA-256、大小和离线 Schema 审计。

结果为：

- `formalDiagnosticReplayGate=passed`；
- `formalControlGate=failed`；
- `controllerStatus=non_publishable`；
- 四个终止通道完整，唯一触发通道为 `joint_limit`；
- 本次重放终止关节为 `right_hip_yaw`；
- 静态语义等价通过，动态 Trace 差异只作信息证据；
- 旧 A5-C 的历史根因仍为 `unknown`，不得追溯性改写；
- A5、5/5、100M 和 L3 均未执行。

至此 ADR-0024 的诊断修正目标已经完成。下一步若要修复控制行为，必须另立
控制设计 ADR；本流程不自动继续。
