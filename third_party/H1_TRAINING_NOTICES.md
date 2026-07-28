# H1 training third-party source notices

This notice is deliberately separate from `THIRD_PARTY_NOTICES.md`: changing a
training framework notice must not change the digest of an already composed H1
and Robotiq asset bundle.

## MuJoCo Playground

- Upstream: <https://github.com/google-deepmind/mujoco_playground>
- Locked release: `v0.2.0`
- Locked commit: `124a73fa3303f75a62f8fe04d329b829ed0ebdfb`
- License: Apache-2.0.
- Selected source files, their digests, and the intended MuJoCo/MJX, Warp, and
  Brax JAX PPO integration are recorded in `h1-training.lock.json`.
- The source lock is not a target-runtime lock and is not evidence that PPO has
  run or that a policy exists.

This notice is an engineering record, not a final legal opinion. Public
distribution remains blocked by the repository's legal-release gate.
