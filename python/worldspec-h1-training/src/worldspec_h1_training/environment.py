"""Target-bundle H1 locomotion environment.

Heavy dependencies are imported only when the locked Linux/NVIDIA runtime calls
``make_environment``. This keeps static contract tests independent of CUDA.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import TrainingError


def _preserving_update(
    current: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Update owned keys without deleting Brax wrapper state."""

    result = dict(current)
    result.update(updates)
    return result


def make_environment(profile: dict[str, Any], training_model: Path):
    """Create an MJX environment bound to the derived composition model."""

    import jax
    import jax.numpy as jp
    import mujoco
    import numpy as np
    from ml_collections import config_dict
    from mujoco import mjx
    from mujoco_playground._src import mjx_env

    control = profile["control"]
    training = profile["training"]
    validation = profile["validation"]
    capacity = profile["runtime"]["mjxCapacity"]
    config = config_dict.create(
        ctrl_dt=training["simulationTimestepSeconds"] * control["controlDecimation"],
        sim_dt=training["simulationTimestepSeconds"],
        episode_length=training["episodeLength"],
        action_repeat=1,
        impl=profile["framework"]["physicsImplementation"],
        naconmax=capacity["activeContactsPerEnvironment"] * training["numEnvs"],
        naccdmax=capacity["ccdContactsPerEnvironment"] * training["numEnvs"],
        njmax=capacity["njmax"],
    )

    class WorldSpecLoadedH1Velocity(mjx_env.MjxEnv):
        """Ten-leg-action velocity tracking on the exact H1+Robotiq target."""

        def __init__(self) -> None:
            super().__init__(config)
            self._xml_path = str(training_model)
            self._mj_model = mujoco.MjModel.from_xml_path(self._xml_path)
            self._mj_model.opt.timestep = config.sim_dt
            self._mjx_model = mjx.put_model(self._mj_model, impl=config.impl)

            def object_id(kind, name: str) -> int:
                value = mujoco.mj_name2id(self._mj_model, kind, name)
                if value < 0:
                    raise TrainingError(
                        "TRAINING_MODEL_BINDING_MISSING",
                        f"Target model has no required object: {name}",
                    )
                return int(value)

            self._policy_joint_ids = np.asarray(
                [object_id(mujoco.mjtObj.mjOBJ_JOINT, name) for name in control["policyJoints"]],
                dtype=np.int32,
            )
            self._held_joint_ids = np.asarray(
                [object_id(mujoco.mjtObj.mjOBJ_JOINT, name) for name in control["heldJoints"]],
                dtype=np.int32,
            )
            self._policy_qpos = jp.asarray(self._mj_model.jnt_qposadr[self._policy_joint_ids])
            self._policy_dof = jp.asarray(self._mj_model.jnt_dofadr[self._policy_joint_ids])
            self._held_qpos = jp.asarray(self._mj_model.jnt_qposadr[self._held_joint_ids])
            self._held_dof = jp.asarray(self._mj_model.jnt_dofadr[self._held_joint_ids])
            self._policy_actuators = jp.asarray(
                [
                    object_id(mujoco.mjtObj.mjOBJ_ACTUATOR, name)
                    for name in control["policyActuators"]
                ]
            )
            self._held_actuators = jp.asarray(
                [object_id(mujoco.mjtObj.mjOBJ_ACTUATOR, name) for name in control["heldActuators"]]
            )
            self._gripper_actuators = jp.asarray(
                [
                    object_id(mujoco.mjtObj.mjOBJ_ACTUATOR, name)
                    for name in control["gripperActuators"]
                ]
            )
            self._pelvis_body = object_id(mujoco.mjtObj.mjOBJ_BODY, "pelvis")
            self._sensor_slices: dict[str, slice] = {}
            for name in ("gyro", "upvector", "local_linvel"):
                sensor_id = object_id(mujoco.mjtObj.mjOBJ_SENSOR, name)
                start = int(self._mj_model.sensor_adr[sensor_id])
                size = int(self._mj_model.sensor_dim[sensor_id])
                self._sensor_slices[name] = slice(start, start + size)

            self._policy_kps = jp.asarray(control["policyKps"])
            self._policy_kds = jp.asarray(control["policyKds"])
            self._default_angles = jp.asarray(control["defaultAngles"])
            self._held_targets = jp.asarray(control["heldTargets"])
            self._held_kps = jp.asarray(control["heldKps"])
            self._held_kds = jp.asarray(control["heldKds"])
            self._gripper_commands = jp.asarray(control["gripperCommands"])
            self._action_scale = float(control["actionScale"])
            self._n_substeps = int(control["controlDecimation"])
            self._ctrl_lower = jp.asarray(self._mj_model.actuator_ctrlrange[:, 0])
            self._ctrl_upper = jp.asarray(self._mj_model.actuator_ctrlrange[:, 1])
            self._ctrl_limited = jp.asarray(self._mj_model.actuator_ctrllimited.astype(bool))

            qpos = np.array(self._mj_model.qpos0, copy=True)
            if qpos.size < 7:
                raise TrainingError(
                    "TRAINING_MODEL_FREEJOINT_MISSING",
                    "H1 training requires a floating-base qpos.",
                )
            qpos[0:3] = [0.0, 0.0, 0.98]
            qpos[3:7] = [1.0, 0.0, 0.0, 0.0]
            qpos[np.asarray(self._policy_qpos)] = np.asarray(control["defaultAngles"])
            qpos[np.asarray(self._held_qpos)] = np.asarray(control["heldTargets"])
            self._initial_qpos = jp.asarray(qpos)

            command = training["commandDistribution"]
            self._command_low = jp.asarray(
                [
                    command["linearVelocityX"][0],
                    command["linearVelocityY"][0],
                    command["angularVelocityYaw"][0],
                ]
            )
            self._command_high = jp.asarray(
                [
                    command["linearVelocityX"][1],
                    command["linearVelocityY"][1],
                    command["angularVelocityYaw"][1],
                ]
            )
            self._zero_command_probability = float(command["zeroCommandProbability"])
            self._minimum_height = float(validation["minimumBaseHeight"])
            self._minimum_upright = float(validation["minimumUprightCosine"])

        def _sensor(self, data, name: str):
            return data.sensordata[self._sensor_slices[name]]

        def sample_command(self, rng):
            sample_rng, zero_rng = jax.random.split(rng)
            value = jax.random.uniform(
                sample_rng,
                shape=(3,),
                minval=self._command_low,
                maxval=self._command_high,
            )
            use_zero = jax.random.bernoulli(zero_rng, self._zero_command_probability)
            return jp.where(use_zero, jp.zeros(3), value)

        def _observation(self, data, last_action, command):
            return jp.concatenate(
                [
                    self._sensor(data, "gyro"),
                    self._sensor(data, "local_linvel"),
                    self._sensor(data, "upvector"),
                    data.qpos[self._policy_qpos] - self._default_angles,
                    data.qvel[self._policy_dof],
                    last_action,
                    command,
                ]
            )

        def reset(self, rng):
            rng, command_rng = jax.random.split(rng)
            data = mjx_env.make_data(
                self.mj_model,
                qpos=self._initial_qpos,
                qvel=jp.zeros(self.mjx_model.nv),
                ctrl=jp.zeros(self.mjx_model.nu),
                impl=self.mjx_model.impl.value,
                naconmax=config.naconmax,
                naccdmax=config.naccdmax,
                njmax=config.njmax,
            )
            data = mjx.forward(self.mjx_model, data)
            info = {
                "rng": rng,
                "command": self.sample_command(command_rng),
                "last_action": jp.zeros(self.action_size),
                "step": jp.zeros((), dtype=jp.int32),
            }
            metrics = {
                "reward/tracking_linear": jp.zeros(()),
                "reward/tracking_yaw": jp.zeros(()),
                "cost/upright": jp.zeros(()),
                "cost/vertical_velocity": jp.zeros(()),
                "cost/torque": jp.zeros(()),
                "cost/action_rate": jp.zeros(()),
            }
            observation = {"state": self._observation(data, info["last_action"], info["command"])}
            return mjx_env.State(
                data,
                observation,
                jp.zeros(()),
                jp.zeros(()),
                metrics,
                info,
            )

        def step(self, state, action):
            rng, command_rng = jax.random.split(state.info["rng"])
            policy_q = state.data.qpos[self._policy_qpos]
            policy_dq = state.data.qvel[self._policy_dof]
            targets = self._default_angles + action * self._action_scale
            policy_torque = (targets - policy_q) * self._policy_kps - policy_dq * self._policy_kds
            held_q = state.data.qpos[self._held_qpos]
            held_dq = state.data.qvel[self._held_dof]
            held_torque = (self._held_targets - held_q) * self._held_kps - held_dq * self._held_kds
            ctrl = jp.zeros(self.mjx_model.nu)
            ctrl = ctrl.at[self._policy_actuators].set(policy_torque)
            ctrl = ctrl.at[self._held_actuators].set(held_torque)
            ctrl = ctrl.at[self._gripper_actuators].set(self._gripper_commands)
            limited_ctrl = jp.clip(ctrl, self._ctrl_lower, self._ctrl_upper)
            ctrl = jp.where(self._ctrl_limited, limited_ctrl, ctrl)
            data = mjx_env.step(self.mjx_model, state.data, ctrl, self._n_substeps)
            command = state.info["command"]
            local_velocity = self._sensor(data, "local_linvel")
            gyro = self._sensor(data, "gyro")
            upvector = self._sensor(data, "upvector")
            linear_error = jp.sum(jp.square(command[:2] - local_velocity[:2]))
            yaw_error = jp.square(command[2] - gyro[2])
            tracking_linear = jp.exp(-linear_error / 0.25)
            tracking_yaw = jp.exp(-yaw_error / 0.25)
            upright_cost = jp.sum(jp.square(upvector[:2]))
            vertical_cost = jp.square(local_velocity[2])
            torque_cost = jp.sum(jp.square(policy_torque)) * 2e-6
            action_rate_cost = jp.sum(jp.square(action - state.info["last_action"])) * 0.02
            reward = jp.clip(
                (
                    1.5 * tracking_linear
                    + 0.8 * tracking_yaw
                    - 5.0 * upright_cost
                    - 2.0 * vertical_cost
                    - torque_cost
                    - action_rate_cost
                )
                * self.dt,
                0.0,
            )
            policy_q = data.qpos[self._policy_qpos]
            held_q = data.qpos[self._held_qpos]
            joint_violation = jp.any(
                policy_q < jp.asarray(self._mj_model.jnt_range)[self._policy_joint_ids, 0]
            )
            joint_violation |= jp.any(
                policy_q > jp.asarray(self._mj_model.jnt_range)[self._policy_joint_ids, 1]
            )
            joint_violation |= jp.any(
                held_q < jp.asarray(self._mj_model.jnt_range)[self._held_joint_ids, 0]
            )
            joint_violation |= jp.any(
                held_q > jp.asarray(self._mj_model.jnt_range)[self._held_joint_ids, 1]
            )
            fallen = data.xpos[self._pelvis_body, 2] < self._minimum_height
            fallen |= upvector[2] < self._minimum_upright
            finite = jp.all(jp.isfinite(data.qpos)) & jp.all(jp.isfinite(data.qvel))
            done = (joint_violation | fallen | ~finite).astype(reward.dtype)
            step = state.info["step"] + 1
            resample = step >= 500
            next_command = jp.where(resample, self.sample_command(command_rng), command)
            next_step = jp.where(resample | done.astype(bool), 0, step)
            info = _preserving_update(
                state.info,
                {
                    "rng": rng,
                    "command": next_command,
                    "last_action": action,
                    "step": next_step,
                },
            )
            metrics = _preserving_update(
                state.metrics,
                {
                    "reward/tracking_linear": tracking_linear,
                    "reward/tracking_yaw": tracking_yaw,
                    "cost/upright": upright_cost,
                    "cost/vertical_velocity": vertical_cost,
                    "cost/torque": torque_cost,
                    "cost/action_rate": action_rate_cost,
                },
            )
            observation = {"state": self._observation(data, action, next_command)}
            return state.replace(
                data=data,
                obs=observation,
                reward=reward,
                done=done,
                metrics=metrics,
                info=info,
            )

        @property
        def xml_path(self) -> str:
            return self._xml_path

        @property
        def action_size(self) -> int:
            return len(control["policyJoints"])

        @property
        def mj_model(self):
            return self._mj_model

        @property
        def mjx_model(self):
            return self._mjx_model

        @property
        def pelvis_body_id(self) -> int:
            return self._pelvis_body

        def upvector(self, data):
            return self._sensor(data, "upvector")

        def local_velocity(self, data):
            return self._sensor(data, "local_linvel")

        def angular_velocity(self, data):
            return self._sensor(data, "gyro")

    return WorldSpecLoadedH1Velocity()
