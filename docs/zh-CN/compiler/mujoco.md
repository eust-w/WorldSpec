---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/compiler/mujoco.md
last-verified: 2026-07-28
---

# MuJoCo 参考后端

当前参考实现已能把规范合成刚体、fixed/revolute/prismatic/ball 关系和 primitive box 降级为：

```text
model.xml
compile-summary.json
build-manifest.json
loss-report.json
worldspec.lock.json
```

本实现已用本机 MuJoCo 3.6.0 `MjModel.from_xml_path` 原生加载并短步进验证最小立方体。没有可解析碰撞资源或尺寸的表示会生成诊断 box 并明确记为 `approximated`，不得用于任务认证。

仍未实现的目标范围包括真实 Mesh/纹理资源复制、完整惯量、材质、相机、光源、执行器、传感器以及 Native Payload round-trip。tendon、equality、plugin 等能力在实现前必须报告 `unsupported`，不能静默丢失。

L2 完整认证仍需锁定环境 ConformanceReport、资源/单位/Frame/质量惯量检查和证书；当前原生加载烟测不等于已签发 L2。L3 再运行选定刚体行为：自由落体、静置、斜面、关节限位、抽屉开合或抓取保持。

不承诺与其他后端逐帧轨迹一致，只认证指定测试和容差。
