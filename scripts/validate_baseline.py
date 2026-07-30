#!/usr/bin/env python3
"""Repository-only validation for the WorldSpec documentation/schema baseline."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "0.1"
EXAMPLES = ROOT / "examples"
DOCS = ROOT / "docs"


class Failure(Exception):
    pass


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise Failure(f"JSON_PARSE {path.relative_to(ROOT)}: {exc}") from exc


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def schema_registry() -> tuple[dict[str, Any], Registry]:
    schemas: dict[str, Any] = {}
    resources = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = read_json(path)
        Draft202012Validator.check_schema(schema)
        schemas[path.name] = schema
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return schemas, Registry().with_resources(resources)


def walk_refs(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str):
                yield child
            yield from walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_refs(child)


def resolve_pointer(document: Any, fragment: str) -> None:
    if not fragment:
        return
    if not fragment.startswith("/"):
        raise Failure(f"Unsupported JSON pointer fragment: #{fragment}")
    cursor = document
    for token in fragment[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(cursor, list):
            cursor = cursor[int(token)]
        else:
            cursor = cursor[token]


def check_refs(schemas: dict[str, Any]) -> None:
    for schema_name, schema in schemas.items():
        for ref in walk_refs(schema):
            if ref.startswith(("https://", "http://")):
                continue
            file_part, _, fragment = ref.partition("#")
            target_name = file_part or schema_name
            if target_name not in schemas:
                raise Failure(f"BROKEN_REF {schema_name}: {ref}")
            try:
                resolve_pointer(schemas[target_name], fragment)
            except Exception as exc:
                raise Failure(f"BROKEN_REF {schema_name}: {ref}: {exc}") from exc


def validate_instance(
    instance_path: Path,
    schema_name: str,
    schemas: dict[str, Any],
    registry: Registry,
) -> list[str]:
    instance = read_json(instance_path)
    validator = Draft202012Validator(
        schemas[schema_name],
        registry=registry,
        format_checker=FormatChecker(),
    )
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(
            validator.iter_errors(instance), key=lambda item: list(item.absolute_path)
        )
    ]


def all_object_ids(document: Any) -> list[str]:
    result: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("id"), str):
                result.append(value["id"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)
    return result


def semantic_world_errors(document: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    ids = all_object_ids(document)
    if any(count > 1 for count in Counter(ids).values()):
        codes.add("WS_INV_001_DUPLICATE_ID")

    claim_ids = {claim["id"] for claim in document["evidenceGraph"]["claims"]}
    for component in document["components"]:
        for claim_ref in component.get("claimBindings", {}).values():
            if claim_ref not in claim_ids:
                codes.add("WS_INV_032_MISSING_CLAIM")
    for representation in document["representations"]:
        for claim_ref in representation.get("claimRefs", []):
            if claim_ref not in claim_ids:
                codes.add("WS_INV_032_MISSING_CLAIM")

    adjacency: dict[str, list[str]] = defaultdict(list)
    incoming: Counter[str] = Counter()
    for relation in document["relations"]:
        if relation["type"].startswith("worldspec://relation/frame."):
            parent = relation["parentFrame"]
            child = relation["childFrame"]
            adjacency[parent].append(child)
            incoming[child] += 1
    if any(count > 1 for count in incoming.values()):
        codes.add("WS_INV_012_MULTIPLE_FRAME_DRIVERS")

    visiting: set[str] = set()
    visited: set[str] = set()

    def has_cycle(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(has_cycle(child) for child in adjacency[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    if any(has_cycle(node) for node in list(adjacency)):
        codes.add("WS_INV_009_FRAME_CYCLE")
    return codes


def semantic_loss_errors(
    report: dict[str, Any], target: dict[str, Any] | None = None
) -> set[str]:
    codes: set[str] = set()
    coverage = report["coverage"]
    if coverage["reportedItemCount"] != len(report["entries"]):
        codes.add("LOSS_REPORTED_COUNT_MISMATCH")
    if (
        coverage["complete"]
        and coverage["sourceItemCount"] != coverage["reportedItemCount"]
    ):
        codes.add("LOSS_COVERAGE_MISMATCH")
    if target is not None:
        reported = {entry["capability"] for entry in report["entries"]}
        non_exact = {
            item["id"] for item in target["capabilities"] if item["support"] != "exact"
        }
        if not non_exact.issubset(reported):
            codes.add("LOSS_UNREPORTED_NON_EXACT_CAPABILITY")
    return codes


def check_examples(schemas: dict[str, Any], registry: Registry) -> int:
    positive = {
        "minimal-cube/world.json": "world-definition.schema.json",
        "hollow-mug/world.json": "world-definition.schema.json",
        "articulated-drawer/world.json": "world-definition.schema.json",
        "minimal-cube/asset-draft.json": "asset-draft.schema.json",
        "minimal-cube/target-profile.json": "target-profile.schema.json",
        "minimal-cube/target-profile-threejs.json": "target-profile.schema.json",
        "minimal-cube/build-intent.json": "build-intent.schema.json",
        "minimal-cube/loss-report.json": "loss-report.schema.json",
        "minimal-cube/build-manifest.json": "build-manifest.schema.json",
        "minimal-cube/conformance-report.json": "conformance-report.schema.json",
        "minimal-cube/certificate.json": "certificate.schema.json",
        "minimal-cube/rights.json": "rights.schema.json",
        "minimal-cube/source-bundle.json": "source-bundle.schema.json",
        "minimal-cube/ingestion-profile.json": "ingestion-profile.schema.json",
        "minimal-cube/generation-profile.json": "generation-profile.schema.json",
        "minimal-cube/lowering-plan.json": "lowering-plan.schema.json",
        "minimal-cube/artifact-bundle.json": "artifact-bundle.schema.json",
        "minimal-cube/backend-calibration.json": "backend-calibration.schema.json",
        "minimal-cube/predicate-profile.json": "predicate-profile.schema.json",
        "minimal-cube/control-profile.json": "control-profile.schema.json",
        "minimal-cube/task-profile.json": "task-profile.schema.json",
        "minimal-cube/task-run-report.json": "task-run-report.schema.json",
        "minimal-cube/runtime-record.json": "runtime-record.schema.json",
        "minimal-cube/job-spec.json": "job.schema.json",
        "minimal-cube/job-result.json": "job.schema.json",
        "h1-kitchen/composition-profile.json": "h1-composition-profile.schema.json",
        "h1-kitchen/native-load-conformance.darwin-arm64.json": "h1-composition-conformance.schema.json",
        "h1-kitchen/training-model-native-load.darwin-arm64.json": "h1-composition-conformance.schema.json",
        "h1-kitchen/locomotion-adapter-profile.json": "h1-locomotion-adapter.schema.json",
        "h1-kitchen/locomotion-conformance.darwin-arm64.failed.json": "h1-locomotion-conformance.schema.json",
        "h1-kitchen/locomotion-training-profile.json": "h1-locomotion-training-profile.schema.json",
        "h1-kitchen/locomotion-training-profile.task-v1.json": "h1-locomotion-training-profile.schema.json",
        "h1-kitchen/kitchen-task-profile.json": "h1-kitchen-task-profile.schema.json",
        "h1-kitchen/whole-body-control-profile.json": "h1-whole-body-control-profile.schema.json",
        "h1-kitchen/whole-body-policy-handoff-profile.json": "h1-whole-body-control-profile.schema.json",
        "h1-kitchen/whole-body-dynamic-arm-profile.json": "h1-whole-body-control-profile.schema.json",
        "h1-kitchen/whole-body-ergonomic-handle-profile.json": "h1-whole-body-control-profile.schema.json",
        "h1-kitchen/whole-body-base-anchor-profile.json": "h1-whole-body-control-profile.schema.json",
        "h1-kitchen/whole-body-forward-only-base-anchor-profile.json": "h1-whole-body-control-profile.schema.json",
        "h1-kitchen/locomotion-task-load-profile.json": "h1-locomotion-task-load-profile.schema.json",
        "h1-kitchen/locomotion-task-load-retention-profile.json": "h1-locomotion-task-load-retention-profile.schema.json",
        "h1-kitchen/locomotion-task-load-survival-profile.json": "h1-locomotion-task-load-survival-profile.schema.json",
        "h1-kitchen/locomotion-task-load-deployment-eval-profile.json": "h1-locomotion-task-load-deployment-eval-profile.schema.json",
        "h1-kitchen/locomotion-task-load-horizon-profile.json": "h1-locomotion-task-load-horizon-profile.schema.json",
        "h1-kitchen/locomotion-task-load-formal-profile.json": "h1-locomotion-task-load-formal-profile.schema.json",
        "h1-kitchen/whole-body-control.cpu-preflight.passed.json": "h1-whole-body-cpu-preflight.schema.json",
        "h1-kitchen/whole-body-policy-handoff.cpu-preflight.passed.json": "h1-whole-body-cpu-preflight.schema.json",
        "h1-kitchen/whole-body-dynamic-arm.cpu-preflight.passed.json": "h1-whole-body-cpu-preflight.schema.json",
        "h1-kitchen/whole-body-ergonomic-handle.cpu-preflight.passed.json": "h1-whole-body-cpu-preflight.schema.json",
        "h1-kitchen/whole-body-base-anchor.cpu-preflight.passed.json": "h1-whole-body-cpu-preflight.schema.json",
        "h1-kitchen/whole-body-forward-only-base-anchor.cpu-preflight.passed.json": "h1-whole-body-cpu-preflight.schema.json",
        "h1-kitchen/whole-body-control.a800.failed-summary.json": "h1-whole-body-control-failure-summary.schema.json",
        "h1-kitchen/whole-body-policy-handoff.a800.failed-summary.json": "h1-whole-body-controller-failure-evidence.schema.json",
        "h1-kitchen/whole-body-dynamic-arm.a800.failed-summary.json": "h1-whole-body-controller-failure-evidence.schema.json",
        "h1-kitchen/whole-body-ergonomic-handle.a800.failed-summary.json": "h1-whole-body-controller-failure-evidence.schema.json",
        "h1-kitchen/whole-body-base-anchor.a800.failed-summary.json": "h1-whole-body-controller-failure-evidence.schema.json",
        "h1-kitchen/whole-body-forward-only-base-anchor.a800.failed-summary.json": "h1-whole-body-controller-failure-evidence.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay-profile.template.json": "h1-whole-body-diagnostic-replay-profile.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay-profile.attempt-01.json": "h1-whole-body-diagnostic-replay-profile.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay-profile.attempt-02.json": "h1-whole-body-diagnostic-replay-profile.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay-profile.attempt-03.json": "h1-whole-body-diagnostic-replay-profile.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay-profile.attempt-04.json": "h1-whole-body-diagnostic-replay-profile.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay-profile.attempt-05.json": "h1-whole-body-diagnostic-replay-profile.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay-profile.json": "h1-whole-body-diagnostic-replay-profile.schema.json",
        "h1-kitchen/whole-body-diagnostic-trace-record.example.json": "h1-whole-body-diagnostic-trace-record.schema.json",
        "h1-kitchen/whole-body-equivalence-report.example.json": "h1-whole-body-equivalence-report.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay-report.example.json": "h1-whole-body-diagnostic-replay-report.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay.a800.failed-attempt.json": "h1-whole-body-diagnostic-replay-attempt-summary.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay.a800.failed-attempt-02.json": "h1-whole-body-diagnostic-replay-handoff-failure-summary.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay.a800.failed-attempt-03.json": "h1-whole-body-diagnostic-replay-schema-failure-summary.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay.a800.failed-attempt-04.json": "h1-whole-body-diagnostic-replay-trace-schema-failure-summary.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay.a800.passed-summary.json": "h1-whole-body-diagnostic-replay-passed-summary.schema.json",
        "h1-kitchen/diagnostic-replay-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/diagnostic-replay-image-build.a800.attempt-01.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/diagnostic-replay-image-build.a800.attempt-02.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/diagnostic-replay-image-build.a800.attempt-03.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/diagnostic-replay-image-build.a800.attempt-04.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/diagnostic-replay-image-build.a800.attempt-05.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/whole-body-base-anchor-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/whole-body-forward-only-base-anchor-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/whole-body-diagnostic-replay-receipt.example.json": "h1-whole-body-diagnostic-replay-receipt.schema.json",
        "h1-kitchen/kitchen-task-preflight.darwin-arm64.passed.json": "h1-kitchen-task-preflight.schema.json",
        "h1-kitchen/locomotion-training-result.blocked.json": "h1-locomotion-training-result.schema.json",
        "h1-kitchen/runtime-spike.a800.passed.json": "h1-runtime-spike-report.schema.json",
        "h1-kitchen/training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/training-image-build.a5.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/training-image-build.a5-seed-fix.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/training-image-build.a5r.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/whole-body-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/kitchen-task.a800.failed.json": "h1-kitchen-task-report.schema.json",
        "h1-kitchen/kitchen-task.a5r.a800.failed.json": "h1-kitchen-task-report.schema.json",
        "h1-kitchen/transition-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/retention-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/dual-policy-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/capture-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/capture-training-image-build-v2.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/supervisor-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/task-load-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/task-load-retention-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/task-load-survival-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/task-load-horizon-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/task-load-formal-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/ccd-iterations-spike.a800.passed.json": "h1-ccd-iterations-spike-report.schema.json",
        "h1-kitchen/locomotion-transition.a800.failed.json": "h1-locomotion-midterm-report.schema.json",
        "h1-kitchen/locomotion-retention.a800.failed.json": "h1-locomotion-midterm-report.schema.json",
        "h1-kitchen/locomotion-task-load-survival.a800.failed.json": "h1-locomotion-midterm-report.schema.json",
        "h1-kitchen/locomotion-task-load-deployment-eval.a800.failed.json": "h1-locomotion-midterm-report.schema.json",
        "h1-kitchen/locomotion-task-load-horizon.a800.passed.json": "h1-locomotion-midterm-report.schema.json",
        "h1-kitchen/locomotion-task-load-formal.a800.failed-summary.json": "h1-locomotion-formal-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-balance.a800.failed-summary.json": "h1-locomotion-manipulation-balance-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-anchor.a800.failed-summary.json": "h1-locomotion-manipulation-anchor-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-mixed-reset.a800.failed-summary.json": "h1-locomotion-manipulation-mixed-reset-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-post-walk-biased.a800.failed-summary.json": "h1-locomotion-manipulation-post-walk-biased-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-on-policy-continuation.a800.failed-summary.json": "h1-locomotion-manipulation-on-policy-continuation-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-checkpoint-portfolio.a800.runtime-failed-summary.json": "h1-locomotion-manipulation-checkpoint-portfolio-runtime-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-memory-isolation.a800.runtime-failed-summary.json": "h1-locomotion-manipulation-process-isolation-runtime-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-process-isolation-v9.a800.runtime-failed-summary.json": "h1-locomotion-manipulation-process-isolation-v9-runtime-failure-summary.schema.json",
        "h1-kitchen/locked-runtime.a800.passed.json": "h1-locked-runtime-report.schema.json",
        "h1-kitchen/capacity-scale.a800.passed.json": "h1-capacity-scale-report.schema.json",
        "h1-kitchen/ppo-smoke.a800.passed.json": "h1-ppo-smoke-report.schema.json",
        "h1-kitchen/locomotion-calibration-profile.json": "h1-locomotion-calibration-profile.schema.json",
        "h1-kitchen/locomotion-calibration-profile.stand-v1.json": "h1-locomotion-calibration-profile.schema.json",
        "h1-kitchen/locomotion-calibration.a800.failed.json": "h1-locomotion-calibration-attempt.schema.json",
        "h1-kitchen/locomotion-calibration.a800.configuration-failed.json": "h1-locomotion-calibration-attempt.schema.json",
        "h1-kitchen/locomotion-calibration.a800.quality-failed.json": "h1-locomotion-calibration-attempt.schema.json",
        "h1-kitchen/locomotion-calibration.a800.passed.json": "h1-locomotion-calibration-report.schema.json",
        "h1-kitchen/locomotion-midterm-profile.json": "h1-locomotion-midterm-profile.schema.json",
        "h1-kitchen/locomotion-midterm.a800.failed.json": "h1-locomotion-midterm-report.schema.json",
        "h1-kitchen/locomotion-transition-profile.json": "h1-locomotion-transition-profile.schema.json",
        "h1-kitchen/locomotion-retention-profile.json": "h1-locomotion-retention-profile.schema.json",
        "h1-kitchen/locomotion-dual-policy-profile.json": "h1-locomotion-dual-policy-profile.schema.json",
        "h1-kitchen/locomotion-dual-policy.a800.failed.json": "h1-locomotion-dual-policy-report.schema.json",
        "h1-kitchen/locomotion-capture-profile.json": "h1-locomotion-capture-profile.schema.json",
        "h1-kitchen/locomotion-capture.a800.passed.json": "h1-locomotion-capture-report.schema.json",
        "h1-kitchen/locomotion-manipulation-balance-profile.json": "h1-locomotion-manipulation-balance-profile.schema.json",
        "h1-kitchen/locomotion-manipulation-viability-profile.json": "h1-manipulation-viability-profile.schema.json",
        "h1-kitchen/locomotion-supervisor-profile.json": "h1-locomotion-supervisor-profile.schema.json",
        "h1-kitchen/locomotion-supervisor.a800.passed.json": "h1-locomotion-supervisor-report.schema.json",
        "h1-kitchen/locomotion-task-load-supervisor-profile.json": "h1-locomotion-task-load-supervisor-profile.schema.json",
        "h1-kitchen/task-load-supervisor-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/task-load-full-kitchen-single-profile.json": "h1-task-load-full-kitchen-single-profile.schema.json",
        "h1-kitchen/task-load-full-kitchen-single-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-balance-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-anchor-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-mixed-reset-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-post-walk-biased-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-on-policy-continuation-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-checkpoint-portfolio-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-memory-isolated-checkpoint-portfolio-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-process-isolated-checkpoint-portfolio-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-process-isolated-checkpoint-portfolio-v9-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-process-isolated-checkpoint-portfolio-v10-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-process-isolated-checkpoint-portfolio-v10-locked-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-suite-isolated-checkpoint-portfolio-v11-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-unbounded-recovery-checkpoint-portfolio-v12-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-unbounded-recovery-frozen-bank-checkpoint-portfolio-v13-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-unbounded-recovery-frozen-bank-checkpoint-portfolio-v13r1-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/manipulation-hard-negative-replay-checkpoint-portfolio-v14-training-image-build.a800.passed.json": "h1-image-build-report.schema.json",
        "h1-kitchen/locomotion-manipulation-v10-bootstrap.a800.configuration-failed-summary.json": "h1-locomotion-manipulation-bootstrap-configuration-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-suite-isolation.a800.runtime-failed-summary.json": "h1-locomotion-manipulation-suite-isolation-runtime-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-suite-isolated.a800.quality-failed-summary.json": "h1-locomotion-manipulation-suite-isolated-quality-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-frozen-bank.a800.quality-failed-summary.json": "h1-locomotion-manipulation-frozen-bank-quality-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-hard-negative-replay.a800.quality-failed-summary.json": "h1-locomotion-manipulation-hard-negative-replay-quality-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-unbounded-recovery.a800.configuration-failed-summary.json": "h1-locomotion-manipulation-unbounded-recovery-configuration-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-unbounded-recovery.a800.snapshot-generation-failed-summary.json": "h1-locomotion-manipulation-unbounded-recovery-snapshot-generation-failure-summary.schema.json",
        "h1-kitchen/locomotion-manipulation-frozen-bank.a800.model-shape-failed-summary.json": "h1-locomotion-manipulation-frozen-bank-model-shape-failure-summary.schema.json",
        "../third_party/h1-training.lock.json": "h1-training-source-lock.schema.json",
    }
    for relative, schema_name in positive.items():
        path = EXAMPLES / relative
        errors = validate_instance(path, schema_name, schemas, registry)
        if errors:
            raise Failure(f"POSITIVE_EXAMPLE {relative}: {'; '.join(errors)}")
        if path.name == "world.json":
            semantic = semantic_world_errors(read_json(path))
            if semantic:
                raise Failure(f"POSITIVE_SEMANTIC {relative}: {sorted(semantic)}")
    positive_loss = read_json(EXAMPLES / "minimal-cube/loss-report.json")
    positive_target = read_json(EXAMPLES / "minimal-cube/target-profile.json")
    loss_errors = semantic_loss_errors(positive_loss, positive_target)
    if loss_errors:
        raise Failure(f"POSITIVE_LOSS: {sorted(loss_errors)}")
    training_profile = read_json(
        EXAMPLES / "h1-kitchen/locomotion-training-profile.json"
    )
    training_result = read_json(
        EXAMPLES / "h1-kitchen/locomotion-training-result.blocked.json"
    )
    if training_result["trainingProfileDigest"] != canonical_digest(training_profile):
        raise Failure("H1_TRAINING_RESULT_PROFILE_DIGEST_MISMATCH")
    training_lock = ROOT / "third_party/h1-training.lock.json"
    if training_profile["framework"]["sourceLockDigest"] != file_digest(training_lock):
        raise Failure("H1_TRAINING_SOURCE_LOCK_DIGEST_MISMATCH")
    return len(positive)


def check_negative_examples(schemas: dict[str, Any], registry: Registry) -> int:
    expectations = read_json(EXAMPLES / "negative" / "expectations.json")["cases"]
    for case in expectations:
        path = EXAMPLES / "negative" / case["path"]
        schema_errors = validate_instance(path, case["schema"], schemas, registry)
        if case["validationLayer"] == "schema":
            if not schema_errors:
                raise Failure(f"NEGATIVE_NOT_REJECTED {case['path']}")
            continue
        if schema_errors:
            raise Failure(f"NEGATIVE_WRONG_LAYER {case['path']}: {schema_errors}")
        document = read_json(path)
        if case["schema"] == "world-definition.schema.json":
            semantic_errors = semantic_world_errors(document)
        else:
            target_path = path.with_name("target-profile.json")
            target = read_json(target_path) if target_path.exists() else None
            semantic_errors = semantic_loss_errors(document, target)
        if case["expectedCode"] not in semantic_errors:
            raise Failure(
                f"NEGATIVE_NOT_REJECTED {case['path']}: "
                f"expected {case['expectedCode']}, got {sorted(semantic_errors)}"
            )
    return len(expectations)


FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def metadata(path: Path) -> dict[str, str]:
    match = FRONT_MATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        raise Failure(f"MISSING_FRONT_MATTER {path.relative_to(ROOT)}")
    result = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip()
    return result


def check_docs() -> None:
    zh_root = DOCS / "zh-CN"
    en_root = DOCS / "en"
    zh_files = {path.relative_to(zh_root) for path in zh_root.rglob("*.md")}
    en_files = {path.relative_to(en_root) for path in en_root.rglob("*.md")}
    if zh_files != en_files:
        raise Failure(
            f"MIRROR_MISMATCH missing_en={sorted(zh_files - en_files)} "
            f"missing_zh={sorted(en_files - zh_files)}"
        )
    required = {"status", "applies-to", "normative-language", "mirror", "last-verified"}
    for relative in sorted(zh_files):
        zh_path = zh_root / relative
        en_path = en_root / relative
        for path in (zh_path, en_path):
            found = metadata(path)
            missing = required - found.keys()
            if missing:
                raise Failure(
                    f"MISSING_METADATA {path.relative_to(ROOT)}: {sorted(missing)}"
                )
            mirror = (path.parent / found["mirror"]).resolve()
            expected = en_path.resolve() if path == zh_path else zh_path.resolve()
            if mirror != expected:
                raise Failure(
                    f"BAD_MIRROR {path.relative_to(ROOT)} -> {found['mirror']}"
                )
        en_text = en_path.read_text(encoding="utf-8")
        if "The Chinese document is the normative source" not in en_text:
            raise Failure(f"ENGLISH_AUTHORITY_MISSING {en_path.relative_to(ROOT)}")

    for path in [ROOT / "README.md", ROOT / "README.en.md", *DOCS.rglob("*.md")]:
        text = path.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(text):
            target = target.split("#", 1)[0]
            if not target or target.startswith(
                ("http://", "https://", "mailto:", "chatgpt-")
            ):
                continue
            local = (path.parent / target).resolve()
            if not local.exists():
                raise Failure(f"BROKEN_LINK {path.relative_to(ROOT)} -> {target}")


def main() -> int:
    try:
        schemas, registry = schema_registry()
        check_refs(schemas)
        positive_count = check_examples(schemas, registry)
        negative_count = check_negative_examples(schemas, registry)
        check_docs()
    except Failure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "PASS: "
        f"{len(schemas)} schemas; "
        f"{positive_count} positive fixtures; "
        f"{negative_count} negative fixtures; "
        "bilingual mirrors and local links"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
