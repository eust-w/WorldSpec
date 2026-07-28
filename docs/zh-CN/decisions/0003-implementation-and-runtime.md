---
status: Accepted
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0003-implementation-and-runtime.md
last-verified: 2026-07-28
---

# ADR-0003：实现技术与参考运行环境

## 决策

实现方向为 Rust Core 与多语言绑定：Python 对接生成/科学计算，TypeScript/WASM 对接 Three.js。

v0.1 生成参考环境为 Linux + NVIDIA 80GB GPU，参考 A800/H100。该环境是测试 Profile，不是对其他平台的禁止。

## 后果

Core 语义不绑定语言。所有平台/硬件能力必须进入运行 Profile；未实测平台不得宣称支持。文档/Schema 阶段未创建产品脚手架；后续阶段已按本 ADR 加入首个 Rust Validator。
