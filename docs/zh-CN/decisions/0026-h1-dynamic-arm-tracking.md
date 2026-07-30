---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0026-h1-dynamic-arm-tracking.md
last-verified: 2026-07-30
---

# ADR-0026：H1 固定底座四关节动态右臂跟踪

## 背景

A5-CF Job `worldspec-h1-midterm-45v9r` 在 Drobodata A800 上正常执行，
Profile Digest 为 `sha256:2fd53b...02a54`。交接修复达到了预期：
任务阶段没有再出现 `right_hip_yaw` 越限，也没有 NaN、容量溢出或异常接触。

控制门仍因 `fall_height` 失败。Trace 显示：

- `whole_body_settle` 的 25 步均使用 Stand Policy；
- `track_handle` 的前 62 步仍使用 Stand Policy，但 QP 同时持续改变躯干和右臂；
- 基座逐步向后加速，QP 命令范数达到 `0.05` 后才进入 Motion Policy；
- 最低基座高度降至 `0.777434 m`，最终触发 `fall_height`；
- 终止时无关节越限，Task Handoff 自身也没有失败。

因此，提高 Motion 进入阈值或放宽高度门不能解决问题。失败已从“策略硬切换”
收敛为“操作控制改变质心，而冻结 Stand Policy 无法保持动态平衡”。

## 决策

采用 A5-CG 最小变体：

1. 保留场景、三份策略、种子、质量门、关节范围、终止条件和显式
   `qfrc_bias` 前馈。
2. QP 的底座平面速度、底座偏航和躯干速度固定为零，只控制
   `right_shoulder_pitch`、`right_shoulder_roll`、`right_shoulder_yaw`
   和 `right_elbow`。
3. 躯干及未控制上肢使用原 Profile 的固定参考目标，不再每步把当前漂移位置
   当成新目标。
4. 任务阶段腿部保持 Stand Policy；不增加隐藏约束、mocap、运动学瞬移，
   不修改门槛。
5. 新 Profile 必须绑定 A5-CF 的 Report、Controller 和 Trace Digest。
6. 先通过固定底座 MuJoCo CPU 跟踪门，再构建新镜像并只执行一次单卡 A800
   控制 Spike。

## 执行结果

A5-CG Job `worldspec-h1-midterm-9zmdg` 在真实 A800 上完成，Profile Digest
为 `sha256:994c9a...3cb0d`。动态臂隔离与 Stand Policy 均按设计启用，
没有关节越限、NaN 或交接失败，但在第 301 条 Trace 触发 `fall_height`，
因此控制门失败且 Controller 保持 `non_publishable`。

新 Trace 进一步表明：TCP 在约
`[1.8351, -0.1891, 1.1411] m` 已短暂稳定，而旧把手目标仍为
`[1.87, -0.21, 1.075] m`。QP 为继续追逐低位目标进入近奇异屈肘姿态，
随后基座在直立状态下持续向后滑移。A5-CG 由此证明“锁定底座命令和躯干”
仍不足以补偿不合适的任务几何。

## 放行边界

- 通过只产生内部 `control_candidate`；
- 不证明物理抓取、完整抽屉任务、5/5、L3 或 100M 训练；
- A5-CF 失败证据保持不可变；
- 若 A5-CG 仍失败，必须按新 Trace 决定是否需要平衡感知操作策略，而不是继续
  静默调参。
