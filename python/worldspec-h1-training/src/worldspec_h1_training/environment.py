"""Target-bundle H1 locomotion environment.

Heavy dependencies are imported only when the locked Linux/NVIDIA runtime calls
``make_environment``. This keeps static contract tests independent of CUDA.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import TrainingError
from .transition import transition_phase_masks


def _preserving_update(
    current: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Update owned keys without deleting Brax wrapper state."""

    result = dict(current)
    result.update(updates)
    return result


def make_environment(
    profile: dict[str, Any],
    training_model: Path,
    stand_teacher_policy: Any | None = None,
):
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
    training_environment = profile.get("trainingEnvironment")
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
            self._mj_model.opt.ccd_iterations = int(
                profile["runtime"].get(
                    "ccdIterations",
                    self._mj_model.opt.ccd_iterations,
                )
            )
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
            self._calibration_enabled = isinstance(training_environment, dict)
            self._transition_curriculum = None
            self._stand_teacher_policy = stand_teacher_policy
            self._stand_replay_probability = 0.0
            self._stand_distillation_sigma = 1.0
            if self._calibration_enabled:
                termination = training_environment["termination"]
                self._minimum_height = float(termination["minimumBaseHeight"])
                self._minimum_upright = float(termination["minimumUprightCosine"])
                self._joint_limit_tolerance = float(termination["jointLimitToleranceRadians"])
                self._reward_config = training_environment["reward"]
                self._reward_targets = training_environment["targets"]
                self._reward_sigmas = training_environment["sigmas"]
                self._command_resample_steps = int(training_environment["commandResampleSteps"])
                transition = training_environment.get("transitionCurriculum")
                if isinstance(transition, dict):
                    self._transition_curriculum = transition
                    motion = transition["motionCommandDistribution"]
                    self._motion_command_low = jp.asarray(
                        [
                            motion["linearVelocityX"][0],
                            motion["linearVelocityY"][0],
                            motion["angularVelocityYaw"][0],
                        ]
                    )
                    self._motion_command_high = jp.asarray(
                        [
                            motion["linearVelocityX"][1],
                            motion["linearVelocityY"][1],
                            motion["angularVelocityYaw"][1],
                        ]
                    )
                    self._transition_probability = float(transition["transitionCycleProbability"])
                    self._stand_replay_probability = float(
                        transition.get("standReplayProbability", 0.0)
                    )
                    self._transition_move_steps = int(transition["moveSteps"])
                    self._transition_settle_steps = int(transition["settleSteps"])
                    self._transition_cycle_steps = (
                        self._transition_move_steps + self._transition_settle_steps
                    )
                    self._stand_distillation_sigma = float(
                        self._reward_sigmas.get("standDistillation", 1.0)
                    )
                    if self._stand_replay_probability > 0.0 and (
                        self._stand_teacher_policy is None
                    ):
                        raise TrainingError(
                            "TRAINING_STAND_TEACHER_MISSING",
                            "Stand replay with distillation requires a bound teacher policy.",
                        )
            else:
                self._minimum_height = float(validation["minimumBaseHeight"])
                self._minimum_upright = float(validation["minimumUprightCosine"])
                self._joint_limit_tolerance = 0.0
                self._reward_config = {}
                self._reward_targets = {}
                self._reward_sigmas = {}
                self._command_resample_steps = 500

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

        def sample_motion_command(self, rng):
            return jax.random.uniform(
                rng,
                shape=(3,),
                minval=self._motion_command_low,
                maxval=self._motion_command_high,
            )

        def sample_cycle(self, rng):
            if self._transition_curriculum is None:
                return self.sample_command(rng), jp.asarray(False), jp.asarray(False)
            if self._stand_replay_probability > 0.0:
                mode_rng, motion_rng, baseline_rng = jax.random.split(rng, 3)
                selector = jax.random.uniform(mode_rng)
                transition_active = selector < self._transition_probability
                stand_replay_active = (selector >= self._transition_probability) & (
                    selector < self._transition_probability + self._stand_replay_probability
                )
                motion_command = self.sample_motion_command(motion_rng)
                baseline_command = self.sample_command(baseline_rng)
                command = jp.where(transition_active, motion_command, baseline_command)
                command = jp.where(stand_replay_active, jp.zeros(3), command)
                return command, transition_active, stand_replay_active
            mode_rng, motion_rng, baseline_rng = jax.random.split(rng, 3)
            transition_active = jax.random.bernoulli(
                mode_rng,
                self._transition_probability,
            )
            motion_command = self.sample_motion_command(motion_rng)
            baseline_command = self.sample_command(baseline_rng)
            return (
                jp.where(transition_active, motion_command, baseline_command),
                transition_active,
                jp.asarray(False),
            )

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
            command, transition_active, stand_replay_active = self.sample_cycle(command_rng)
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
                "command": command,
                "transition_active": transition_active,
                "stand_replay_active": stand_replay_active,
                "last_action": jp.zeros(self.action_size),
                "step": jp.zeros((), dtype=jp.int32),
                "termination": {
                    "joint_limit": jp.zeros((), dtype=bool),
                    "fall_height": jp.zeros((), dtype=bool),
                    "fall_upright": jp.zeros((), dtype=bool),
                    "nonfinite": jp.zeros((), dtype=bool),
                },
            }
            metrics = {
                "reward/tracking_linear": jp.zeros(()),
                "reward/tracking_yaw": jp.zeros(()),
                "reward/survival": jp.zeros(()),
                "reward/upright": jp.zeros(()),
                "reward/base_height": jp.zeros(()),
                "reward/pose": jp.zeros(()),
                "reward/settle_linear": jp.zeros(()),
                "reward/settle_yaw": jp.zeros(()),
                "reward/stand_distillation": jp.zeros(()),
                "cost/upright": jp.zeros(()),
                "cost/vertical_velocity": jp.zeros(()),
                "cost/angular_velocity_xy": jp.zeros(()),
                "cost/pose": jp.zeros(()),
                "cost/torque": jp.zeros(()),
                "cost/action_rate": jp.zeros(()),
                "cost/teacher_action_mse": jp.zeros(()),
                "termination/joint_limit": jp.zeros(()),
                "termination/fall_height": jp.zeros(()),
                "termination/fall_upright": jp.zeros(()),
                "termination/nonfinite": jp.zeros(()),
                "state/base_height": jp.zeros(()),
                "state/upright_cosine": jp.zeros(()),
                "state/transition_settle": jp.zeros(()),
                "state/stand_replay": jp.zeros(()),
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
            tracking_sigma = (
                float(self._reward_sigmas["tracking"]) if self._calibration_enabled else 0.25
            )
            tracking_linear = jp.exp(-linear_error / tracking_sigma)
            tracking_yaw = jp.exp(-yaw_error / tracking_sigma)
            upright_cost = jp.sum(jp.square(upvector[:2]))
            vertical_cost = jp.square(local_velocity[2])
            policy_q = data.qpos[self._policy_qpos]
            held_q = data.qpos[self._held_qpos]
            pose_cost = jp.sum(jp.square(policy_q - self._default_angles))
            angular_velocity_xy_cost = jp.sum(jp.square(gyro[:2]))
            raw_torque_cost = jp.sum(jp.square(policy_torque))
            raw_action_rate_cost = jp.sum(jp.square(action - state.info["last_action"]))
            transition_active = state.info.get("transition_active", jp.asarray(False))
            stand_replay_active = state.info.get(
                "stand_replay_active",
                jp.asarray(False),
            )
            if self._transition_curriculum is not None:
                _, settle_phase, _ = transition_phase_masks(
                    state.info["step"],
                    self._transition_move_steps,
                    self._transition_cycle_steps,
                )
                transition_settle = transition_active & settle_phase
            else:
                transition_settle = jp.asarray(False)
            settle_linear_reward = jp.zeros(())
            settle_yaw_reward = jp.zeros(())
            stand_distillation_reward = jp.zeros(())
            teacher_action_mse = jp.zeros(())
            if self._calibration_enabled:
                base_height = data.xpos[self._pelvis_body, 2]
                survival_reward = jp.ones(())
                upright_reward = jp.exp(-upright_cost / float(self._reward_sigmas["upright"]))
                height_error = jp.square(base_height - float(self._reward_targets["baseHeight"]))
                base_height_reward = jp.exp(
                    -height_error / float(self._reward_sigmas["baseHeight"])
                )
                pose_reward = jp.exp(-pose_cost / float(self._reward_sigmas["pose"]))
                if self._transition_curriculum is not None:
                    settle_sigma = float(self._reward_sigmas["settleTracking"])
                    settle_linear_reward = (
                        jp.exp(-jp.sum(jp.square(local_velocity[:2])) / settle_sigma)
                        * transition_settle
                    )
                    settle_yaw_reward = (
                        jp.exp(-jp.square(gyro[2]) / settle_sigma) * transition_settle
                    )
                    action_rate_scale = jp.where(
                        transition_settle,
                        float(self._reward_config["settleActionRateScale"]),
                        1.0,
                    )
                    if self._stand_teacher_policy is not None:
                        teacher_observation = dict(state.obs)
                        teacher_observation["state"] = teacher_observation["state"].at[-3:].set(0.0)
                        teacher_action, _ = self._stand_teacher_policy(
                            teacher_observation,
                            state.info["rng"],
                        )
                        teacher_action_mse = jp.mean(jp.square(action - teacher_action))
                        stand_distillation_reward = (
                            jp.exp(-teacher_action_mse / self._stand_distillation_sigma)
                            * stand_replay_active
                        )
                else:
                    action_rate_scale = 1.0
                reward = jp.clip(
                    (
                        float(self._reward_config["survival"]) * survival_reward
                        + float(self._reward_config["trackingLinear"]) * tracking_linear
                        + float(self._reward_config["trackingYaw"]) * tracking_yaw
                        + float(self._reward_config["upright"]) * upright_reward
                        + float(self._reward_config["baseHeight"]) * base_height_reward
                        + float(self._reward_config["pose"]) * pose_reward
                        + float(self._reward_config.get("settleLinear", 0.0)) * settle_linear_reward
                        + float(self._reward_config.get("settleYaw", 0.0)) * settle_yaw_reward
                        + float(self._reward_config.get("standDistillation", 0.0))
                        * stand_distillation_reward
                        - float(self._reward_config["verticalVelocityCost"]) * vertical_cost
                        - float(self._reward_config["angularVelocityXYCost"])
                        * angular_velocity_xy_cost
                        - float(self._reward_config["torqueCost"]) * raw_torque_cost
                        - float(self._reward_config["actionRateCost"])
                        * action_rate_scale
                        * raw_action_rate_cost
                    )
                    * self.dt,
                    0.0,
                )
                torque_cost = raw_torque_cost * float(self._reward_config["torqueCost"])
                action_rate_cost = (
                    raw_action_rate_cost
                    * float(self._reward_config["actionRateCost"])
                    * action_rate_scale
                )
            else:
                survival_reward = jp.zeros(())
                upright_reward = jp.zeros(())
                base_height_reward = jp.zeros(())
                pose_reward = jp.zeros(())
                torque_cost = raw_torque_cost * 2e-6
                action_rate_cost = raw_action_rate_cost * 0.02
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
            joint_ranges = jp.asarray(self._mj_model.jnt_range)
            tolerance = self._joint_limit_tolerance
            joint_violation = jp.any(policy_q < joint_ranges[self._policy_joint_ids, 0] - tolerance)
            joint_violation |= jp.any(
                policy_q > joint_ranges[self._policy_joint_ids, 1] + tolerance
            )
            joint_violation |= jp.any(held_q < joint_ranges[self._held_joint_ids, 0] - tolerance)
            joint_violation |= jp.any(held_q > joint_ranges[self._held_joint_ids, 1] + tolerance)
            base_height = data.xpos[self._pelvis_body, 2]
            fall_height = base_height < self._minimum_height
            fall_upright = upvector[2] < self._minimum_upright
            finite = jp.all(jp.isfinite(data.qpos)) & jp.all(jp.isfinite(data.qvel))
            nonfinite = ~finite
            done = (joint_violation | fall_height | fall_upright | nonfinite).astype(reward.dtype)
            step = state.info["step"] + 1
            if self._transition_curriculum is not None:
                (
                    sampled_command,
                    sampled_transition_active,
                    sampled_stand_replay_active,
                ) = self.sample_cycle(command_rng)
                _, begin_settle_phase, resample = transition_phase_masks(
                    step,
                    self._transition_move_steps,
                    self._transition_cycle_steps,
                )
                begin_settle = (
                    transition_active & begin_settle_phase & (step == self._transition_move_steps)
                )
                next_command = jp.where(begin_settle, jp.zeros(3), command)
                next_command = jp.where(resample, sampled_command, next_command)
                next_transition_active = jp.where(
                    resample,
                    sampled_transition_active,
                    transition_active,
                )
                next_stand_replay_active = jp.where(
                    resample,
                    sampled_stand_replay_active,
                    stand_replay_active,
                )
            else:
                resample = step >= self._command_resample_steps
                next_command = jp.where(resample, self.sample_command(command_rng), command)
                next_transition_active = transition_active
                next_stand_replay_active = stand_replay_active
            next_step = jp.where(resample | done.astype(bool), 0, step)
            info = _preserving_update(
                state.info,
                {
                    "rng": rng,
                    "command": next_command,
                    "transition_active": next_transition_active,
                    "stand_replay_active": next_stand_replay_active,
                    "last_action": action,
                    "step": next_step,
                    "termination": {
                        "joint_limit": joint_violation,
                        "fall_height": fall_height,
                        "fall_upright": fall_upright,
                        "nonfinite": nonfinite,
                    },
                },
            )
            metrics = _preserving_update(
                state.metrics,
                {
                    "reward/tracking_linear": tracking_linear,
                    "reward/tracking_yaw": tracking_yaw,
                    "reward/survival": survival_reward,
                    "reward/upright": upright_reward,
                    "reward/base_height": base_height_reward,
                    "reward/pose": pose_reward,
                    "reward/settle_linear": settle_linear_reward,
                    "reward/settle_yaw": settle_yaw_reward,
                    "reward/stand_distillation": stand_distillation_reward,
                    "cost/upright": upright_cost,
                    "cost/vertical_velocity": vertical_cost,
                    "cost/angular_velocity_xy": angular_velocity_xy_cost,
                    "cost/pose": pose_cost,
                    "cost/torque": torque_cost,
                    "cost/action_rate": action_rate_cost,
                    "cost/teacher_action_mse": teacher_action_mse,
                    "termination/joint_limit": joint_violation.astype(reward.dtype),
                    "termination/fall_height": fall_height.astype(reward.dtype),
                    "termination/fall_upright": fall_upright.astype(reward.dtype),
                    "termination/nonfinite": nonfinite.astype(reward.dtype),
                    "state/base_height": base_height,
                    "state/upright_cosine": upvector[2],
                    "state/transition_settle": transition_settle.astype(reward.dtype),
                    "state/stand_replay": stand_replay_active.astype(reward.dtype),
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

        @property
        def ccd_iterations(self) -> int:
            return int(self._mj_model.opt.ccd_iterations)

        def upvector(self, data):
            return self._sensor(data, "upvector")

        def local_velocity(self, data):
            return self._sensor(data, "local_linvel")

        def angular_velocity(self, data):
            return self._sensor(data, "gyro")

    return WorldSpecLoadedH1Velocity()
