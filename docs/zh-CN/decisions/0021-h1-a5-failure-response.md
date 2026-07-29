---
status: Pending Decision
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0021-h1-a5-failure-response.md
last-verified: 2026-07-29
---

# ADR-0021：H1 A5 首次行为失败后的处理

## 已确认事实

2026-07-29，A5 在一张 NVIDIA A800-SXM4-80GB 上完成了第一次真实任务运行。
运行使用锁定的 Motion、Capture、Stand Checkpoint 和镜像
`sha256:f3eaaa71...89f0d8`。结果为 `formalTaskGate=failed`，其余四次没有执行，
也没有启动 100M。

失败证据表明：

- H1 完成 1.3973 米前进，最低基座高度为 0.9883 米，最低直立余弦为 0.9941；
  没有提前终止、NaN、关节越限或异常接触；
- 任务停在 `reach_handle`，100 步后目标误差仍约 0.3926 米；
- 杯子在机器人到达前从初始高度 1.1928 米跌到地面约 0.0349 米，说明两条侧轨
  没有形成有效支撑面；
- MJX 日志出现 1069 次 broadphase capacity overflow，实际提示至少需要
  `nconmax/naconmax=19`，而当前单环境容量为 16。

规范化失败报告见
[`kitchen-task.a800.failed.json`](../../../examples/h1-kitchen/kitchen-task.a800.failed.json)，
完整内部 Trace Digest 为
`sha256:20d065ef...fc506f`。

## 待用户选择

### A5-R（推荐）：先修复基准，再验证控制

- A5 专用接触容量提升到至少 32；
- 用真实碰撞支撑面替换无效侧轨，但不增加 weld、mocap 或隐藏附件；
- 在启动 A800 前增加固定基座 IK 可达性扫描，并把柜体相对位置约束到明确的
  可达余量；
- 保持 A4 三策略、四关节右臂控制器和物理抓取边界不变；
- 重新运行一次门控，只有通过才继续 5/5。

这条路线先消除已证实的无效基准条件，最容易区分“控制器能力不足”和“场景本身
不可执行”。

### A5-C：同时升级操作控制器

在 A5-R 的修复基础上，允许站稳后的底座微调或任务空间 MPC/QP，使基座和右臂
共同满足把手与杯子的可达性。它更接近真实全身操作，但会扩大 A5 控制边界，验证
成本和安全审计范围更大。

### A5-S：只保存失败证据并停止

不再消耗 A800 资源。A5 保持 `non_publishable`，后续等真实厨房几何、经验证的
安装位姿或更完整操作策略到位后再恢复。

不建议只增加超时时间或直接开始任务训练：当前杯子支撑和接触容量已明确无效，
这样做会把基准缺陷混入策略。
