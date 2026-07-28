---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/compiler/threejs.md
last-verified: 2026-07-28
---

# Three.js 参考后端

输出：

```text
scene.glb (或多个内容寻址GLB)
scene-manifest.json
textures/
preview/
build-manifest.json
loss-report.json
conformance-report.json
certificate.json
```

编译器把规范 +Z Up、+X Forward、右手系的 Frame 转为目标场景约定，并在 Manifest 中记录变换。Scale 只能来自 Representation mapping，不进入物理 Frame。

材质优先映射 glTF PBR；不支持的着色器、程序材质或神经表示必须 baked、emulated 或 unsupported。相机、灯光、层级、实例和动画绑定需要稳定 WorldSpec ID 映射。

Three.js Bundle 用于预览、检查和调试。L2 验证资源加载、Frame/相机、材质和可见性；除非绑定独立物理后端及对应 Profile，不认证动力学、接触或传感器物理。
