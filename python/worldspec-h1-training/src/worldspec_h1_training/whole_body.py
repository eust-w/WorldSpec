"""A5-C hierarchical whole-body task-space control spike.

The controller solves a small box-constrained convex QP on the host.  Its
decision vector contains planar base velocity, torso velocity, and the four
right-arm joint velocities.  The frozen locomotion/stand policies remain the
only leg controller.  MuJoCo bias forces are passed to MJX as explicit,
traceable feed-forward torque; no hidden constraint or kinematic teleport is
introduced.
"""

from __future__ import annotations

import copy
import functools
import json
import math
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contract import canonical_bytes, digest_bytes, digest_json, validate_profile
from .errors import TrainingError
from .kitchen_task import (
    ERGONOMIC_TASK_SCENE,
    TASK_CAPACITY,
    TASK_SCENE,
    _target_for_phase,
    _task_metrics,
    prepare_kitchen_task_model,
)
from .midterm import _load_deterministic_teacher_policy
from .preflight import runtime_preflight, static_preflight
from .supervisor import SUPERVISOR, SupervisorState, make_supervisor_evaluation_profile
from .trainer import _flat_observation_size
from .warm_start import materialize_warm_start, validate_network_compatibility

WHOLE_BODY_CONTROLLER = {
    "mode": "hierarchical_box_qp_with_inverse_dynamics_feedforward",
    "decisionVariables": [
        "base_velocity_x",
        "base_velocity_y",
        "base_yaw_rate",
        "torso_velocity",
        "right_shoulder_pitch_velocity",
        "right_shoulder_roll_velocity",
        "right_shoulder_yaw_velocity",
        "right_elbow_velocity",
    ],
    "controlledJoints": [
        "torso",
        "right_shoulder_pitch",
        "right_shoulder_roll",
        "right_shoulder_yaw",
        "right_elbow",
    ],
    "qpIterations": 48,
    "cartesianGain": 4.0,
    "maximumCartesianSpeed": 0.35,
    "velocityLowerBounds": [-0.08, -0.06, -0.15, -0.5, -0.8, -0.8, -0.8, -0.8],
    "velocityUpperBounds": [0.08, 0.06, 0.15, 0.5, 0.8, 0.8, 0.8, 0.8],
    "regularization": [2.0, 2.0, 3.0, 0.35, 0.15, 0.15, 0.15, 0.15],
    "targetHorizonSeconds": 0.4,
    "maximumJointTargetStep": 0.30,
    "jointLimitMarginRadians": 0.05,
    "feedforwardScale": 1.0,
    "feedforwardControlReserve": 0.20,
}

WHOLE_BODY_GATES = {
    "settleSteps": 25,
    "trackingSteps": 180,
    "positionToleranceMeters": 0.035,
    "holdSteps": 20,
    "maximumTcpSpeed": 0.15,
    "maximumBaseTranslation": 0.20,
    "maximumBaseLateralDrift": 0.12,
    "minimumBaseHeight": 0.80,
    "minimumUprightCosine": 0.80,
    "maximumProjectedGradient": 1e-5,
    "maximumNonFiniteSamples": 0,
}

A5R_FAILED_REPORT_DIGEST = "sha256:c55d67244d28d3abdfef787b7858fceabea61a534fe1beb674fdc3bad7a67da0"

TASK_POLICY_HANDOFF = {
    "mode": "hysteretic_motion_capture_blend_stand",
    "initialPolicy": "stand",
    "motionEntryThreshold": 0.05,
    "motionExitThreshold": 0.02,
    "captureGate": copy.deepcopy(SUPERVISOR["captureGate"]),
    "blendSteps": SUPERVISOR["handoff"]["blendSteps"],
    "policyObservationCommandDuringHandoff": [0.0, 0.0, 0.0],
    "motionReentry": "allowed_above_entry_threshold",
}

A5CI_DIAGNOSTIC_EVIDENCE = {
    "attemptId": "a5ci-replay-05",
    "baseControlProfileDigest": (
        "sha256:84175bdeb52d0b9a9122888e36f8bbd9fd42ccf79adb5c5534f16a5d74d787fd"
    ),
    "replayProfileDigest": (
        "sha256:aa4ce7769044c26902745a9f054c6b18310c850f178c2f43295386e9fba1832c"
    ),
    "passedSummaryDigest": (
        "sha256:bb005cb91d983f8174205b8a9cfb102152e58e512822debef46c0c6c7b7501a5"
    ),
    "replayReportDigest": (
        "sha256:b3fff6a7a8845eef6eddbb2f7f67da51bc5f34771c081dcb22d5ddd717ddeff8"
    ),
    "traceDigest": ("sha256:c7da0c7becb3fc84e0b06199fa622364cac9ccd29453b5a79aa9b0a70eec20a7"),
    "terminalReason": "joint_limit",
    "terminalJoint": "right_hip_yaw",
    "formalDiagnosticReplayGate": "passed",
    "formalControlGate": "failed",
}

A5CF_FAILURE_EVIDENCE = {
    "job": "worldspec-h1-midterm-45v9r",
    "controlProfileDigest": (
        "sha256:2fd53b32393025124967288f39419980f2c1b0b5a46140f91284e86c30202a54"
    ),
    "reportDigest": ("sha256:5de85648bc2fcd12a47b402628e7072f295ea4a95426c65ecaa71edaed51f012"),
    "controllerDigest": ("sha256:c723dfc437f4f4b2ba1f1952e04f93ae82ab8fc0039249cce604484dff8524e4"),
    "traceDigest": ("sha256:6c98416d60bf36e78cf29d4043d16ecebb04bfbe862012b49ef4ab171b7a91b1"),
    "traceRecordCount": 307,
    "terminalReason": "fall_height",
    "taskPolicyFinalPhase": "motion",
    "taskPolicyHandoffFailed": False,
    "formalControlGate": "failed",
}

DYNAMIC_ARM_TRACKING = {
    "mode": "fixed_base_four_joint_qp_with_bias_feedforward",
    "controlledJoints": [
        "right_shoulder_pitch",
        "right_shoulder_roll",
        "right_shoulder_yaw",
        "right_elbow",
    ],
    "baseCommand": "locked_zero",
    "torsoTargetRadians": 0.0,
    "uncontrolledHeldTargets": "profile_defaults",
    "legPolicy": "stand",
    "feedforward": "mujoco_qfrc_bias",
}

A5CG_FAILURE_EVIDENCE = {
    "job": "worldspec-h1-midterm-9zmdg",
    "controlProfileDigest": (
        "sha256:994c9a7e9b3e6312e3e1e8b13c5cc97f9a2b69e3798682a36d57a79f4153cb0d"
    ),
    "reportDigest": "sha256:56a804482e903e64d11092b0d5c1f60fa50466b6581d3de56f08d1aca1ae957f",
    "controllerDigest": ("sha256:d7a3b176e08a9a14dc1b0331bfb7bd3a09bab03b46080451249d104f7d7dc7b2"),
    "traceDigest": "sha256:8cc84091b367ece380b8f500a9481d9d6567a937ae4199241ef90f19cc507b08",
    "traceRecordCount": 301,
    "terminalReason": "fall_height",
    "taskPolicyFinalPhase": "stand",
    "taskPolicyHandoffFailed": False,
    "dynamicArmTrackingEnabled": True,
    "formalControlGate": "failed",
}

TASK_GEOMETRY_CALIBRATION = {
    "mode": "measured_stable_workspace_alignment",
    "sourceJob": "worldspec-h1-midterm-9zmdg",
    "sourceTraceDigest": A5CG_FAILURE_EVIDENCE["traceDigest"],
    "sourceStableTcpPosition": [1.835095491188453, -0.18911960748591475, 1.1411498880156772],
    "sceneTranslation": [-0.03, 0.0, 0.065],
    "calibratedHandleTarget": [1.84, -0.21, 1.14],
    "qualityGatesChanged": False,
}

DIAGNOSTIC_TERMINATION_CHANNELS = (
    "joint_limit",
    "fall_height",
    "fall_upright",
    "nonfinite",
)
DIAGNOSTIC_JOINT_GROUPS = ("policy", "held")
DIAGNOSTIC_ACTUATOR_GROUPS = ("policy", "held", "gripper")


