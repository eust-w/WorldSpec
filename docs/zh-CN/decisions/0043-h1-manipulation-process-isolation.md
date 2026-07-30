---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0043-h1-manipulation-process-isolation.md
last-verified: 2026-07-30
---

# ADR-0043：H1 操作平衡训练与评估进程隔离

## 背景

memory-isolated-checkpoint-portfolio-v7 已在 Drobodata A800 作业
`worldspec-h1-midterm-rfkl4` 中真实运行。训练完成到 17,203,200 步并保存
全部七个 Checkpoint，但 platform allocator、`jax.clear_caches()` 和垃圾
回收仍未释放同一 Python 进程中的全部 JAX/XLA/Warp 设备上下文。候选评估
切换到 `from_rest` 环境时，Warp 申请 100,663,296 字节失败。正式操作平衡门
仍未执行，因此该结果不是策略质量失败。

## 决策

新增 process-isolated-checkpoint-portfolio-v8：

1. 第一个 Python/CUDA 进程只生成状态库、训练七个 Checkpoint、保存精确
   Progress Record 与绑定清单，然后正常退出；
2. Shell 在第一个进程成功退出后启动全新的 Python/CUDA 进程；
3. 第二个进程只读校验 Profile、输入 Checkpoint、状态库、候选步和摘要，
   再执行原有十项固定门控；
4. 训练与评估之间的绑定清单使用 Canonical Digest，任一文件、Profile 或
   候选集合漂移即 fail closed；
5. Warm Start、教师策略、训练步数、环境规模、随机种子、候选排序和全部
   质量门保持不变；
6. v7 的日志与 Job/Pod Manifest 进入独立运行失败证据；不自动启动完整厨房
   单次或 5/5。

## 证据边界

- v7 证明真实 A800 训练完成并再次暴露同进程显存生命周期问题，不产生策略
  质量结论；
- 进程隔离只改变运行时生命周期，不改变学习问题、控制语义或验收门；
- v8 只有在产物完整交接并通过正式门后，才可作为 Manipulation Policy 候选；
- v8 若仍在正式门前失败，必须继续标记为运行时失败。
