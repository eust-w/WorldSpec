---
status: Accepted
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0002-document-and-schema-binding.md
last-verified: 2026-07-28
---

# ADR-0002：文档真源与 Schema 绑定

## 决策

仓库是文档真源。所有正式文档全量中英双语，中文为规范真源，英文为官方译本。

v0.1 机器绑定采用 JSON 与 JSON Schema Draft 2020-12。YAML 仅可作为未来作者格式，进入系统前必须确定性转换为规范 JSON。

## 后果

CI 必须检查双语镜像、元数据、链接、JSON、`$ref` 和示例。翻译冲突以中文和 Accepted ADR 为准。
