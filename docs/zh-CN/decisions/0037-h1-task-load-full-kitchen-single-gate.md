---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0037-h1-task-load-full-kitchen-single-gate.md
last-verified: 2026-07-30
---

# ADR-0037：H1 任务载荷完整厨房单次门控

## 背景

ADR-0036 的 A6-S Job `worldspec-h1-midterm-69xm4` 已在真实 Drobodata
A800 上完成。五次行走—停稳与五次零命令站立回归全部通过，
`formalTaskLoadSupervisorGate=passed`。Report、Controller 与 Trace 已回传并
通过 SHA-256 校验。

这只证明 100M Motion Policy 与冻结 Capture/Stand Supervisor 在静态 A5-CK
右臂载荷下兼容。它不证明全身任务控制、抽屉接触、杯子抓放或完整任务。

历史 `fixed_kitchen_full_loop_probe` 在首轮通过后会立即追加四次运行，且其正式
Report 只有 5/5 才能通过，不能表达 ADR-0036 冻结的“单次 A5 后再决定是否
5/5”。它还使用已知在 `reach_handle` 失败的四关节 Jacobian 控制器。

## 决策

新增 `task_load_fixed_kitchen_single_probe`（A6-K1）研究阶段：

1. Motion、Capture、Stand Policy 与 A6-S 完全相同；
2. 行走和初始停稳期间保留 A6-S 的静态右臂姿态及显式偏置力；
3. 任务阶段复用 A5-CK 的全身 QP、动态右臂跟踪、任务策略迟滞交接、人体工学
   场景和前向域内基座恢复契约；A5-CK 失败证据只作为控制契约血缘，不能被
   重新标记为已通过；
4. 执行完整 13 相位：
   站稳、接近把手、夹紧、拉开、释放、接近杯子、夹紧、抬起、放入、释放、
   撤回、推闭抽屉和最终保持；
5. 抓取继续只依赖物理接触，禁止 weld、mocap attachment、teleport 或状态
   改写；
6. 只运行固定种子 `41` 的一个 Episode。无论通过或失败都回传 Report、
   Controller 与逐步 Trace；
7. 单次通过只产生 `single_integration_candidate`，仍禁止 5/5、L3 和公开
   发布声明；
8. 只有单次门通过时，才允许创建独立的固定场景 5/5 Profile；失败则停止并
   根据本次精确相位、终止通道和接触证据另立控制决策。

## 证据边界

- A6-S 的通过结果不能替代本阶段运行；
- Schema、CPU 测试或 OCI 构建不能替代 A800 行为 Witness；
- 自制 primitive 场景与 Robotiq 安装位姿仍是
  `generated / estimated / internal_only`；
- 即使后续 5/5 通过，仍需权利、真实厨房物理证据和 L3 独立审查。
