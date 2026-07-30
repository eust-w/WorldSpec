---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0042-h1-manipulation-checkpoint-memory-isolation.md
last-verified: 2026-07-30
---

# ADR-0042：H1 Checkpoint 组合评估显存隔离

## 背景

checkpoint-portfolio-v6 已在 Drobodata A800 作业
`worldspec-h1-midterm-xzrb5` 中真实运行。PPO 训练完成并保存了七个预期
Checkpoint，但逐候选评估尚未完成时，Warp 在切换到 `from_rest` 环境时发生
GPU OOM，最终连 48 字节分配也失败。作业因此在正式质量门之前终止，不能被
解释为策略失败或通过。

Job 使用了 `XLA_PYTHON_CLIENT_PREALLOCATE=false`，但默认 BFC allocator
仍会保留已释放的 JAX 缓冲区。训练可执行体、步行后环境和静态环境的编译缓存
在同一进程累计，挤占了 Warp 的设备内存。

## 决策

新增 memory-isolated-checkpoint-portfolio-v7：

1. 设置 `XLA_PYTHON_CLIENT_ALLOCATOR=platform`，使已释放的 JAX 缓冲区归还
   CUDA；
2. PPO 训练结束后删除训练专用环境和教师策略引用，并调用
   `jax.clear_caches()` 与垃圾回收；
3. 在步行后套件切换到静态套件前，以及每个 Checkpoint 候选评估结束后，
   重复清理编译缓存；
4. v6 的 Warm Start、训练步数、超参数、状态库、随机种子、候选集合、排序
   规则和全部质量门保持不变；
5. v6 的日志、Job/Pod Manifest 和 OOM 分类进入独立运行失败证据；
6. 只在 v7 的正式门完成且通过后，才继续独立 Manipulation Policy 集成和
   完整厨房单次门。

## 证据边界

- v6 只证明训练完成到七个 Checkpoint 保存以及评估运行时 OOM，不产生策略
  质量结论；
- 显存隔离是运行时修正，不是控制参数、训练目标或门槛调整；
- platform allocator 可能降低运行速度，但不改变任务语义；
- v7 若仍在正式门前失败，必须保存新证据并停止；不得把缺失结果当作策略失败
  或通过。
