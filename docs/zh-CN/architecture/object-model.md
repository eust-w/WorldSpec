---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/architecture/object-model.md
last-verified: 2026-07-28
---

# Core 对象模型

WorldDefinition 是规范对象库和多张图，不是单一场景树。

## 核心对象

- **Entity**：稳定身份、所有权、生命周期；不等于 Mesh 或 RigidBody。
- **Frame**：只表达右手系、米制的 SE(3) 空间参考；Scale 必须在 Representation 中处理或烘焙。
- **Component**：Entity 具有的版本化能力或模型，例如 rigid body、collider、camera。
- **Relation**：Frame、Entity、Component 或 Relation 之间的连接，例如 fixed、joint、constraint、transmission。
- **Representation**：某个 Subject 的 visual、collision、mass、semantic geometry 等数字表示。
- **Model**：在声明的 Purpose、Assumption 与 ValidityDomain 下选择一组 Component/Representation。

## 三类结构必须分离

1. **Ownership Tree**：版本、删除、命名空间和生命周期；必须无环。
2. **Frame Placement Graph**：权威空间父关系；每个非根活动 Frame 恰好一个驱动来源且无环。
3. **General Relation Graph**：关节、约束、传动和语义关系；允许闭环，但不能成为第二个位姿真源。

## 关键不变量

- 一个 WorldDefinition 恰好一个 World Root Entity 与 Root Frame。
- 每个 spatial Entity 恰好一个 root frame；每个 Frame 恰好属于一个 Entity。
- ID 全局唯一且不可由显示名、数组位置或后端名称推导。
- visual、collision、mass、semantic geometry 的角色必须显式分开。
- 一个活动 Model Family 必须确定性选择唯一 Model。
- Component 和 Relation 必须声明类型 URI 与 Schema 版本。
- Schema 负责结构；跨引用、唯一性、图环和证据覆盖由语义 Validator 负责。
