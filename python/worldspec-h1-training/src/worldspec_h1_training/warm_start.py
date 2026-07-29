"""Safe, digest-bound Orbax checkpoint materialization for policy warm starts."""

from __future__ import annotations

import json
import shutil
import stat
import zipfile
from pathlib import Path
from typing import Any

from .contract import digest_bytes
from .errors import TrainingError

_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
_MAX_MEMBER_COUNT = 10_000


def _safe_member_path(root: Path, name: str) -> Path:
    relative = Path(name)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise TrainingError(
            "WARM_START_ARCHIVE_UNSAFE",
            "Warm-start checkpoint contains an unsafe path.",
            {"path": name},
        )
    destination = (root / relative).resolve()
    if root != destination and root not in destination.parents:
        raise TrainingError(
            "WARM_START_ARCHIVE_UNSAFE",
            "Warm-start checkpoint escapes its extraction root.",
            {"path": name},
        )
    return destination


def materialize_warm_start(
    archive_path: Path,
    destination: Path,
    expected_digest: str,
    expected_size: int,
) -> tuple[Path, dict[str, Any]]:
    """Verify and extract an Orbax archive, returning its latest numeric step."""

    payload = archive_path.read_bytes()
    actual_digest = digest_bytes(payload)
    if len(payload) != expected_size or actual_digest != expected_digest:
        raise TrainingError(
            "WARM_START_ARCHIVE_MISMATCH",
            "Warm-start checkpoint does not match its declared size and digest.",
            {
                "expectedDigest": expected_digest,
                "actualDigest": actual_digest,
                "expectedSize": expected_size,
                "actualSize": len(payload),
            },
        )
    if len(payload) > _MAX_ARCHIVE_BYTES:
        raise TrainingError(
            "WARM_START_ARCHIVE_TOO_LARGE",
            "Warm-start checkpoint exceeds the extraction limit.",
            {"sizeBytes": len(payload), "limitBytes": _MAX_ARCHIVE_BYTES},
        )
    if destination.exists():
        if destination.is_symlink():
            raise TrainingError(
                "WARM_START_DESTINATION_INVALID",
                "Warm-start extraction destination cannot be a symlink.",
            )
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    destination = destination.resolve()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if not members or len(members) > _MAX_MEMBER_COUNT:
                raise TrainingError(
                    "WARM_START_ARCHIVE_INVALID",
                    "Warm-start checkpoint has an invalid member count.",
                    {"memberCount": len(members)},
                )
            seen: set[str] = set()
            total_uncompressed = 0
            for member in members:
                if member.filename in seen:
                    raise TrainingError(
                        "WARM_START_ARCHIVE_INVALID",
                        "Warm-start checkpoint contains duplicate paths.",
                        {"path": member.filename},
                    )
                seen.add(member.filename)
                file_type = (member.external_attr >> 16) & 0o170000
                if file_type == stat.S_IFLNK:
                    raise TrainingError(
                        "WARM_START_ARCHIVE_UNSAFE",
                        "Warm-start checkpoint cannot contain symbolic links.",
                        {"path": member.filename},
                    )
                total_uncompressed += member.file_size
                if total_uncompressed > _MAX_ARCHIVE_BYTES:
                    raise TrainingError(
                        "WARM_START_ARCHIVE_TOO_LARGE",
                        "Warm-start checkpoint expands beyond the extraction limit.",
                        {
                            "uncompressedBytes": total_uncompressed,
                            "limitBytes": _MAX_ARCHIVE_BYTES,
                        },
                    )
                target = _safe_member_path(destination, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if member.file_size <= 0:
                    raise TrainingError(
                        "WARM_START_ARCHIVE_INVALID",
                        "Warm-start checkpoint contains an empty file.",
                        {"path": member.filename},
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("xb") as sink:
                    shutil.copyfileobj(source, sink)
    except zipfile.BadZipFile as error:
        raise TrainingError(
            "WARM_START_ARCHIVE_INVALID",
            "Warm-start checkpoint is not a valid ZIP archive.",
        ) from error

    steps = sorted(
        (path for path in destination.iterdir() if path.is_dir() and path.name.isdigit()),
        key=lambda path: int(path.name),
    )
    if not steps:
        raise TrainingError(
            "WARM_START_STEP_MISSING",
            "Warm-start checkpoint has no numeric Orbax step directory.",
        )
    latest = steps[-1]
    config_path = latest / "ppo_network_config.json"
    metadata_path = latest / "_CHECKPOINT_METADATA"
    if not config_path.is_file() or not metadata_path.is_file():
        raise TrainingError(
            "WARM_START_STEP_INVALID",
            "Latest warm-start step lacks Orbax or PPO metadata.",
            {"step": latest.name},
        )
    try:
        network_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TrainingError(
            "WARM_START_NETWORK_CONFIG_INVALID",
            "Warm-start PPO network configuration is invalid.",
        ) from error
    return latest, {
        "archiveDigest": actual_digest,
        "archiveSizeBytes": len(payload),
        "selectedStep": int(latest.name),
        "networkConfig": network_config,
        "restored": {
            "normalizer": True,
            "policy": True,
            "value": True,
            "optimizer": False,
        },
        "optimizerState": "reset",
    }


def validate_network_compatibility(
    metadata: dict[str, Any],
    observation_size: int,
    action_size: int,
) -> None:
    """Reject warm starts produced by an incompatible observation/action ABI."""

    config = metadata.get("networkConfig", {})
    configured_action_size = config.get("action_size")
    configured_observation = config.get("observation_size", {})
    configured_state = configured_observation.get("state", {})
    configured_shape = configured_state.get("shape")
    if (
        configured_action_size != action_size
        or configured_shape != [observation_size]
        or config.get("normalize_observations") is not True
    ):
        raise TrainingError(
            "WARM_START_NETWORK_INCOMPATIBLE",
            "Warm-start observation/action ABI does not match the target environment.",
            {
                "expectedObservationSize": observation_size,
                "actualObservationShape": configured_shape,
                "expectedActionSize": action_size,
                "actualActionSize": configured_action_size,
                "normalizeObservations": config.get("normalize_observations"),
            },
        )