@dataclass
class TaskPolicyHandoffState:
    """Task-phase leg-policy supervisor with a guarded stop transition.

    The task-space QP may request small planar corrections after the passing A4
    locomotion supervisor has already reached stand.  A5-C used a single
    command-norm threshold and switched motion directly to stand.  This state
    machine adds hysteresis and reuses the independently validated capture and
    five-step blend path for every motion-to-stand transition.
    """

    phase: str = "stand"
    capture_steps: int = 0
    stable_steps: int = 0
    blend_steps: int = 0
    handoff_failed: bool = False

    def prepare(self, command_norm: float) -> str:
        """Update phase from the current requested command before inference."""

        if not math.isfinite(command_norm) or command_norm < 0.0:
            raise TrainingError(
                "TASK_POLICY_COMMAND_INVALID",
                "Task policy handoff requires a finite non-negative command norm.",
            )
        entry = TASK_POLICY_HANDOFF["motionEntryThreshold"]
        exit_threshold = TASK_POLICY_HANDOFF["motionExitThreshold"]
        if self.phase == "stand":
            if command_norm >= entry:
                self._enter_motion()
        elif self.phase == "motion":
            if command_norm <= exit_threshold:
                self._enter_capture()
        elif self.phase in {"capture", "blend"}:
            if command_norm >= entry:
                self._enter_motion()
        else:
            raise TrainingError(
                "TASK_POLICY_PHASE_INVALID",
                f"Unsupported task policy handoff phase: {self.phase}",
            )
        return self.phase

    def select(self, motion_action, capture_action, stand_action):
        """Return action, active policy label, and stand-blend alpha."""

        if self.phase == "motion":
            return motion_action, "motion", 0.0
        if self.phase == "capture":
            return capture_action, "capture", 0.0
        if self.phase == "blend":
            total = TASK_POLICY_HANDOFF["blendSteps"]
            alpha = (self.blend_steps + 1) / total
            return (
                (1.0 - alpha) * capture_action + alpha * stand_action,
                "blend",
                alpha,
            )
        if self.phase == "stand":
            return stand_action, "stand", 1.0
        raise TrainingError(
            "TASK_POLICY_PHASE_INVALID",
            f"Unsupported task policy handoff phase: {self.phase}",
        )

    def observe(self, active_phase: str, linear_speed: float, angular_speed: float) -> None:
        """Advance capture and blend only after observing the executed step."""

        capture = TASK_POLICY_HANDOFF["captureGate"]
        if active_phase == "capture":
            self.capture_steps += 1
            stable = (
                linear_speed <= capture["maximumLinearSpeed"]
                and angular_speed <= capture["maximumAngularSpeed"]
            )
            self.stable_steps = self.stable_steps + 1 if stable else 0
            if (
                self.capture_steps >= capture["minimumSteps"]
                and self.stable_steps >= capture["requiredConsecutiveStableSteps"]
            ):
                self.phase = "blend"
                self.blend_steps = 0
            elif self.capture_steps >= capture["maximumSteps"]:
                self.handoff_failed = True
        elif active_phase == "blend":
            self.blend_steps += 1
            if self.blend_steps >= TASK_POLICY_HANDOFF["blendSteps"]:
                self.phase = "stand"
        elif active_phase not in {"motion", "stand"}:
            raise TrainingError(
                "TASK_POLICY_PHASE_INVALID",
                f"Unsupported observed task policy phase: {active_phase}",
            )

    def _enter_motion(self) -> None:
        self.phase = "motion"
        self.capture_steps = 0
        self.stable_steps = 0
        self.blend_steps = 0
        self.handoff_failed = False

    def _enter_capture(self) -> None:
        self.phase = "capture"
        self.capture_steps = 0
        self.stable_steps = 0
        self.blend_steps = 0
        self.handoff_failed = False


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _trace_number(value: object) -> float | None:
    """Return a JSON-safe diagnostic number while preserving invalid evidence as null."""

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def whole_body_profile_semantic_projection(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Project an A5-C control Profile onto replay-relevant semantics.

    A diagnostic replay is allowed to use a newly built OCI image.  No other
    field is excluded: controller, policies, scene, seed, gates, package lock,
    capacity, and claim boundaries remain part of the projection.
    """

    projection = copy.deepcopy(dict(profile))
    runtime = projection.get("runtime")
    if not isinstance(runtime, dict):
        raise TrainingError(
            "DIAGNOSTIC_PROFILE_RUNTIME_INVALID",
            "Whole-body semantic projection requires a runtime object.",
        )
    runtime.pop("containerImage", None)
    runtime.pop("containerDigest", None)
    return projection


def whole_body_controller_semantic_projection(
    controller_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Remove only the embedded full Profile digest from a controller artifact."""

    projection = copy.deepcopy(dict(controller_artifact))
    if "profileDigest" not in projection:
        raise TrainingError(
            "DIAGNOSTIC_CONTROLLER_PROFILE_DIGEST_MISSING",
            "Controller projection requires the embedded profileDigest.",
        )
    projection.pop("profileDigest")
    return projection


def _path_value(record: Mapping[str, Any], path: str) -> object:
    value: object = record
    for segment in path.split("."):
        if not isinstance(value, Mapping) or segment not in value:
            return None
        value = value[segment]
    return value


def _numeric_values(value: object) -> list[float] | None:
    if _finite_number(value):
        return [float(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = list(value)
        if all(_finite_number(item) for item in values):
            return [float(item) for item in values]
    return None


def _nonfinite_numeric_paths(value: object, prefix: str) -> list[str]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [] if math.isfinite(float(value)) else [prefix]
    if isinstance(value, Mapping):
        paths: list[str] = []
        for key, item in value.items():
            paths.extend(_nonfinite_numeric_paths(item, f"{prefix}.{key}"))
        return paths
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_nonfinite_numeric_paths(item, f"{prefix}[{index}]"))
        return paths
    return []


def compare_whole_body_traces(
    reference_records: Iterable[Mapping[str, Any]],
    replay_records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Report dynamic A5-C/A5-CI trace differences without deciding equivalence."""

    reference = [dict(record) for record in reference_records]
    replay = [dict(record) for record in replay_records]

    def index_by_step(records: list[dict[str, Any]]) -> tuple[dict[int, dict[str, Any]], int]:
        indexed: dict[int, dict[str, Any]] = {}
        duplicates = 0
        for record in records:
            step = record.get("step")
            if isinstance(step, int) and not isinstance(step, bool):
                duplicates += int(step in indexed)
                indexed[step] = record
        return indexed, duplicates

    reference_by_step, reference_duplicates = index_by_step(reference)
    replay_by_step, replay_duplicates = index_by_step(replay)
    common_steps = sorted(set(reference_by_step) & set(replay_by_step))
    categorical_paths = ("phase", "activePolicy", "finite", "done", "termination")
    numeric_paths = (
        "timeSeconds",
        "command",
        "basePosition",
        "minimumBaseHeight",
        "minimumUprightCosine",
        "site.targetErrorMeters",
        "site.tcpSpeed",
        "control.targetErrorMeters",
        "control.qpProjectedGradient",
    )
    categorical: dict[str, dict[str, Any]] = {}
    first_divergence: int | None = None
    for path in categorical_paths:
        compared = 0
        differences: list[int] = []
        reference_available = 0
        replay_available = 0
        for step in common_steps:
            reference_value = _path_value(reference_by_step[step], path)
            replay_value = _path_value(replay_by_step[step], path)
            reference_available += int(reference_value is not None)
            replay_available += int(replay_value is not None)
            if reference_value is None or replay_value is None:
                continue
            compared += 1
            if reference_value != replay_value:
                differences.append(step)
        if differences:
            candidate = differences[0]
            first_divergence = (
                candidate if first_divergence is None else min(first_divergence, candidate)
            )
        categorical[path] = {
            "referenceAvailable": reference_available,
            "replayAvailable": replay_available,
            "samplesCompared": compared,
            "differenceCount": len(differences),
            "firstDifferenceStep": differences[0] if differences else None,
        }

    numeric: dict[str, dict[str, Any]] = {}
    for path in numeric_paths:
        compared = 0
        sample_differences: list[float] = []
        difference_steps: list[int] = []
        reference_available = 0
        replay_available = 0
        for step in common_steps:
            reference_value = _numeric_values(_path_value(reference_by_step[step], path))
            replay_value = _numeric_values(_path_value(replay_by_step[step], path))
            reference_available += int(reference_value is not None)
            replay_available += int(replay_value is not None)
            if (
                reference_value is None
                or replay_value is None
                or len(reference_value) != len(replay_value)
            ):
                continue
            compared += 1
            difference = max(
                (
                    abs(left - right)
                    for left, right in zip(reference_value, replay_value, strict=True)
                ),
                default=0.0,
            )
            sample_differences.append(difference)
            if difference != 0.0:
                difference_steps.append(step)
        if difference_steps:
            candidate = difference_steps[0]
            first_divergence = (
                candidate if first_divergence is None else min(first_divergence, candidate)
            )
        numeric[path] = {
            "referenceAvailable": reference_available,
            "replayAvailable": replay_available,
            "samplesCompared": compared,
            "differentSampleCount": len(difference_steps),
            "firstDifferenceStep": difference_steps[0] if difference_steps else None,
            "maximumAbsoluteDifference": max(sample_differences, default=None),
            "meanAbsoluteDifference": (
                sum(sample_differences) / len(sample_differences) if sample_differences else None
            ),
        }

    return {
        "referenceRecordCount": len(reference),
        "replayRecordCount": len(replay),
        "commonStepCount": len(common_steps),
        "referenceOnlySteps": sorted(set(reference_by_step) - set(replay_by_step)),
        "replayOnlySteps": sorted(set(replay_by_step) - set(reference_by_step)),
        "duplicateSteps": {
            "reference": reference_duplicates,
            "replay": replay_duplicates,
        },
        "firstDynamicDivergenceStep": first_divergence,
        "categoricalDifferences": categorical,
        "numericDifferences": numeric,
        "interpretation": "report_only_not_static_equivalence",
    }


def _diagnostic_trace_errors(
    record: Mapping[str, Any],
    expected_control: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(record.get("activePolicy"), str) or not record["activePolicy"]:
        errors.append("active_policy_missing")
    if (
        not isinstance(record.get("command"), list)
        or len(record["command"]) != 3
        or not all(_finite_number(value) for value in record["command"])
    ):
        errors.append("command_not_finite_vector3")
    if (
        not isinstance(record.get("basePosition"), list)
        or len(record["basePosition"]) != 3
        or not all(_finite_number(value) for value in record["basePosition"])
    ):
        errors.append("base_position_not_finite_vector3")
    for field in ("timeSeconds", "minimumBaseHeight", "minimumUprightCosine"):
        if not _finite_number(record.get(field)):
            errors.append(f"{field}_not_finite")
    for field in ("control", "site"):
        errors.extend(
            f"{field}_nonfinite:{path}"
            for path in _nonfinite_numeric_paths(record.get(field), field)
        )
    done = record.get("done")
    if not isinstance(done, bool):
        errors.append("done_not_boolean")

    termination = record.get("termination")
    if not isinstance(termination, Mapping):
        errors.append("termination_not_object")
        termination_values: dict[str, bool] = {}
    else:
        actual_keys = set(termination)
        expected_keys = set(DIAGNOSTIC_TERMINATION_CHANNELS)
        if actual_keys != expected_keys:
            errors.append("termination_channels_mismatch")
        termination_values = {}
        for name in DIAGNOSTIC_TERMINATION_CHANNELS:
            value = termination.get(name)
            if not isinstance(value, bool):
                errors.append(f"termination_{name}_not_boolean")
            else:
                termination_values[name] = value
    if done is True and not any(termination_values.values()):
        errors.append("done_without_termination_reason")

    joint_state = record.get("jointState")
    violated_joints: list[str] = []
    if not isinstance(joint_state, Mapping) or set(joint_state) != set(DIAGNOSTIC_JOINT_GROUPS):
        errors.append("joint_state_groups_mismatch")
        joint_state = {}
    joint_fields = {
        "name",
        "position",
        "velocity",
        "lowerLimit",
        "upperLimit",
        "tolerance",
        "violated",
    }
    for group in DIAGNOSTIC_JOINT_GROUPS:
        expected_names = expected_control.get(f"{group}Joints")
        actual_records = joint_state.get(group) if isinstance(joint_state, Mapping) else None
        if not isinstance(expected_names, list) or not all(
            isinstance(name, str) and name for name in expected_names
        ):
            errors.append(f"expected_{group}_joint_names_invalid")
            continue
        if not isinstance(actual_records, list):
            errors.append(f"{group}_joint_records_not_array")
            continue
        actual_names = [
            item.get("name") if isinstance(item, Mapping) else None for item in actual_records
        ]
        if actual_names != expected_names:
            errors.append(f"{group}_joint_names_mismatch")
        for index, item in enumerate(actual_records):
            label = f"{group}_joint_{index}"
            if not isinstance(item, Mapping):
                errors.append(f"{label}_not_object")
                continue
            if set(item) != joint_fields:
                errors.append(f"{label}_fields_mismatch")
            position = item.get("position")
            velocity = item.get("velocity")
            lower = item.get("lowerLimit")
            upper = item.get("upperLimit")
            tolerance = item.get("tolerance")
            for field, value in (
                ("position", position),
                ("velocity", velocity),
                ("lower_limit", lower),
                ("upper_limit", upper),
                ("tolerance", tolerance),
            ):
                if not _finite_number(value):
                    errors.append(f"{label}_{field}_not_finite")
            if _finite_number(lower) and _finite_number(upper) and float(lower) > float(upper):
                errors.append(f"{label}_range_invalid")
            if _finite_number(tolerance) and float(tolerance) < 0.0:
                errors.append(f"{label}_tolerance_negative")
            violated = item.get("violated")
            if not isinstance(violated, bool):
                errors.append(f"{label}_violated_not_boolean")
            elif all(_finite_number(value) for value in (position, lower, upper, tolerance)):
                expected_violated = float(position) < float(lower) - float(tolerance) or float(
                    position
                ) > float(upper) + float(tolerance)
                if violated != expected_violated:
                    errors.append(f"{label}_violated_inconsistent")
                if violated and isinstance(item.get("name"), str):
                    violated_joints.append(item["name"])
    if termination_values.get("joint_limit") is True and not violated_joints:
        errors.append("joint_limit_without_violated_joint")
    if violated_joints and termination_values.get("joint_limit") is not True:
        errors.append("violated_joint_without_joint_limit")

    actuation = record.get("actuation")
    if not isinstance(actuation, Mapping):
        errors.append("actuation_not_object")
        actuation = {}
    groups = actuation.get("groups") if isinstance(actuation, Mapping) else None
    if not isinstance(groups, Mapping) or set(groups) != set(DIAGNOSTIC_ACTUATOR_GROUPS):
        errors.append("actuator_groups_mismatch")
        groups = {}
    actuator_fields = {
        "name",
        "appliedControl",
        "lowerLimit",
        "upperLimit",
        "limited",
        "utilization",
        "saturated",
    }
    saturated_count = 0
    maximum_utilization = 0.0
    for group in DIAGNOSTIC_ACTUATOR_GROUPS:
        expected_names = expected_control.get(f"{group}Actuators")
        actual_records = groups.get(group) if isinstance(groups, Mapping) else None
        if not isinstance(expected_names, list) or not all(
            isinstance(name, str) and name for name in expected_names
        ):
            errors.append(f"expected_{group}_actuator_names_invalid")
            continue
        if not isinstance(actual_records, list):
            errors.append(f"{group}_actuator_records_not_array")
            continue
        actual_names = [
            item.get("name") if isinstance(item, Mapping) else None for item in actual_records
        ]
        if actual_names != expected_names:
            errors.append(f"{group}_actuator_names_mismatch")
        for index, item in enumerate(actual_records):
            label = f"{group}_actuator_{index}"
            if not isinstance(item, Mapping):
                errors.append(f"{label}_not_object")
                continue
            if set(item) != actuator_fields:
                errors.append(f"{label}_fields_mismatch")
            lower = item.get("lowerLimit")
            upper = item.get("upperLimit")
            applied = item.get("appliedControl")
            utilization = item.get("utilization")
            for field, value in (
                ("applied_control", applied),
                ("lower_limit", lower),
                ("upper_limit", upper),
                ("utilization", utilization),
            ):
                if not _finite_number(value):
                    errors.append(f"{label}_{field}_not_finite")
            if _finite_number(lower) and _finite_number(upper) and float(lower) > float(upper):
                errors.append(f"{label}_range_invalid")
            limited = item.get("limited")
            saturated = item.get("saturated")
            if not isinstance(limited, bool):
                errors.append(f"{label}_limited_not_boolean")
            if not isinstance(saturated, bool):
                errors.append(f"{label}_saturated_not_boolean")
            elif saturated:
                saturated_count += 1
                if limited is False:
                    errors.append(f"{label}_unlimited_saturated")
            if _finite_number(utilization):
                maximum_utilization = max(maximum_utilization, float(utilization))
                if float(utilization) < 0.0:
                    errors.append(f"{label}_utilization_negative")
            if all(_finite_number(value) for value in (applied, lower, upper)):
                control_limit = max(abs(float(lower)), abs(float(upper)))
                expected_utilization = (
                    abs(float(applied)) / control_limit if control_limit > 0.0 else 0.0
                )
                if _finite_number(utilization) and not math.isclose(
                    float(utilization),
                    expected_utilization,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    errors.append(f"{label}_utilization_inconsistent")
                saturation_tolerance = max(control_limit * 1e-7, 1e-9)
                expected_saturated = limited is True and (
                    float(applied) <= float(lower) + saturation_tolerance
                    or float(applied) >= float(upper) - saturation_tolerance
                )
                if isinstance(saturated, bool) and saturated != expected_saturated:
                    errors.append(f"{label}_saturated_inconsistent")

    recorded_saturation_count = actuation.get("saturationCount")
    if (
        not isinstance(recorded_saturation_count, int)
        or isinstance(recorded_saturation_count, bool)
        or recorded_saturation_count != saturated_count
    ):
        errors.append("saturation_count_inconsistent")
    recorded_maximum_utilization = actuation.get("maximumUtilization")
    if not _finite_number(recorded_maximum_utilization) or not math.isclose(
        float(recorded_maximum_utilization),
        maximum_utilization,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        errors.append("maximum_utilization_inconsistent")

    base_state = record.get("baseState")
    expected_base_fields = {
        "position",
        "linearVelocity",
        "angularVelocity",
        "height",
        "uprightCosine",
    }
    if not isinstance(base_state, Mapping) or set(base_state) != expected_base_fields:
        errors.append("base_state_fields_mismatch")
    else:
        for field in ("position", "linearVelocity", "angularVelocity"):
            value = base_state[field]
            if (
                not isinstance(value, list)
                or len(value) != 3
                or not all(_finite_number(item) for item in value)
            ):
                errors.append(f"base_state_{field}_not_finite_vector3")
        for field in ("height", "uprightCosine"):
            if not _finite_number(base_state[field]):
                errors.append(f"base_state_{field}_not_finite")
    if record.get("finite") is not True:
        errors.append("record_not_finite")
    return errors


def validate_diagnostic_trace_record(
    record: Mapping[str, Any],
    expected_control: Mapping[str, Any],
) -> None:
    """Fail closed when a replay Trace Record is incomplete or self-inconsistent."""

    errors = _diagnostic_trace_errors(record, expected_control)
    if errors:
        raise TrainingError(
            "DIAGNOSTIC_TRACE_INVALID",
            "A5-CI diagnostic Trace Record is incomplete or inconsistent.",
            {"step": record.get("step"), "reasons": errors},
        )


def assess_diagnostic_trace(
    records: Iterable[Mapping[str, Any]],
    expected_control: Mapping[str, Any],
) -> dict[str, Any]:
    """Aggregate a diagnostic trace while retaining all record-level failures."""

    trace = [dict(record) for record in records]
    reasons: list[str] = []
    terminal_reasons: set[str] = set()
    terminal_joints: set[str] = set()
    control_saturation_samples = 0
    maximum_control_utilization = 0.0
    if not trace:
        reasons.append("trace_empty")
    for index, record in enumerate(trace):
        for error in _diagnostic_trace_errors(record, expected_control):
            reasons.append(f"record[{index}]:{error}")
        termination = record.get("termination")
        if isinstance(termination, Mapping):
            terminal_reasons.update(
                name for name in DIAGNOSTIC_TERMINATION_CHANNELS if termination.get(name) is True
            )
        joint_state = record.get("jointState")
        if isinstance(joint_state, Mapping):
            for group in DIAGNOSTIC_JOINT_GROUPS:
                entries = joint_state.get(group)
                if not isinstance(entries, list):
                    continue
                terminal_joints.update(
                    item["name"]
                    for item in entries
                    if isinstance(item, Mapping)
                    and item.get("violated") is True
                    and isinstance(item.get("name"), str)
                )
        actuation = record.get("actuation")
        if isinstance(actuation, Mapping):
            saturation_count = actuation.get("saturationCount")
            control_saturation_samples += int(
                isinstance(saturation_count, int)
                and not isinstance(saturation_count, bool)
                and saturation_count > 0
            )
            utilization = actuation.get("maximumUtilization")
            if _finite_number(utilization):
                maximum_control_utilization = max(
                    maximum_control_utilization,
                    float(utilization),
                )
    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "status": "passed" if not unique_reasons else "failed",
        "reasons": unique_reasons,
        "recordCount": len(trace),
        "terminalReasons": sorted(terminal_reasons),
        "terminalJoints": sorted(terminal_joints),
        "controlSaturationSamples": control_saturation_samples,
        "maximumControlUtilization": maximum_control_utilization,
    }


def solve_box_qp(
    hessian,
    gradient,
    lower,
    upper,
    *,
    iterations: int,
):
    """Solve a strictly-convex box QP using deterministic coordinate descent."""

    import numpy as np

    h = np.asarray(hessian, dtype=float)
    g = np.asarray(gradient, dtype=float)
    lo = np.asarray(lower, dtype=float)
    hi = np.asarray(upper, dtype=float)
    if (
        h.ndim != 2
        or h.shape[0] != h.shape[1]
        or g.shape != (h.shape[0],)
        or lo.shape != g.shape
        or hi.shape != g.shape
        or not np.all(np.isfinite(h))
        or not np.all(np.isfinite(g))
        or not np.all(lo <= hi)
        or np.any(np.diag(h) <= 0)
    ):
        raise TrainingError("WHOLE_BODY_QP_INVALID", "Box QP inputs are invalid.")
    solution = np.zeros_like(g)
    solution = np.clip(solution, lo, hi)
    for _ in range(iterations):
        for index in range(solution.size):
            residual = g[index] + float(h[index] @ solution)
            solution[index] = np.clip(
                solution[index] - residual / h[index, index],
                lo[index],
                hi[index],
            )
    full_gradient = h @ solution + g
    projected = solution - np.clip(solution - full_gradient, lo, hi)
    objective = 0.5 * float(solution @ h @ solution) + float(g @ solution)
    return solution, objective, float(np.max(np.abs(projected)))


class WholeBodyTaskSpaceController:
    """Host-side task allocator and inverse-dynamics feed-forward generator."""

    def __init__(
        self,
        model,
        control_profile: dict[str, Any],
        dynamic_arm_tracking: Mapping[str, Any] | None = None,
    ) -> None:
        import mujoco
        import numpy as np

        self._mujoco = mujoco
        self._np = np
        self._model = model
        self._data = mujoco.MjData(model)
        self._dynamic_arm_tracking = (
            copy.deepcopy(dynamic_arm_tracking) if dynamic_arm_tracking is not None else None
        )
        self._site = mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_SITE,
            "right_gripper_pinch",
        )
        pelvis = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
        if self._site < 0 or pelvis < 0:
            raise TrainingError(
                "WHOLE_BODY_CONTROL_BINDING_MISSING",
                "Whole-body controller requires pelvis and right_gripper_pinch.",
            )
        root_joint = int(model.body_jntadr[pelvis])
        root_dof = int(model.jnt_dofadr[root_joint])
        self._base_dofs = np.asarray([root_dof, root_dof + 1, root_dof + 5], dtype=int)
        self._joint_names = WHOLE_BODY_CONTROLLER["controlledJoints"]
        self._policy_joint_names = list(control_profile["policyJoints"])
        self._held_joint_names = list(control_profile["heldJoints"])
        self._joint_ids = np.asarray(
            [
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
                for name in self._joint_names
            ],
            dtype=int,
        )
        self._policy_joint_ids = np.asarray(
            [
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
                for name in self._policy_joint_names
            ],
            dtype=int,
        )
        held_names = self._held_joint_names
        self._held_joint_ids = np.asarray(
            [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name) for name in held_names],
            dtype=int,
        )
        self._policy_actuator_names = list(control_profile["policyActuators"])
        self._held_actuator_names = list(control_profile["heldActuators"])
        self._gripper_actuator_names = list(control_profile["gripperActuators"])
        policy_actuator_ids = np.asarray(
            [
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
                for name in self._policy_actuator_names
            ],
            dtype=int,
        )
        held_actuator_ids = np.asarray(
            [
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
                for name in self._held_actuator_names
            ],
            dtype=int,
        )
        gripper_actuator_ids = np.asarray(
            [
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
                for name in self._gripper_actuator_names
            ],
            dtype=int,
        )
        if (
            (self._joint_ids < 0).any()
            or (self._policy_joint_ids < 0).any()
            or (self._held_joint_ids < 0).any()
            or (policy_actuator_ids < 0).any()
            or (held_actuator_ids < 0).any()
            or (gripper_actuator_ids < 0).any()
        ):
            raise TrainingError(
                "WHOLE_BODY_CONTROL_BINDING_MISSING",
                "Whole-body joint or actuator binding is absent from the target model.",
            )
        self._joint_qpos = model.jnt_qposadr[self._joint_ids]
        self._joint_dofs = model.jnt_dofadr[self._joint_ids]
        self._joint_ranges = model.jnt_range[self._joint_ids]
        self._policy_qpos = model.jnt_qposadr[self._policy_joint_ids]
        self._policy_dofs = model.jnt_dofadr[self._policy_joint_ids]
        self._policy_ranges = model.jnt_range[self._policy_joint_ids]
        self._held_qpos = model.jnt_qposadr[self._held_joint_ids]
        self._held_dofs = model.jnt_dofadr[self._held_joint_ids]
        self._held_ranges = model.jnt_range[self._held_joint_ids]
        self._held_reference_targets = np.asarray(control_profile["heldTargets"], dtype=float)
        self._held_index = {name: index for index, name in enumerate(self._held_joint_names)}
        self._actuator_names = (
            self._policy_actuator_names + self._held_actuator_names + self._gripper_actuator_names
        )
        self._actuator_ids = np.concatenate(
            (policy_actuator_ids, held_actuator_ids, gripper_actuator_ids)
        )
        self._actuator_ctrlrange = model.actuator_ctrlrange[self._actuator_ids]
        self._actuator_limited = model.actuator_ctrllimited[self._actuator_ids].astype(bool)
        policy_stop = len(self._policy_actuator_names)
        held_stop = policy_stop + len(self._held_actuator_names)
        self._actuator_slices = {
            "policy": slice(0, policy_stop),
            "held": slice(policy_stop, held_stop),
            "gripper": slice(held_stop, len(self._actuator_names)),
        }
        self._held_ctrlrange = model.actuator_ctrlrange[held_actuator_ids]

    def solve(self, qpos, qvel, target, *, allow_base: bool = True) -> dict[str, Any]:
        np = self._np
        qpos_value = np.asarray(qpos, dtype=float)
        qvel_value = np.asarray(qvel, dtype=float)
        target_value = np.asarray(target, dtype=float)
        self._data.qpos[:] = qpos_value
        self._data.qvel[:] = qvel_value
        self._mujoco.mj_forward(self._model, self._data)
        current = self._data.site_xpos[self._site].copy()
        error = target_value - current
        desired = float(WHOLE_BODY_CONTROLLER["cartesianGain"]) * error
        desired_norm = float(np.linalg.norm(desired))
        speed_limit = float(WHOLE_BODY_CONTROLLER["maximumCartesianSpeed"])
        if desired_norm > speed_limit:
            desired *= speed_limit / desired_norm
        jacp = np.zeros((3, self._model.nv))
        jacr = np.zeros((3, self._model.nv))
        self._mujoco.mj_jacSite(
            self._model,
            self._data,
            jacp,
            jacr,
            self._site,
        )
        selected_dofs = np.concatenate((self._base_dofs, self._joint_dofs))
        jacobian = jacp[:, selected_dofs]
        regularization = np.asarray(WHOLE_BODY_CONTROLLER["regularization"], dtype=float)
        hessian = jacobian.T @ jacobian + np.diag(regularization**2)
        gradient = -(jacobian.T @ desired)
        lower = np.asarray(WHOLE_BODY_CONTROLLER["velocityLowerBounds"], dtype=float)
        upper = np.asarray(WHOLE_BODY_CONTROLLER["velocityUpperBounds"], dtype=float)
        if not allow_base:
            lower = lower.copy()
            upper = upper.copy()
            lower[:3] = 0.0
            upper[:3] = 0.0
        if self._dynamic_arm_tracking is not None:
            lower = lower.copy()
            upper = upper.copy()
            lower[:4] = 0.0
            upper[:4] = 0.0
        decision, objective, projected_gradient = solve_box_qp(
            hessian,
            gradient,
            lower,
            upper,
            iterations=int(WHOLE_BODY_CONTROLLER["qpIterations"]),
        )
        held_targets = (
            self._held_reference_targets.copy()
            if self._dynamic_arm_tracking is not None
            else qpos_value[self._held_qpos].copy()
        )
        horizon = float(WHOLE_BODY_CONTROLLER["targetHorizonSeconds"])
        maximum_step = float(WHOLE_BODY_CONTROLLER["maximumJointTargetStep"])
        margin = float(WHOLE_BODY_CONTROLLER["jointLimitMarginRadians"])
        joint_delta = np.clip(decision[3:] * horizon, -maximum_step, maximum_step)
        joint_targets = np.clip(
            qpos_value[self._joint_qpos] + joint_delta,
            self._joint_ranges[:, 0] + margin,
            self._joint_ranges[:, 1] - margin,
        )
        for name, value in zip(self._joint_names, joint_targets, strict=True):
            if (
                self._dynamic_arm_tracking is not None
                and name not in self._dynamic_arm_tracking["controlledJoints"]
            ):
                continue
            held_targets[self._held_index[name]] = value
        feedforward = (
            float(WHOLE_BODY_CONTROLLER["feedforwardScale"]) * self._data.qfrc_bias[self._held_dofs]
        )
        reserve = float(WHOLE_BODY_CONTROLLER["feedforwardControlReserve"])
        limits = np.max(np.abs(self._held_ctrlrange), axis=1) * (1.0 - reserve)
        feedforward = np.clip(feedforward, -limits, limits)
        predicted_velocity = jacobian @ decision
        return {
            "baseCommand": [float(value) for value in decision[:3]],
            "heldTargets": [float(value) for value in held_targets],
            "feedforwardTorque": [float(value) for value in feedforward],
            "tcpPosition": [float(value) for value in current],
            "targetErrorMeters": float(np.linalg.norm(error)),
            "predictedVelocityResidual": float(np.linalg.norm(predicted_velocity - desired)),
            "qpObjective": objective,
            "qpProjectedGradient": projected_gradient,
            "decision": [float(value) for value in decision],
        }

    def site_state(self, qpos, qvel, target) -> dict[str, Any]:
        np = self._np
        self._data.qpos[:] = np.asarray(qpos, dtype=float)
        self._data.qvel[:] = np.asarray(qvel, dtype=float)
        self._mujoco.mj_forward(self._model, self._data)
        jacp = np.zeros((3, self._model.nv))
        jacr = np.zeros((3, self._model.nv))
        self._mujoco.mj_jacSite(
            self._model,
            self._data,
            jacp,
            jacr,
            self._site,
        )
        velocity = jacp @ np.asarray(qvel, dtype=float)
        position = self._data.site_xpos[self._site].copy()
        return {
            "tcpPosition": [float(value) for value in position],
            "tcpSpeed": float(np.linalg.norm(velocity)),
            "targetErrorMeters": float(np.linalg.norm(np.asarray(target, dtype=float) - position)),
            "heldPositions": [float(value) for value in self._data.qpos[self._held_qpos]],
            "heldVelocities": [float(value) for value in self._data.qvel[self._held_dofs]],
        }

    def diagnostic_state(
        self,
        qpos,
        qvel,
        applied_control,
        *,
        joint_limit_tolerance: float,
    ) -> dict[str, Any]:
        """Return trace-only joint and actuator evidence without changing control."""

        np = self._np
        qpos_value = np.asarray(qpos, dtype=float)
        qvel_value = np.asarray(qvel, dtype=float)
        applied_value = np.asarray(applied_control, dtype=float)[self._actuator_ids]
        limits = np.max(np.abs(self._actuator_ctrlrange), axis=1)
        utilization = np.divide(
            np.abs(applied_value),
            limits,
            out=np.zeros_like(applied_value),
            where=limits > 0,
        )
        tolerance = np.maximum(limits * 1e-7, 1e-9)
        saturated = self._actuator_limited & (
            (applied_value <= self._actuator_ctrlrange[:, 0] + tolerance)
            | (applied_value >= self._actuator_ctrlrange[:, 1] - tolerance)
        )

        def joint_records(names, qpos_indices, dof_indices, joint_ranges):
            return [
                {
                    "name": name,
                    "position": _trace_number(qpos_value[qpos_index]),
                    "velocity": _trace_number(qvel_value[dof_index]),
                    "lowerLimit": _trace_number(joint_range[0]),
                    "upperLimit": _trace_number(joint_range[1]),
                    "tolerance": _trace_number(joint_limit_tolerance),
                    "violated": bool(
                        qpos_value[qpos_index] < joint_range[0] - joint_limit_tolerance
                        or qpos_value[qpos_index] > joint_range[1] + joint_limit_tolerance
                    ),
                }
                for name, qpos_index, dof_index, joint_range in zip(
                    names,
                    qpos_indices,
                    dof_indices,
                    joint_ranges,
                    strict=True,
                )
            ]

        actuator_records = [
            {
                "name": name,
                "appliedControl": _trace_number(value),
                "lowerLimit": _trace_number(control_range[0]),
                "upperLimit": _trace_number(control_range[1]),
                "limited": bool(limited),
                "utilization": _trace_number(ratio),
                "saturated": bool(is_saturated),
            }
            for name, value, control_range, limited, ratio, is_saturated in zip(
                self._actuator_names,
                applied_value,
                self._actuator_ctrlrange,
                self._actuator_limited,
                utilization,
                saturated,
                strict=True,
            )
        ]
        groups = {
            group: actuator_records[group_slice]
            for group, group_slice in self._actuator_slices.items()
        }
        return {
            "jointState": {
                "policy": joint_records(
                    self._policy_joint_names,
                    self._policy_qpos,
                    self._policy_dofs,
                    self._policy_ranges,
                ),
                "held": joint_records(
                    self._held_joint_names,
                    self._held_qpos,
                    self._held_dofs,
                    self._held_ranges,
                ),
            },
            "actuation": {
                "groups": groups,
                "saturationCount": int(np.count_nonzero(saturated)),
                "maximumUtilization": _trace_number(np.max(utilization, initial=0.0)),
            },
        }


def validate_whole_body_profile(
    base_profile: dict[str, Any],
    supervisor_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    validate_profile(base_profile)
    make_supervisor_evaluation_profile(base_profile, supervisor_profile)
    if (
        profile.get("profileVersion") != "0.1.0"
        or profile.get("status") != "research"
        or profile.get("stage") != "whole_body_task_space_control_spike"
    ):
        raise TrainingError(
            "WHOLE_BODY_PROFILE_UNSUPPORTED",
            "A5-C must use whole_body_task_space_control_spike v0.1.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "WHOLE_BODY_BASE_PROFILE_MISMATCH",
            "A5-C is not bound to the base training Profile.",
        )
    if profile.get("supervisorProfileDigest") != digest_json(supervisor_profile):
        raise TrainingError(
            "WHOLE_BODY_SUPERVISOR_MISMATCH",
            "A5-C is not bound to the passing A4 supervisor Profile.",
        )
    if profile.get("failedA5RReportDigest") != A5R_FAILED_REPORT_DIGEST:
        raise TrainingError(
            "WHOLE_BODY_A5R_LINEAGE_MISMATCH",
            "A5-C must remain bound to the archived A5-R failure evidence.",
        )
    for key in ("motionPolicy", "capturePolicy", "standPolicy"):
        if profile.get(key) != supervisor_profile[key]:
            raise TrainingError(
                "WHOLE_BODY_POLICY_LINEAGE_MISMATCH",
                "A5-C must reuse the frozen A4 policy identities.",
            )
    task_geometry_calibration = profile.get("taskGeometryCalibration")
    a5cg_evidence = profile.get("a5cgEvidence")
    if (task_geometry_calibration is None) != (a5cg_evidence is None):
        raise TrainingError(
            "WHOLE_BODY_TASK_GEOMETRY_LINEAGE_INCOMPLETE",
            "A5-CH requires both the task geometry calibration and A5-CG failure evidence.",
        )
    expected_scene = ERGONOMIC_TASK_SCENE if task_geometry_calibration is not None else TASK_SCENE
    if profile.get("scene") != expected_scene:
        raise TrainingError(
            "WHOLE_BODY_SCENE_INVALID",
            "A5-C must use the primitive scene selected by its frozen lineage.",
        )
    if task_geometry_calibration is not None:
        if task_geometry_calibration != TASK_GEOMETRY_CALIBRATION:
            raise TrainingError(
                "WHOLE_BODY_TASK_GEOMETRY_INVALID",
                "A5-CH must use the frozen measured stable-workspace calibration.",
            )
        if a5cg_evidence != A5CG_FAILURE_EVIDENCE:
            raise TrainingError(
                "WHOLE_BODY_TASK_GEOMETRY_EVIDENCE_MISMATCH",
                "A5-CH must remain bound to the archived A5-CG fall-height evidence.",
            )
    if profile.get("controller") != WHOLE_BODY_CONTROLLER:
        raise TrainingError(
            "WHOLE_BODY_CONTROLLER_INVALID",
            "A5-C controller contract changed.",
        )
    if profile.get("qualityGates") != WHOLE_BODY_GATES:
        raise TrainingError(
            "WHOLE_BODY_GATES_INVALID",
            "A5-C Spike gates cannot be relaxed.",
        )
    task_policy_handoff = profile.get("taskPolicyHandoff")
    diagnostic_evidence = profile.get("diagnosticEvidence")
    if (task_policy_handoff is None) != (diagnostic_evidence is None):
        raise TrainingError(
            "WHOLE_BODY_HANDOFF_LINEAGE_INCOMPLETE",
            "A5-CF requires both the handoff contract and its A5-CI diagnostic evidence.",
        )
    if task_policy_handoff is not None:
        if task_policy_handoff != TASK_POLICY_HANDOFF:
            raise TrainingError(
                "WHOLE_BODY_HANDOFF_INVALID",
                "A5-CF must use the frozen hysteretic capture-blend handoff contract.",
            )
        if diagnostic_evidence != A5CI_DIAGNOSTIC_EVIDENCE:
            raise TrainingError(
                "WHOLE_BODY_HANDOFF_EVIDENCE_MISMATCH",
                "A5-CF must remain bound to the passing A5-CI failure evidence.",
            )
    dynamic_arm_tracking = profile.get("dynamicArmTracking")
    a5cf_evidence = profile.get("a5cfEvidence")
    if (dynamic_arm_tracking is None) != (a5cf_evidence is None):
        raise TrainingError(
            "WHOLE_BODY_DYNAMIC_ARM_LINEAGE_INCOMPLETE",
            "A5-CG requires both the dynamic arm contract and A5-CF failure evidence.",
        )
    if dynamic_arm_tracking is not None:
        if task_policy_handoff is None:
            raise TrainingError(
                "WHOLE_BODY_DYNAMIC_ARM_HANDOFF_MISSING",
                "A5-CG must preserve the passing A5-CF task policy handoff contract.",
            )
        if dynamic_arm_tracking != DYNAMIC_ARM_TRACKING:
            raise TrainingError(
                "WHOLE_BODY_DYNAMIC_ARM_INVALID",
                "A5-CG must lock the base and torso while controlling only the right arm.",
            )
        if a5cf_evidence != A5CF_FAILURE_EVIDENCE:
            raise TrainingError(
                "WHOLE_BODY_DYNAMIC_ARM_EVIDENCE_MISMATCH",
                "A5-CG must remain bound to the archived A5-CF fall-height evidence.",
            )
    if task_geometry_calibration is not None and dynamic_arm_tracking is None:
        raise TrainingError(
            "WHOLE_BODY_TASK_GEOMETRY_CONTROLLER_MISSING",
            "A5-CH must preserve the A5-CG dynamic arm controller.",
        )
    runtime = profile.get("runtime", {})
    if (
        runtime.get("ccdIterations") != 50
        or runtime.get("evaluationEnvironments") != 1
        or runtime.get("mjxCapacity") != TASK_CAPACITY
    ):
        raise TrainingError(
            "WHOLE_BODY_RUNTIME_INVALID",
            "A5-C requires the repaired one-environment A5-R runtime.",
        )
    if (
        runtime.get("containerDigest")
        != runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1]
    ):
        raise TrainingError(
            "WHOLE_BODY_CONTAINER_BINDING_MISMATCH",
            "A5-C containerImage and containerDigest differ.",
        )
    if profile.get("artifactPolicy") != {
        "controller": "research_only",
        "distribution": "internal_only",
        "fullTaskClaim": "forbidden",
        "l3Claim": "forbidden",
    }:
        raise TrainingError(
            "WHOLE_BODY_ARTIFACT_POLICY_INVALID",
            "A5-C Spike cannot claim the full task or L3.",
        )


def make_whole_body_evaluation_profile(
    base_profile: dict[str, Any],
    supervisor_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    validate_whole_body_profile(base_profile, supervisor_profile, profile)
    effective = make_supervisor_evaluation_profile(base_profile, supervisor_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["runtime"]["mjxCapacity"] = copy.deepcopy(profile["runtime"]["mjxCapacity"])
    effective["training"]["numEnvs"] = 1
    effective["training"]["seed"] = profile["seed"]
    return effective


def evaluate_whole_body_control_spike(
    profile: dict[str, Any],
    env,
    motion_policy,
    capture_policy,
    stand_policy,
    task_policy_handoff: Mapping[str, Any] | None = None,
    dynamic_arm_tracking: Mapping[str, Any] | None = None,
    task_scene: Mapping[str, Any] = TASK_SCENE,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import jax
    import jax.numpy as jp
    import numpy as np

    motion_inference = jax.jit(motion_policy)
    capture_inference = jax.jit(capture_policy)
    stand_inference = jax.jit(stand_policy)
    reset = jax.jit(env.reset)
    step = jax.jit(env.step)
    controller = WholeBodyTaskSpaceController(
        env.mj_model,
        profile["control"],
        dynamic_arm_tracking,
    )
    rng = jax.random.PRNGKey(profile["training"]["seed"])
    state = reset(rng)
    supervisor = SupervisorState()
    task_supervisor = TaskPolicyHandoffState() if task_policy_handoff is not None else None
    traces: list[dict[str, Any]] = []
    nonfinite = 0
    done_seen = False
    failure = None
    hold_steps = 0
    initial_task_base = None
    minimum_height = float("inf")
    minimum_upright = float("inf")
    maximum_projected_gradient = 0.0
    terminal_reasons: set[str] = set()

    def with_inputs(state_value, command, held_targets, feedforward):
        info = dict(state_value.info)
        info["command"] = command
        info["held_targets"] = jp.asarray(held_targets)
        info["held_feedforward"] = jp.asarray(feedforward)
        info["gripper_commands"] = jp.asarray([0.0])
        false_value = command[0] < command[0]
        info["transition_active"] = false_value
        info["stand_replay_active"] = false_value
        info["capture_active"] = false_value
        observation = {
            "state": env._observation(
                state_value.data,
                info["last_action"],
                command,
            )
        }
        return state_value.replace(info=info, obs=observation)

    total_steps = (
        SUPERVISOR["moveSteps"]
        + SUPERVISOR["settleSteps"]
        + WHOLE_BODY_GATES["settleSteps"]
        + WHOLE_BODY_GATES["trackingSteps"]
    )
    final_site = None
    for index in range(total_steps):
        moving = index < SUPERVISOR["moveSteps"]
        supervisor_settle_end = SUPERVISOR["moveSteps"] + SUPERVISOR["settleSteps"]
        transitioning = not moving and index < supervisor_settle_end
        if moving or transitioning:
            phase = "locomotion"
            if transitioning:
                phase = "locomotion_settle"
            command = jp.asarray([0.5, 0.0, 0.0]) if moving else jp.asarray([0.0, 0.0, 0.0])
            held_targets = [0.0] * 9
            feedforward = [0.0] * 9
            control = None
        else:
            if supervisor.phase != "stand":
                failure = "locomotion_supervisor_not_ready"
                break
            if initial_task_base is None:
                initial_task_base = np.asarray(state.data.qpos[:3], dtype=float).copy()
            settle_end = supervisor_settle_end + WHOLE_BODY_GATES["settleSteps"]
            phase = "whole_body_settle" if index < settle_end else "track_handle"
            metrics = _task_metrics(env, state, task_scene)
            target_phase = "stand_ready" if phase == "whole_body_settle" else "reach_handle"
            target = _target_for_phase(target_phase, metrics, task_scene)
            control = controller.solve(
                np.asarray(state.data.qpos),
                np.asarray(state.data.qvel),
                target,
            )
            command = jp.asarray(control["baseCommand"])
            held_targets = control["heldTargets"]
            feedforward = control["feedforwardTorque"]
            maximum_projected_gradient = max(
                maximum_projected_gradient,
                control["qpProjectedGradient"],
            )
        policy_command = command
        task_handoff_phase = None
        task_handoff_alpha = None
        if not (moving or transitioning) and task_supervisor is not None:
            command_norm = float(np.linalg.norm(np.asarray(command)))
            task_handoff_phase = task_supervisor.prepare(command_norm)
            if task_handoff_phase != "motion":
                policy_command = jp.asarray(
                    task_policy_handoff["policyObservationCommandDuringHandoff"]
                )
        state = with_inputs(state, policy_command, held_targets, feedforward)
        rng, motion_rng, capture_rng, stand_rng = jax.random.split(rng, 4)
        motion_action, _ = motion_inference(state.obs, motion_rng)
        capture_action, _ = capture_inference(state.obs, capture_rng)
        stand_action, _ = stand_inference(state.obs, stand_rng)
        if moving or transitioning:
            action, active_policy, _ = supervisor.select(
                moving,
                motion_action,
                capture_action,
                stand_action,
            )
        elif task_supervisor is not None:
            action, active_policy, task_handoff_alpha = task_supervisor.select(
                motion_action,
                capture_action,
                stand_action,
            )
        else:
            use_motion = bool(np.linalg.norm(np.asarray(command)) > 0.01)
            action = motion_action if use_motion else stand_action
            active_policy = "motion" if use_motion else "stand"
        state = step(state, action)
        jax.block_until_ready(state.reward)
        qpos = np.asarray(state.data.qpos)
        qvel = np.asarray(state.data.qvel)
        linear = np.asarray(env.local_velocity(state.data), dtype=float)
        angular = np.asarray(env.angular_velocity(state.data), dtype=float)
        height = float(np.asarray(state.data.xpos[env.pelvis_body_id, 2]))
        upright = float(np.asarray(env.upvector(state.data)[2]))
        finite = bool(np.isfinite(qpos).all() and np.isfinite(qvel).all())
        done = bool(np.asarray(state.done))
        diagnostic = controller.diagnostic_state(
            qpos,
            qvel,
            state.data.ctrl,
            joint_limit_tolerance=float(env._joint_limit_tolerance),
        )
        actuation = diagnostic["actuation"]
        raw_termination = state.info.get("termination")
        if isinstance(raw_termination, Mapping):
            termination = {}
            for name, value in raw_termination.items():
                array = np.asarray(value)
                termination[name] = (
                    bool(array)
                    if array.shape == () and np.issubdtype(array.dtype, np.bool_)
                    else None
                )
        else:
            termination = raw_termination
        if isinstance(termination, Mapping):
            terminal_reasons.update(name for name, active in termination.items() if active is True)
        minimum_height = min(minimum_height, height)
        minimum_upright = min(minimum_upright, upright)
        nonfinite += 0 if finite else 1
        if moving or transitioning:
            supervisor.observe(
                active_policy,
                float(np.linalg.norm(linear)),
                float(np.linalg.norm(angular)),
            )
            if supervisor.handoff_failed:
                failure = "locomotion_handoff_timeout"
            site = None
        else:
            if task_supervisor is not None:
                task_supervisor.observe(
                    active_policy,
                    float(np.linalg.norm(linear)),
                    float(np.linalg.norm(angular)),
                )
                if task_supervisor.handoff_failed:
                    failure = failure or "task_policy_handoff_timeout"
            metrics = _task_metrics(env, state, task_scene)
            target_phase = "stand_ready" if phase == "whole_body_settle" else "reach_handle"
            target = _target_for_phase(target_phase, metrics, task_scene)
            site = controller.site_state(qpos, qvel, target)
            final_site = site
            within = (
                phase == "track_handle"
                and site["targetErrorMeters"] <= WHOLE_BODY_GATES["positionToleranceMeters"]
                and site["tcpSpeed"] <= WHOLE_BODY_GATES["maximumTcpSpeed"]
            )
            hold_steps = hold_steps + 1 if within else 0
        record = {
            "step": index,
            "timeSeconds": (index + 1) * env.dt,
            "phase": phase,
            "activePolicy": active_policy,
            "command": [_trace_number(value) for value in np.asarray(command)],
            "basePosition": [_trace_number(value) for value in qpos[:3]],
            "baseState": {
                "position": [_trace_number(value) for value in qpos[:3]],
                "linearVelocity": [_trace_number(value) for value in linear],
                "angularVelocity": [_trace_number(value) for value in angular],
                "height": _trace_number(height),
                "uprightCosine": _trace_number(upright),
            },
            "minimumBaseHeight": _trace_number(minimum_height),
            "minimumUprightCosine": _trace_number(minimum_upright),
            "finite": finite,
            "done": done,
            "termination": termination,
            "jointState": diagnostic["jointState"],
            "actuation": actuation,
            "control": control,
            "site": site,
        }
        if task_supervisor is not None and not (moving or transitioning):
            record["policyCommand"] = [_trace_number(value) for value in np.asarray(policy_command)]
            record["taskPolicyHandoff"] = {
                "phase": task_handoff_phase,
                "blendAlpha": _trace_number(task_handoff_alpha),
                "requestedCommandNorm": _trace_number(np.linalg.norm(np.asarray(command))),
                "captureSteps": task_supervisor.capture_steps,
                "stableSteps": task_supervisor.stable_steps,
                "blendSteps": task_supervisor.blend_steps,
                "handoffFailed": task_supervisor.handoff_failed,
            }
        traces.append(record)
        diagnostic_errors = _diagnostic_trace_errors(record, profile["control"])
        if diagnostic_errors:
            failure = failure or f"diagnostic_incomplete:{diagnostic_errors[0]}"
        if done:
            done_seen = True
            reason = ",".join(sorted(terminal_reasons)) or "unclassified"
            failure = failure or f"robot_termination:{reason}"
        if failure:
            break
    if initial_task_base is None:
        initial_task_base = np.asarray(state.data.qpos[:3], dtype=float)
    final_base = np.asarray(state.data.qpos[:3], dtype=float)
    base_delta = final_base - initial_task_base
    diagnostic_assessment = assess_diagnostic_trace(traces, profile["control"])
    passed = (
        failure is None
        and diagnostic_assessment["status"] == "passed"
        and final_site is not None
        and hold_steps >= WHOLE_BODY_GATES["holdSteps"]
        and final_site["targetErrorMeters"] <= WHOLE_BODY_GATES["positionToleranceMeters"]
        and final_site["tcpSpeed"] <= WHOLE_BODY_GATES["maximumTcpSpeed"]
        and float(np.linalg.norm(base_delta[:2])) <= WHOLE_BODY_GATES["maximumBaseTranslation"]
        and abs(float(base_delta[1])) <= WHOLE_BODY_GATES["maximumBaseLateralDrift"]
        and minimum_height >= WHOLE_BODY_GATES["minimumBaseHeight"]
        and minimum_upright >= WHOLE_BODY_GATES["minimumUprightCosine"]
        and maximum_projected_gradient <= WHOLE_BODY_GATES["maximumProjectedGradient"]
        and nonfinite <= WHOLE_BODY_GATES["maximumNonFiniteSamples"]
        and not done_seen
    )
    return (
        {
            "id": "test://worldspec/h1-kitchen/whole-body-control-spike/1",
            "result": "pass" if passed else "fail",
            "metrics": {
                "failedReason": failure,
                "holdSteps": hold_steps,
                "finalTargetErrorMeters": (final_site["targetErrorMeters"] if final_site else None),
                "finalTcpSpeed": final_site["tcpSpeed"] if final_site else None,
                "baseTranslation": float(np.linalg.norm(base_delta[:2])),
                "baseLateralDrift": abs(float(base_delta[1])),
                "minimumBaseHeight": minimum_height,
                "minimumUprightCosine": minimum_upright,
                "maximumProjectedGradient": maximum_projected_gradient,
                "nonFiniteSamples": nonfinite,
                "doneSeen": done_seen,
                "terminalReasons": diagnostic_assessment["terminalReasons"],
                "terminalJoints": diagnostic_assessment["terminalJoints"],
                "controlSaturationSamples": diagnostic_assessment["controlSaturationSamples"],
                "maximumControlUtilization": diagnostic_assessment["maximumControlUtilization"],
                "diagnosticStatus": diagnostic_assessment["status"],
                "diagnosticReasons": diagnostic_assessment["reasons"],
                "taskPolicyHandoffEnabled": task_supervisor is not None,
                "taskPolicyFinalPhase": (
                    task_supervisor.phase if task_supervisor is not None else None
                ),
                "taskPolicyHandoffFailed": (
                    task_supervisor.handoff_failed if task_supervisor is not None else False
                ),
                "dynamicArmTrackingEnabled": dynamic_arm_tracking is not None,
                "taskGeometryCalibrationEnabled": task_scene == ERGONOMIC_TASK_SCENE,
            },
        },
        traces,
    )


def run_whole_body_control_spike(
    base_profile: dict[str, Any],
    supervisor_profile: dict[str, Any],
    profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
    output_dir: Path,
    motion_archive: Path,
    capture_archive: Path,
    stand_archive: Path,
) -> dict[str, Any]:
    from brax.training.agents.ppo import networks as ppo_networks

    from .environment import make_environment

    effective = make_whole_body_evaluation_profile(
        base_profile,
        supervisor_profile,
        profile,
    )
    static = static_preflight(base_profile, bundle_dir)
    task_model, derivation = prepare_kitchen_task_model(
        base_profile,
        bundle_dir,
        model_dir,
        profile["scene"],
    )
    runtime = runtime_preflight(effective, task_model)
    output_dir.mkdir(parents=True, exist_ok=True)
    network_factory = functools.partial(
        ppo_networks.make_ppo_networks,
        policy_hidden_layer_sizes=(128, 128, 128, 128),
        value_hidden_layer_sizes=(256, 256, 256, 256, 256),
        policy_obs_key="state",
        value_obs_key="state",
    )
    environment = make_environment(effective, task_model)
    observation_size = _flat_observation_size(environment.observation_size["state"])
    action_size = int(environment.action_size)
    loaded: dict[str, dict[str, Any]] = {}
    policies: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-whole-body-") as temporary:
        root = Path(temporary)
        for role, archive, source in (
            ("motion", motion_archive, profile["motionPolicy"]),
            ("capture", capture_archive, profile["capturePolicy"]),
            ("stand", stand_archive, profile["standPolicy"]),
        ):
            step_path, initialization = materialize_warm_start(
                archive,
                root / role,
                source["checkpointDigest"],
                source["checkpointSizeBytes"],
            )
            validate_network_compatibility(initialization, observation_size, action_size)
            policies[role] = _load_deterministic_teacher_policy(
                step_path,
                initialization,
                network_factory,
            )
            initialization["role"] = source["selectedRole"]
            loaded[role] = initialization
        test, traces = evaluate_whole_body_control_spike(
            effective,
            environment,
            policies["motion"],
            policies["capture"],
            policies["stand"],
            profile.get("taskPolicyHandoff"),
            profile.get("dynamicArmTracking"),
            profile["scene"],
        )
    trace_path = output_dir / "evaluation-traces.jsonl"
    with trace_path.open("w", encoding="utf-8") as stream:
        for record in traces:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    controller_artifact = {
        "controllerVersion": "0.1.0",
        "status": "research_only",
        "profileDigest": digest_json(profile),
        "supervisorProfileDigest": digest_json(supervisor_profile),
        "controller": copy.deepcopy(WHOLE_BODY_CONTROLLER),
        **(
            {"taskPolicyHandoff": copy.deepcopy(profile["taskPolicyHandoff"])}
            if "taskPolicyHandoff" in profile
            else {}
        ),
        **(
            {"dynamicArmTracking": copy.deepcopy(profile["dynamicArmTracking"])}
            if "dynamicArmTracking" in profile
            else {}
        ),
        **(
            {"taskGeometryCalibration": copy.deepcopy(profile["taskGeometryCalibration"])}
            if "taskGeometryCalibration" in profile
            else {}
        ),
        "scene": copy.deepcopy(profile["scene"]),
        "policies": {
            role: {
                "checkpointDigest": value["archiveDigest"],
                "selectedStep": value["selectedStep"],
            }
            for role, value in loaded.items()
        },
        "distribution": "internal_only",
        "fullTaskClaim": "forbidden",
        "l3Claim": "forbidden",
    }
    controller_path = output_dir / "whole-body-controller.json"
    controller_path.write_bytes(canonical_bytes(controller_artifact))
    passed = test["result"] == "pass"
    return {
        "baseTrainingProfileDigest": digest_json(base_profile),
        "supervisorProfileDigest": digest_json(supervisor_profile),
        "controlProfileDigest": digest_json(profile),
        "policies": loaded,
        "staticPreflight": static,
        "runtimePreflight": runtime,
        "target": {
            "sourceBundleDigest": derivation["parentDerivation"]["sourceBundleDigest"],
            "derivedModelDigest": derivation["derivedModelDigest"],
            "observationSize": observation_size,
            "actionSize": action_size,
        },
        "scene": copy.deepcopy(profile["scene"]),
        "controller": copy.deepcopy(WHOLE_BODY_CONTROLLER),
        **(
            {"taskPolicyHandoff": copy.deepcopy(profile["taskPolicyHandoff"])}
            if "taskPolicyHandoff" in profile
            else {}
        ),
        **(
            {"dynamicArmTracking": copy.deepcopy(profile["dynamicArmTracking"])}
            if "dynamicArmTracking" in profile
            else {}
        ),
        **(
            {"taskGeometryCalibration": copy.deepcopy(profile["taskGeometryCalibration"])}
            if "taskGeometryCalibration" in profile
            else {}
        ),
        "qualityAssessment": {
            "status": "passed" if passed else "failed",
            "tests": [test],
        },
        "controllerArtifact": {
            "path": controller_path.name,
            "digest": digest_bytes(controller_path.read_bytes()),
            "sizeBytes": controller_path.stat().st_size,
            "distribution": "internal_only",
        },
        "traceArtifact": {
            "path": trace_path.name,
            "digest": digest_bytes(trace_path.read_bytes()),
            "sizeBytes": trace_path.stat().st_size,
            "distribution": "internal_only",
        },
        "claimBoundary": {
            "status": "control_spike_only",
            "fullTaskClaim": "forbidden",
            "l3Claim": "forbidden",
            "reasons": [
                "only_handle_tracking_is_evaluated",
                "whole_body_control_is_not_yet_validated_for_physical_grasp",
                "right_gripper_mount_evidence_is_estimated",
            ],
        },
    }
