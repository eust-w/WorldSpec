---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0012-h1-robotiq-composition.md
last-verified: 2026-07-28
---

# ADR-0012：H1 与 Robotiq 的可追溯组合

## 决策

WorldSpec 不修改 Menagerie 的 H1 或 Robotiq 源树。组合器重新校验
[`h1-kitchen.lock.json`](../../../third_party/h1-kitchen.lock.json)，复制不可变原生载荷，
对 Robotiq 的 Body、Joint、Mesh、Material、Default Class、Tendon、Equality 和
Actuator 做确定性命名空间处理，再根据独立 CompositionProfile 挂到 H1 的目标 Body。

组合 Profile 支持一个或两个 Robotiq 2F-85。v0.1 当前只提供一个**右手单夹爪实验候选**：

```text
parent body: right_elbow_link
translation: [0.28, 0, -0.015] m
rotation wxyz: [0.70710678, 0, 0.70710678, 0]
```

该变换把夹爪局部 `+Z` 接近轴映射到 H1 前臂局部 `+X`，安装 Frame 原点取 H1
肘部碰撞胶囊的远端。独立安装 Frame 包裹 Robotiq 原生根 Body，不覆盖源模型自带
变换；TCP 绑定上游 `pinch` Site 并由组合后的 Frame 图计算。安装变换是 `estimated`
组合假设，不是厂商安装接口或已测量 TCP。
右手候选不等于最终任务必须采用一个夹爪；最终选择左、右或双夹爪仍是待用户冻结的
Task/ControlProfile 决策。

## 已取得的证据

在 macOS arm64、Python 3.12.9、MuJoCo 3.6.0 上，锁定来源组合后的 Bundle 已被
`MjModel.from_xml_path` 原生加载，并短步进 20 次：

```text
bodies=36, joints=28, actuators=20, meshes=29, sites=2
initial finite=true, after finite=true
```

重复组合得到相同 Bundle Digest
`sha256:07e8122f3c922c1ae65e3eca17c34af4cb7a5e92dc926ecb07da9fdbda95938b`。
篡改一个网格后，完整性检查失败并阻止原生加载。脱敏报告见
[`examples/h1-kitchen/native-load-conformance.darwin-arm64.json`](../../../examples/h1-kitchen/native-load-conformance.darwin-arm64.json)。

## 证据边界

本证据只说明候选组合：

- 来源与许可证可追溯；
- 命名空间无冲突；
- 产物确定且篡改会被拒绝；
- 当前本地 MuJoCo 可加载并短步进。

它不证明：

- 安装板几何、TCP 或可达空间正确；
- Unitree RL Gym 策略适配组合后动力学；
- H1 能稳定行走、保持平衡或完成厨房任务；
- Linux x86_64、A800/H100 或真实机器人验证；
- 最终应采用单夹爪还是双夹爪。
