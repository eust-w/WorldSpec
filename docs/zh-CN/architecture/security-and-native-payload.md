---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/architecture/security-and-native-payload.md
last-verified: 2026-07-28
---

# 安全与原生载荷

## 不可信输入

GLB/OBJ/CAD/USD/URDF/MJCF、纹理、压缩包和生成结果均按不可信数据处理。接入阶段必须限制路径、大小、解压比、资源数量和解析时长，并拒绝目录穿越和外部网络引用。

插件、Python、共享库、脚本化 USD 和目标运行时扩展属于可执行内容：

- 默认不执行；
- 与数据解析分进程/容器；
- 最小权限、无隐式网络、只读源；
- 输出带工具和沙箱版本；
- 未执行不等于已验证。

## Native Payload

CAD/OpenUSD/MJCF 等输入采用两条并行路径：

1. **Canonical Mapping**：已知字段映射为可编辑 WorldSpec 对象。
2. **Opaque Preservation**：未知字段与源 Blob 按 Digest 原样保存。

Native Payload 必须声明源格式、版本、命名空间、Digest、权利状态和目标适用范围。它不得覆盖 Core 真值。回到原目标时可参与 round-trip；导出其他目标时必须在 LossReport 中报告无法解释或未应用的内容。

“保存了原始 Blob”不能表述成“跨格式无损转换”。
