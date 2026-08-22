"""Conversion 文件发布与数据库登记之间的可恢复状态记录。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from backend.service.application.backends import (
    ConversionBackendOutput,
    ConversionBackendRunResult,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class ConversionPublicationSnapshot:
    """描述一次已经原子发布、可继续完成数据库登记的 conversion。"""

    publication_object_key: str
    state: str
    run_result: ConversionBackendRunResult
    model_build_ids: tuple[str, ...] = ()


def write_conversion_publication_state(
    *,
    dataset_storage: LocalDatasetStorage,
    publication_object_key: str,
    state: str,
    payload: dict[str, object] | None = None,
) -> None:
    """原子更新 attempt publication 记录，不修改已发布模型产物。"""

    existing: dict[str, Any] = {}
    publication_path = dataset_storage.resolve(publication_object_key)
    if publication_path.is_file():
        raw_existing = dataset_storage.read_json(publication_object_key)
        if isinstance(raw_existing, dict):
            existing.update(raw_existing)
    now = datetime.now(timezone.utc).isoformat()
    dataset_storage.write_json(
        publication_object_key,
        {
            **existing,
            **dict(payload or {}),
            "state": state,
            "created_at": existing.get("created_at", now),
            "updated_at": now,
        },
    )


def mark_conversion_publication_registered(
    *,
    dataset_storage: LocalDatasetStorage,
    conversion_metadata: dict[str, object],
    model_build_ids: tuple[str, ...],
) -> bool:
    """在 ModelBuild 批次提交后把 publication 记录标记为已登记。"""

    publication_object_key = conversion_metadata.get(
        "publication_record_object_key"
    )
    if not isinstance(publication_object_key, str) or not publication_object_key.strip():
        return False
    try:
        write_conversion_publication_state(
            dataset_storage=dataset_storage,
            publication_object_key=publication_object_key,
            state="registered",
            payload={
                "model_build_ids": list(model_build_ids),
                "conversion_metadata": dict(conversion_metadata),
            },
        )
    except (OSError, ValueError):
        return False
    return True


def serialize_conversion_run_result(
    run_result: ConversionBackendRunResult,
) -> dict[str, object]:
    """把已验证并映射到最终目录的 conversion 结果写入 publication。"""

    return {
        "conversion_task_id": run_result.conversion_task_id,
        "outputs": [
            {
                "target_format": output.target_format,
                "object_uri": output.object_uri,
                "file_type": output.file_type,
                "runtime_backend": output.runtime_backend,
                "runtime_precision": output.runtime_precision,
                "metadata": dict(output.metadata),
            }
            for output in run_result.outputs
        ],
        "metadata": dict(run_result.metadata),
    }


def deserialize_conversion_run_result(
    payload: object,
    *,
    expected_task_id: str,
    expected_output_prefix: str,
) -> ConversionBackendRunResult:
    """严格读取 publication 中可用于崩溃恢复的 conversion 结果。"""

    if not isinstance(payload, dict):
        raise ServiceConfigurationError("conversion publication 缺少 run_result")
    task_id = payload.get("conversion_task_id")
    raw_outputs = payload.get("outputs")
    raw_metadata = payload.get("metadata")
    if task_id != expected_task_id or not isinstance(raw_outputs, list):
        raise ServiceConfigurationError(
            "conversion publication 的任务或输出无效",
            details={"expected_task_id": expected_task_id, "actual_task_id": task_id},
        )
    if not isinstance(raw_metadata, dict):
        raise ServiceConfigurationError("conversion publication metadata 无效")

    final_builds_prefix = f"{expected_output_prefix}/artifacts/builds"
    outputs: list[ConversionBackendOutput] = []
    for raw_output in raw_outputs:
        if not isinstance(raw_output, dict):
            raise ServiceConfigurationError("conversion publication output 无效")
        values = {
            key: raw_output.get(key)
            for key in (
                "target_format",
                "object_uri",
                "file_type",
                "runtime_backend",
                "runtime_precision",
            )
        }
        if not all(isinstance(value, str) and value.strip() for value in values.values()):
            raise ServiceConfigurationError("conversion publication output 字段无效")
        object_uri = str(values["object_uri"])
        object_path = PurePosixPath(object_uri)
        builds_path = PurePosixPath(final_builds_prefix)
        if object_path != builds_path and builds_path not in object_path.parents:
            raise ServiceConfigurationError(
                "conversion publication output 超出最终 builds 目录",
                details={"object_uri": object_uri},
            )
        output_metadata = raw_output.get("metadata")
        if not isinstance(output_metadata, dict):
            raise ServiceConfigurationError("conversion publication output metadata 无效")
        outputs.append(
            ConversionBackendOutput(
                target_format=str(values["target_format"]),
                object_uri=object_uri,
                file_type=str(values["file_type"]),
                runtime_backend=str(values["runtime_backend"]),
                runtime_precision=str(values["runtime_precision"]),
                metadata=dict(output_metadata),
            )
        )
    if not outputs:
        raise ServiceConfigurationError("conversion publication outputs 不能为空")
    return ConversionBackendRunResult(
        conversion_task_id=expected_task_id,
        outputs=tuple(outputs),
        metadata=dict(raw_metadata),
    )


def find_recoverable_conversion_publication(
    *,
    dataset_storage: LocalDatasetStorage,
    task_id: str,
    output_object_prefix: str,
) -> ConversionPublicationSnapshot | None:
    """查找当前任务已经发布到最终目录的最新 publication。"""

    expected_prefix = f"task-runs/conversion/{task_id}"
    if output_object_prefix != expected_prefix:
        raise ServiceConfigurationError(
            "conversion 恢复目录与任务不匹配",
            details={"task_id": task_id, "output_object_prefix": output_object_prefix},
        )
    attempts_root = dataset_storage.resolve(f"{expected_prefix}/attempts")
    final_builds_path = dataset_storage.resolve(
        f"{expected_prefix}/artifacts/builds"
    )
    if not attempts_root.is_dir() or not final_builds_path.is_dir():
        return None

    marker_paths = sorted(
        attempts_root.glob("*/publication.json"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for marker_path in marker_paths:
        attempt_id = marker_path.parent.name
        publication_object_key = (
            f"{expected_prefix}/attempts/{attempt_id}/publication.json"
        )
        payload = dataset_storage.read_json(publication_object_key)
        if not isinstance(payload, dict):
            raise ServiceConfigurationError("conversion publication JSON 无效")
        if (
            payload.get("conversion_task_id") != task_id
            or payload.get("conversion_attempt_id") != attempt_id
            or payload.get("final_builds_object_key")
            != f"{expected_prefix}/artifacts/builds"
        ):
            raise ServiceConfigurationError(
                "conversion publication 归属信息无效",
                details={"publication_object_key": publication_object_key},
            )
        state = payload.get("state")
        if state not in {
            "publishing",
            "published_pending_registration",
            "registered",
        }:
            continue
        run_result = deserialize_conversion_run_result(
            payload.get("run_result"),
            expected_task_id=task_id,
            expected_output_prefix=expected_prefix,
        )
        for output in run_result.outputs:
            output_path = dataset_storage.resolve(output.object_uri)
            if not output_path.is_file() or output_path.stat().st_size <= 0:
                raise ServiceConfigurationError(
                    "conversion publication 引用的最终产物不存在",
                    details={"object_uri": output.object_uri},
                )
        raw_model_build_ids = payload.get("model_build_ids", [])
        if not isinstance(raw_model_build_ids, list) or not all(
            isinstance(item, str) and item.strip() for item in raw_model_build_ids
        ):
            raise ServiceConfigurationError(
                "conversion publication 的 model_build_ids 无效"
            )
        return ConversionPublicationSnapshot(
            publication_object_key=publication_object_key,
            state=str(state),
            run_result=replace(
                run_result,
                metadata={
                    **run_result.metadata,
                    "publication_record_object_key": publication_object_key,
                },
            ),
            model_build_ids=tuple(raw_model_build_ids),
        )
    return None


__all__ = [
    "ConversionPublicationSnapshot",
    "deserialize_conversion_run_result",
    "find_recoverable_conversion_publication",
    "mark_conversion_publication_registered",
    "serialize_conversion_run_result",
    "write_conversion_publication_state",
]
