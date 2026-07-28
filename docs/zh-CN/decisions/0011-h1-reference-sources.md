---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0011-h1-reference-sources.md
last-verified: 2026-07-28
---

# ADR-0011：H1 厨房参考来源

## 决策

首个 H1 厨房 L3 案例固定使用：

- MuJoCo Menagerie `unitree_h1`，提交
  `71f066ad0be9cd271f7ed58c030243ef157af9f4`，BSD-3-Clause；
- MuJoCo Menagerie `robotiq_2f85`，同一提交，BSD-2-Clause；
- Unitree RL Gym H1 `motion.pt`、MuJoCo 配置和参考接口，提交
  `276801e46c5d433564f24658bac64f254b7d2d4b`，BSD-3-Clause。

精确文件、大小、目录树和许可证 Digest 位于
[`third_party/h1-kitchen.lock.json`](../../../third_party/h1-kitchen.lock.json)。
仓库不直接提交网格或策略权重；安全拉取器只能检出锁定提交，逐项校验后将其标记为
`verified_not_executed`。下载和 Digest 通过不代表模型、策略或 H1 行为已经运行。

WorldSpec 自己负责 H1 与 Robotiq 的组合、命名空间、安装变换、ControlProfile
和 Derivation。原始载荷保持不可变。本地 dirty BiGym 资产只作为差分参考，不作为
规范来源或可分发载荷。

## 理由

Menagerie 为两个模型分别提供逐目录许可证与衍生说明，Unitree RL Gym 明确提供
H1 MuJoCo 部署配置和只控制十个腿部关节的策略。把来源锁和组合 Derivation 分开，
可避免从用户工作树复制不明确载荷，并允许审计后续安装或控制改动。

## 未解决事项

- Robotiq 已选右手单夹爪；安装变换和权威 TCP 仍需通过组合实验确定；
- 上游策略与组合后的 H1 动力学兼容性必须真实运行验证；
- 第三方许可证记录不替代项目商业双许可、CLA 与品牌法务审查。
