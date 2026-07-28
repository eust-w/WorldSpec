---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/interfaces/reports.md
last-verified: 2026-07-28
---

# 报告与公共产物

## LossReport

逐项记录源语义、目标能力、Lowering 状态、理由、影响和诊断。状态仅允许：

`exact / converted / approximated / baked / emulated / dropped / unsupported`

空报告只表示全部 exact，且必须由 Coverage 检查证明；不能省略。

## BuildManifest

锁定 WorldDefinition、EvidenceGraph、TargetProfile、BuildIntent、Compiler、BackendCalibration、Model/Representation 选择、源资源和输出 Artifact 的 Digest。

## ConformanceReport

记录测试 ID/版本、环境、输入、结果、指标、容差和证据 Artifact。`not_run` 与 `unknown` 不能计为 pass。

## Certificate

只汇总 L0–L3、适用 Profile、所有引用 Digest、签发者和有效性；不复制测试细节。任何输入、工具、Profile 或测试规则变化都使证书失效。

报告必须可机器读取、不可静默修改，并区分 Design 声明与实际运行证据。
