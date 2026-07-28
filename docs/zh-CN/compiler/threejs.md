---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/compiler/threejs.md
last-verified: 2026-07-28
---

# Three.js 参考后端

当前参考实现输出：

```text
scene.glb
scene-manifest.json
compile-summary.json
build-manifest.json
loss-report.json
worldspec.lock.json
```

编译器用一个显式根变换把规范 +Z Up、+X Forward、右手系映射到 glTF/Three.js +Y Up、-Z Forward，并在 Manifest 中记录。稳定 WorldSpec ID 保存于 glTF node extras。Scale 只用于 Representation/node，不进入物理 Frame。

当前仅完整生成诊断 box 的 glTF metallic-roughness 材质；未解析的 Mesh、着色器、程序材质和神经表示必须进入 LossReport。已用 Three.js 0.185.1 与真实 Chromium 页面验证 GLB 加载、稳定 ID、边界尺寸、相机和截图。

Three.js Bundle 用于预览、检查和调试。完整 L2 仍需将浏览器结果写入 ConformanceReport 并签发证书；当前浏览器烟测不等于已签发 L2。除非绑定独立物理后端及对应 Profile，不认证动力学、接触或传感器物理。
