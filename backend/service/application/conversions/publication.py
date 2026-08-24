"""Conversion 文件发布与数据库登记之间的可恢复状态记录。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import os
from pathlib import PurePosixPath
import shutil
from collections.abc import Callable
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
    """描述数据库 fence 对应的唯一 conversion publication。"""

    publication_object_key: str
    state: str
    run_result: ConversionBackendRunResult
    conversion_attempt_id: str
    publication_token: str | None
    staging_prefix: str
    final_builds_object_key: str
    files_published: bool
    model_build_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedConversionPublication:
    """描述已验证但尚未跨过原子 rename 的 staging 产物。"""

    conversion_task_id: str
    conversion_attempt_id: str
    publication_token: str
    publication_object_key: str
    staging_prefix: str
    final_builds_object_key: str
    run_result: ConversionBackendRunResult


def persist_prepared_conversion_publication(
    *,
    dataset_storage: LocalDatasetStorage,
    run_result: ConversionBackendRunResult,
    progress_check: Callable[[], None] | None = None,
) -> str:
    """在取得 DB reservation 前持久化有界结果描述和产物摘要。"""

    identity = _validate_publication_identity(run_result)
    staged_builds_path = dataset_storage.resolve(identity["staged_builds_key"])
    final_builds_path = dataset_storage.resolve(identity["final_builds_key"])
    if not staged_builds_path.is_dir():
        raise ServiceConfigurationError(
            "conversion staging builds 目录不存在",
            details={"staged_builds_key": identity["staged_builds_key"]},
        )
    if final_builds_path.exists():
        raise ServiceConfigurationError(
            "conversion 最终 builds 已存在，拒绝覆盖不可变产物",
            details={"final_builds_object_key": identity["final_builds_key"]},
        )
    artifact_descriptors = _build_artifact_descriptors(
        dataset_storage=dataset_storage,
        run_result=run_result,
        staging_prefix=identity["staging_prefix"],
        final_builds_key=identity["final_builds_key"],
        progress_check=progress_check,
    )
    write_conversion_publication_state(
        dataset_storage=dataset_storage,
        publication_object_key=identity["marker_key"],
        state="prepared",
        payload={
            "conversion_task_id": run_result.conversion_task_id,
            "conversion_attempt_id": identity["attempt_id"],
            "staging_prefix": identity["staging_prefix"],
            "final_builds_object_key": identity["final_builds_key"],
            "target_formats": [
                output.target_format for output in run_result.outputs
            ],
            "artifact_descriptors": artifact_descriptors,
            "run_result": serialize_conversion_run_result(run_result),
        },
    )
    return identity["marker_key"]


def publish_prepared_conversion(
    *,
    dataset_storage: LocalDatasetStorage,
    run_result: ConversionBackendRunResult,
    publication_token: str,
    pre_rename_check: Callable[[], None],
    hash_progress_check: Callable[[], None] | None = None,
) -> PreparedConversionPublication:
    """在数据库 reservation 已取得后写 marker 并原子发布 staging。"""

    identity = _validate_publication_identity(run_result)
    attempt_id = identity["attempt_id"]
    marker_key = identity["marker_key"]
    staging_prefix = identity["staging_prefix"]
    final_builds_key = identity["final_builds_key"]
    token = publication_token.strip()
    if not token or len(token) > 64:
        raise ServiceConfigurationError("conversion publication token 无效")

    staged_builds_key = identity["staged_builds_key"]
    staged_builds_path = dataset_storage.resolve(staged_builds_key)
    final_builds_path = dataset_storage.resolve(final_builds_key)
    if not staged_builds_path.is_dir():
        raise ServiceConfigurationError(
            "conversion staging builds 目录不存在",
            details={"staged_builds_key": staged_builds_key},
        )
    if final_builds_path.exists():
        raise ServiceConfigurationError(
            "conversion 最终 builds 已存在，拒绝覆盖不可变产物",
            details={"final_builds_object_key": final_builds_key},
        )
    prepared_payload = _read_and_validate_publication_marker(
        dataset_storage=dataset_storage,
        publication_object_key=marker_key,
        task_id=run_result.conversion_task_id,
        attempt_id=attempt_id,
        expected_token=token,
        allowed_states={"prepared", "publishing"},
        allow_prepared_without_token=True,
    )
    _verify_artifact_descriptors(
        dataset_storage=dataset_storage,
        payload=prepared_payload,
        use_final_paths=False,
        progress_check=hash_progress_check,
    )
    write_conversion_publication_state(
        dataset_storage=dataset_storage,
        publication_object_key=marker_key,
        state="publishing",
        payload={"publication_token": token},
    )
    pre_rename_check()
    final_builds_path.parent.mkdir(parents=True, exist_ok=True)
    os.rename(staged_builds_path, final_builds_path)
    try:
        write_conversion_publication_state(
            dataset_storage=dataset_storage,
            publication_object_key=marker_key,
            state="published_pending_registration",
            payload={
                "published_object_uris": [
                    output.object_uri for output in run_result.outputs
                ],
            },
        )
    except (OSError, ValueError):
        # 数据库 reservation 才是权威状态；rename 已完成后 marker 可由 recovery 修复。
        pass
    return PreparedConversionPublication(
        conversion_task_id=run_result.conversion_task_id,
        conversion_attempt_id=attempt_id,
        publication_token=token,
        publication_object_key=marker_key,
        staging_prefix=staging_prefix,
        final_builds_object_key=final_builds_key,
        run_result=run_result,
    )


def prepare_conversion_publication_result(
    *,
    raw_run_result: ConversionBackendRunResult,
    conversion_task_id: str,
    conversion_attempt_id: str,
    staging_prefix: str,
    final_output_prefix: str,
) -> ConversionBackendRunResult:
    """把 backend 的 staging 结果映射为尚未发布的最终结果描述。"""

    if raw_run_result.conversion_task_id != conversion_task_id:
        raise ServiceConfigurationError("conversion backend 返回了其他 Task 的结果")
    expected_staging_prefix = (
        f"task-runs/conversion/{conversion_task_id}/attempts/"
        f"{conversion_attempt_id}/staging"
    )
    if staging_prefix != expected_staging_prefix:
        raise ServiceConfigurationError("conversion staging identity 无效")
    expected_final_prefix = f"task-runs/conversion/{conversion_task_id}"
    if final_output_prefix != expected_final_prefix:
        raise ServiceConfigurationError("conversion final output identity 无效")
    if not raw_run_result.outputs:
        raise ServiceConfigurationError("conversion backend 没有返回输出")
    remapped_outputs: list[ConversionBackendOutput] = []
    for output in raw_run_result.outputs:
        staged_path = PurePosixPath(output.object_uri)
        staging_path = PurePosixPath(staging_prefix)
        if staged_path != staging_path and staging_path not in staged_path.parents:
            raise ServiceConfigurationError(
                "conversion backend 输出超出 Attempt staging",
                details={"object_uri": output.object_uri},
            )
        remapped_outputs.append(
            replace(
                output,
                object_uri=_remap_object_prefix(
                    output.object_uri,
                    source_prefix=staging_prefix,
                    target_prefix=final_output_prefix,
                ),
                metadata=_remap_metadata_object_paths(
                    output.metadata,
                    source_prefix=staging_prefix,
                    target_prefix=final_output_prefix,
                ),
            )
        )
    attempt_prefix = staging_prefix.removesuffix("/staging")
    return replace(
        raw_run_result,
        outputs=tuple(remapped_outputs),
        metadata={
            **_remap_metadata_object_paths(
                raw_run_result.metadata,
                source_prefix=staging_prefix,
                target_prefix=final_output_prefix,
            ),
            "conversion_attempt_id": conversion_attempt_id,
            "publication_record_object_key": f"{attempt_prefix}/publication.json",
            "publication_staging_prefix": staging_prefix,
            "publication_final_builds_object_key": (
                f"{final_output_prefix}/artifacts/builds"
            ),
            "publication_protocol": "conversion-publication.v1",
        },
    )


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


def cleanup_aborted_conversion_staging(
    *,
    dataset_storage: LocalDatasetStorage,
    task_id: str,
    conversion_attempt_id: str,
    publication_token: str,
) -> None:
    """仅在最终目录不存在时标记 aborted 并回收当前 Attempt staging。"""

    output_prefix = f"task-runs/conversion/{task_id}"
    final_builds_path = dataset_storage.resolve(
        f"{output_prefix}/artifacts/builds"
    )
    if final_builds_path.exists():
        raise ServiceConfigurationError(
            "conversion 最终目录已存在，禁止按 aborted 清理",
            details={"task_id": task_id},
        )
    marker_key = (
        f"{output_prefix}/attempts/{conversion_attempt_id}/publication.json"
    )
    marker_path = dataset_storage.resolve(marker_key)
    if marker_path.is_file():
        try:
            write_conversion_publication_state(
                dataset_storage=dataset_storage,
                publication_object_key=marker_key,
                state="aborted",
                payload={"publication_token": publication_token},
            )
        except (OSError, ValueError):
            # DB aborted 是权威状态；marker 失败不阻止安全回收未发布 staging。
            pass
    staging_path = dataset_storage.resolve(
        f"{output_prefix}/attempts/{conversion_attempt_id}/staging"
    )
    if staging_path.is_dir():
        shutil.rmtree(staging_path)


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
    conversion_attempt_id: str,
    output_object_prefix: str,
    publication_state: str | None,
    publication_token: str | None,
) -> ConversionPublicationSnapshot | None:
    """只读取数据库当前 Attempt/token 对应的 publication。"""

    expected_prefix = f"task-runs/conversion/{task_id}"
    if output_object_prefix != expected_prefix:
        raise ServiceConfigurationError(
            "conversion 恢复目录与任务不匹配",
            details={"task_id": task_id, "output_object_prefix": output_object_prefix},
        )
    if not conversion_attempt_id.strip():
        raise ServiceConfigurationError("conversion recovery Attempt id 不能为空")
    if publication_state not in {None, "reserved", "published", "registered"}:
        return None
    if publication_state is None and publication_token is not None:
        raise ServiceConfigurationError("conversion recovery token/state 不一致")
    if publication_state is not None and (
        not isinstance(publication_token, str) or not publication_token.strip()
    ):
        raise ServiceConfigurationError("conversion recovery 缺少 DB publication token")
    final_builds_path = dataset_storage.resolve(
        f"{expected_prefix}/artifacts/builds"
    )
    publication_object_key = (
        f"{expected_prefix}/attempts/{conversion_attempt_id}/publication.json"
    )
    publication_path = dataset_storage.resolve(publication_object_key)
    if not publication_path.is_file():
        return None
    expected_token = publication_token if publication_state is not None else None
    allowed_marker_states = (
        {"prepared"}
        if publication_state is None
        else {
            "prepared",
            "publishing",
            "published_pending_registration",
            "registered",
        }
    )
    payload = _read_and_validate_publication_marker(
        dataset_storage=dataset_storage,
        publication_object_key=publication_object_key,
        task_id=task_id,
        attempt_id=conversion_attempt_id,
        expected_token=expected_token,
        allowed_states=allowed_marker_states,
        allow_prepared_without_token=publication_state == "reserved",
    )
    files_published = final_builds_path.is_dir()
    if files_published:
        _verify_artifact_descriptors(
            dataset_storage=dataset_storage,
            payload=payload,
            use_final_paths=True,
        )
    elif publication_state in {"published", "registered"}:
        raise ServiceConfigurationError(
            "conversion DB 已发布但最终 builds 目录不存在",
            details={"task_id": task_id, "publication_state": publication_state},
        )
    run_result = deserialize_conversion_run_result(
        payload.get("run_result"),
        expected_task_id=task_id,
        expected_output_prefix=expected_prefix,
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
        state=str(payload["state"]),
        run_result=replace(
            run_result,
            metadata={
                **run_result.metadata,
                "publication_record_object_key": publication_object_key,
            },
        ),
        conversion_attempt_id=conversion_attempt_id,
        publication_token=(
            publication_token.strip()
            if isinstance(publication_token, str)
            else None
        ),
        staging_prefix=str(payload["staging_prefix"]),
        final_builds_object_key=str(payload["final_builds_object_key"]),
        files_published=files_published,
        model_build_ids=tuple(raw_model_build_ids),
    )


def _validate_publication_identity(
    run_result: ConversionBackendRunResult,
) -> dict[str, str]:
    """核验 run result 中由应用层建立的 publication 身份。"""

    metadata = run_result.metadata
    if metadata.get("publication_protocol") != "conversion-publication.v1":
        raise ServiceConfigurationError("conversion result 缺少 publication protocol")
    attempt_id = _require_metadata_string(metadata, "conversion_attempt_id")
    marker_key = _require_metadata_string(
        metadata,
        "publication_record_object_key",
    )
    staging_prefix = _require_metadata_string(metadata, "publication_staging_prefix")
    final_builds_key = _require_metadata_string(
        metadata,
        "publication_final_builds_object_key",
    )
    expected_prefix = f"task-runs/conversion/{run_result.conversion_task_id}"
    if final_builds_key != f"{expected_prefix}/artifacts/builds":
        raise ServiceConfigurationError("conversion publication 最终目录与 Task 不匹配")
    if staging_prefix != f"{expected_prefix}/attempts/{attempt_id}/staging":
        raise ServiceConfigurationError("conversion publication staging 归属无效")
    if marker_key != f"{expected_prefix}/attempts/{attempt_id}/publication.json":
        raise ServiceConfigurationError("conversion publication marker 归属无效")
    return {
        "attempt_id": attempt_id,
        "marker_key": marker_key,
        "staging_prefix": staging_prefix,
        "staged_builds_key": f"{staging_prefix}/artifacts/builds",
        "final_builds_key": final_builds_key,
    }


def _build_artifact_descriptors(
    *,
    dataset_storage: LocalDatasetStorage,
    run_result: ConversionBackendRunResult,
    staging_prefix: str,
    final_builds_key: str,
    progress_check: Callable[[], None] | None,
) -> list[dict[str, object]]:
    """为 publication 涉及的所有 builds 文件生成不可变摘要。"""

    final_paths: set[str] = {output.object_uri for output in run_result.outputs}
    for output in run_result.outputs:
        _collect_final_build_paths(
            output.metadata,
            final_builds_key=final_builds_key,
            result=final_paths,
        )
    descriptors: list[dict[str, object]] = []
    for final_object_key in sorted(final_paths):
        staged_object_key = _remap_object_prefix(
            final_object_key,
            source_prefix=final_builds_key.removesuffix("/artifacts/builds"),
            target_prefix=staging_prefix,
        )
        staged_path = dataset_storage.resolve(staged_object_key)
        if not staged_path.is_file() or staged_path.stat().st_size <= 0:
            raise ServiceConfigurationError(
                "conversion staging 产物不完整",
                details={"object_uri": staged_object_key},
            )
        descriptors.append(
            {
                "object_uri": final_object_key,
                "staged_object_uri": staged_object_key,
                "size_bytes": staged_path.stat().st_size,
                "sha256": _sha256_file(
                    staged_path,
                    progress_check=progress_check,
                ),
            }
        )
    return descriptors


def _collect_final_build_paths(
    value: Any,
    *,
    final_builds_key: str,
    result: set[str],
) -> None:
    """递归收集 metadata 中位于最终 builds 目录的文件引用。"""

    if isinstance(value, str):
        value_path = PurePosixPath(value)
        builds_path = PurePosixPath(final_builds_key)
        if value_path != builds_path and builds_path in value_path.parents:
            result.add(value)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_final_build_paths(
                item,
                final_builds_key=final_builds_key,
                result=result,
            )
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_final_build_paths(
                item,
                final_builds_key=final_builds_key,
                result=result,
            )


def _read_and_validate_publication_marker(
    *,
    dataset_storage: LocalDatasetStorage,
    publication_object_key: str,
    task_id: str,
    attempt_id: str,
    expected_token: str | None,
    allowed_states: set[str],
    allow_prepared_without_token: bool = False,
) -> dict[str, Any]:
    """读取并严格核验唯一 Attempt publication marker。"""

    payload = dataset_storage.read_json(publication_object_key)
    expected_prefix = f"task-runs/conversion/{task_id}"
    if not isinstance(payload, dict):
        raise ServiceConfigurationError("conversion publication JSON 无效")
    if (
        payload.get("conversion_task_id") != task_id
        or payload.get("conversion_attempt_id") != attempt_id
        or payload.get("staging_prefix")
        != f"{expected_prefix}/attempts/{attempt_id}/staging"
        or payload.get("final_builds_object_key")
        != f"{expected_prefix}/artifacts/builds"
        or payload.get("state") not in allowed_states
    ):
        raise ServiceConfigurationError(
            "conversion publication 归属或状态无效",
            details={"publication_object_key": publication_object_key},
        )
    actual_token = payload.get("publication_token")
    if expected_token is not None and actual_token != expected_token:
        if not (allow_prepared_without_token and payload.get("state") == "prepared"):
            raise ServiceConfigurationError("conversion publication token 不匹配")
    return payload


def _verify_artifact_descriptors(
    *,
    dataset_storage: LocalDatasetStorage,
    payload: dict[str, Any],
    use_final_paths: bool,
    progress_check: Callable[[], None] | None = None,
) -> None:
    """验证 publication 产物的大小与 SHA-256。"""

    descriptors = payload.get("artifact_descriptors")
    if not isinstance(descriptors, list) or not descriptors:
        raise ServiceConfigurationError("conversion publication 缺少产物摘要")
    key_name = "object_uri" if use_final_paths else "staged_object_uri"
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            raise ServiceConfigurationError("conversion publication 产物摘要无效")
        object_key = descriptor.get(key_name)
        size_bytes = descriptor.get("size_bytes")
        sha256 = descriptor.get("sha256")
        if (
            not isinstance(object_key, str)
            or isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes <= 0
            or not isinstance(sha256, str)
            or len(sha256) != 64
        ):
            raise ServiceConfigurationError("conversion publication 产物摘要字段无效")
        artifact_path = dataset_storage.resolve(object_key)
        if (
            not artifact_path.is_file()
            or artifact_path.stat().st_size != size_bytes
            or _sha256_file(
                artifact_path,
                progress_check=progress_check,
            )
            != sha256
        ):
            raise ServiceConfigurationError(
                "conversion publication 产物摘要校验失败",
                details={"object_uri": object_key},
            )


def _sha256_file(
    path,
    *,
    progress_check: Callable[[], None] | None = None,
) -> str:
    """流式计算文件 SHA-256，避免大模型文件进入内存。"""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if progress_check is not None:
                progress_check()
            digest.update(chunk)
    return digest.hexdigest()


def _require_metadata_string(
    metadata: dict[str, object],
    field_name: str,
) -> str:
    """读取 runner 固化的 publication metadata 字符串。"""

    value = metadata.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ServiceConfigurationError(
            "conversion result publication metadata 不完整",
            details={"field_name": field_name},
        )
    return value.strip()


def _remap_object_prefix(
    value: str,
    *,
    source_prefix: str,
    target_prefix: str,
) -> str:
    """把 staging object key 映射到最终发布前缀。"""

    if value == source_prefix:
        return target_prefix
    marker = f"{source_prefix}/"
    if value.startswith(marker):
        return f"{target_prefix}/{value[len(marker):]}"
    return value


def _remap_metadata_object_paths(
    value: Any,
    *,
    source_prefix: str,
    target_prefix: str,
) -> Any:
    """递归映射 metadata 内的 object key。"""

    if isinstance(value, str):
        return _remap_object_prefix(
            value,
            source_prefix=source_prefix,
            target_prefix=target_prefix,
        )
    if isinstance(value, dict):
        return {
            key: _remap_metadata_object_paths(
                item,
                source_prefix=source_prefix,
                target_prefix=target_prefix,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _remap_metadata_object_paths(
                item,
                source_prefix=source_prefix,
                target_prefix=target_prefix,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _remap_metadata_object_paths(
                item,
                source_prefix=source_prefix,
                target_prefix=target_prefix,
            )
            for item in value
        )
    return value


__all__ = [
    "ConversionPublicationSnapshot",
    "PreparedConversionPublication",
    "cleanup_aborted_conversion_staging",
    "deserialize_conversion_run_result",
    "find_recoverable_conversion_publication",
    "mark_conversion_publication_registered",
    "persist_prepared_conversion_publication",
    "prepare_conversion_publication_result",
    "publish_prepared_conversion",
    "serialize_conversion_run_result",
    "write_conversion_publication_state",
]
