---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/compiler/mujoco.md
last-verified: 2026-07-28
---

# MuJoCo 参考后端

当前参考实现已能把规范合成刚体、fixed/revolute/prismatic/ball 关系、primitive box 和 CAS 中已解析的 OBJ 表示降级为：

```text
model.xml
compile-summary.json
build-manifest.json
loss-report.json
worldspec.lock.json
```

本实现已用本机 MuJoCo 3.6.0 `MjModel.from_xml_path` 原生加载并短步进验证最小立方体、真实复制进 Bundle 的 OBJ，以及由最小 URDF/MJCF 提取的两 Link/一 Joint 结构。编译层级使用 Frame Placement Graph，不使用 Entity Ownership Tree。只有 visual Mesh 时会禁用其碰撞并报告 `unsupported`；没有可解析资源或尺寸时会生成诊断 box 并记为 `approximated`；物理证据未解析时另行报告 `resolved-physics-evidence: unsupported`。这些结果都不得用于任务认证。

仍未实现的目标范围包括 GLB 到 MuJoCo Mesh 转换、纹理、完整惯量、材质、相机、光源、执行器、传感器以及 Native Payload round-trip。tendon、equality、plugin 等能力在实现前必须报告 `unsupported`，不能静默丢失。

L2 完整认证仍需锁定环境 ConformanceReport、资源/单位/Frame/质量惯量检查和证书；当前原生加载烟测不等于已签发 L2。L3 再运行选定刚体行为：自由落体、静置、斜面、关节限位、抽屉开合或抓取保持。

不承诺与其他后端逐帧轨迹一致，只认证指定测试和容差。
