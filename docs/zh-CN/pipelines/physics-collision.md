---
status: Research
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/pipelines/physics-collision.md
last-verified: 2026-07-28
---

# 物理与碰撞生成

本页定义候选流程和证据边界，不宣称算法已经达到生产质量。

## 质量与惯量

候选流程是分类/材质先验、几何体积、空心/实心假设和用户证据的组合。每个结果必须输出：

- 名义值与区间/分布；
- 密度、壁厚、质心等中间 Claim；
- 方法、版本和假设；
- 适用任务与 ValidityDomain。

封闭几何可用于体积积分；非封闭/薄壳模型必须先选择质量代理，不可直接套实体体积。

## 碰撞候选

候选包括 primitive compound、convex hull、CoACD/凸分解、任务感知代理和精细碰撞。Doctor 应生成多个候选，由 BuildIntent 在准确度、速度和目标限制之间选择。

## 验证

不能只比较三角面误差。至少需要：

- 穿透、间隙和体积覆盖；
- 接触稳定与物体静置；
- 斜面滑动/滚动、跌落和关节开合；
- 任务特定插入、容纳或抓取；
- 运行时性能和接触数量。

CoACD 参数、耗时、质量误差和物理先验准确率必须由 Spike/Benchmark 决定。
