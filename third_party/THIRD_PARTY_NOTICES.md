# Third-party source notices

This file records sources selected for the internal WorldSpec v0.1 H1 kitchen
reference case. The binary assets and policy are **not vendored in this
repository**. `h1-kitchen.lock.json` binds exact upstream commits, file or tree
digests, sizes, and license-file digests.

## MuJoCo Menagerie

- Upstream: <https://github.com/google-deepmind/mujoco_menagerie>
- Locked commit: `71f066ad0be9cd271f7ed58c030243ef157af9f4`
- `unitree_h1`: Copyright Unitree Robotics, BSD-3-Clause.
- `robotiq_2f85`: Copyright ROS-Industrial, BSD-2-Clause.
- Changes made by WorldSpec, when materialized: composition, namespacing,
  gripper mounting, control binding, and task-scene integration. The original
  upstream payload remains immutable.

## Unitree RL Gym

- Upstream: <https://github.com/unitreerobotics/unitree_rl_gym>
- Locked commit: `276801e46c5d433564f24658bac64f254b7d2d4b`
- Selected H1 locomotion policy, deployment configuration, reference runner,
  and model interface: Copyright Unitree Robotics, BSD-3-Clause.
- The policy is third-party executable model data. It must be loaded only in an
  isolated worker and verified by SHA-256 before use.

The notices above are engineering records, not a final legal opinion. Public
distribution remains blocked by the repository's legal-release gate.
