---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/compiler/mujoco.md
last-verified: 2026-07-28
---

# MuJoCo 参考后端

输出 `MJCF Bundle`：

```text
scene.xml
meshes/
textures/
native/
build-manifest.json
loss-report.json
conformance-report.json
certificate.json
```

映射范围包括静态/动态刚体、fixed/revolute/prismatic/ball joint、碰撞、质量惯量、基础材质、相机、光源、执行器与选定传感器。tendon、equality、plugin 等专有能力优先 round-trip 保留；跨目标导出按 Profile 报告。

L2 必须使用锁定版本的 MuJoCo 原生加载器编译模型，并检查资源、单位、Frame、质量/惯量和数值有限性。L3 再运行选定刚体行为：自由落体、静置、斜面、关节限位、抽屉开合或抓取保持。

不承诺与其他后端逐帧轨迹一致，只认证指定测试和容差。
