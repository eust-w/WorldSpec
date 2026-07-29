---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0020-h1-fixed-kitchen-integration.md
last-verified: 2026-07-29
---

# ADR-0020：H1 固定厨房全闭环集成探针

## 背景

ADR-0019 已在真实 A800 上得到通过的 Motion → Capture → Stand 三策略
Supervisor。A4 只覆盖四秒行走—停稳，不证明操作任务。用户选择 A5，要求把冻结
Supervisor 接入“打开抽屉 → 抓杯 → 放入并释放 → 关闭抽屉”的固定场景闭环。

## 决策

新增 `fixed_kitchen_full_loop_probe` 研究阶段：

- 腿部只使用 A4 已冻结的 Motion、Capture、Stand Checkpoint 和 Supervisor；
- 右臂使用位置 Jacobian 阻尼最小二乘目标和现有 PD 阻抗执行器；
- 右手 Robotiq 使用声明的 `0` 张开、`255` 闭合命令；
- 场景只使用 WorldSpec 自制 primitive 柜体、滑动抽屉、把手、支撑轨和短圆柱杯
  代理，不复制第三方真实厨房资产；
- 抓取只依赖物理接触，不允许隐藏 weld、mocap attachment、teleport 或状态改写；
- 状态机顺序固定为站稳、接近把手、夹紧、拉开、释放、接近杯子、夹紧、抬起、
  放入、释放、撤回、推闭抽屉、最终保持；
- 先运行一次探针；仅单次通过后才继续相同固定场景的其余四次，五次全部通过才
  形成 `integration_candidate`；
- 任一相位超时、跌倒、非有限值、抽屉未曾打开、杯子未最终处于抽屉内并稳定释放、
  或抽屉未最终关闭，都 fail closed；
- 不启动 100M 训练，不做自动调参或自动重试。

## 证据边界

即使固定场景 5/5 通过，A5 仍只允许标记
`research_integration_only / internal_only`，禁止宣称 L3。原因是：

- H1 到 Robotiq 的安装位姿证据仍为 `estimated / unvalidated`；
- 场景是合成 primitive 代理，不是权利明确的真实厨房物理证据；
- 没有随机初始化、物理参数扰动或真机鲁棒性证据。

真实 A800 运行前，文档状态只能是 Accepted Design；代码、Schema、本地 MuJoCo
加载或 GPU 镜像构建都不能替代行为 Witness。
