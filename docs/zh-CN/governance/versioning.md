---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/governance/versioning.md
last-verified: 2026-07-28
---

# 版本与治理

## 版本对象

Schema、Component/Relation Type、Profile、Predicate、Compiler、Adapter、资产、报告和证书分别版本化。文档版本不能替代机器对象版本。

## 兼容规则

- Patch：修正文档或实现，不改变合法实例及语义结果。
- Minor：向后兼容新增可选能力。
- Major：改变必填字段、ID/单位/状态语义或 true/false 判定。

Schema `$id` 与目录版本固定；已发布 Schema 不原地修改。迁移器输出新对象、Derivation 和 MigrationReport。

## 治理流程

采用 RFC/ADR、Schema Registry、类型/能力/Profile/Predicate Registry、Conformance Suite、弃用策略和迁移策略。扩展使用受控 URI 命名空间，不得在 `properties` 中隐藏未注册的核心语义。

证书绑定所有 Digest。资产、Profile、工具、后端或测试版本变化后，旧证书保留历史但不再适用于新 Build。
