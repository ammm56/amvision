"""conversion 任务的领域级删除服务。"""

from __future__ import annotations

from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.application.ports.queue import QueueBackend

from pathlib import PurePosixPath
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_TERMINAL_STATES = {
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    "canceled",
    "completed",
}


def delete_conversion_task_outputs(
    *, task: TaskRecord, session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage, queue_backend: QueueBackend | None = None,
) -> None:
    """删除转换输出、登记、全部尝试及队列，任何外部依赖阻止删除。"""
    _ensure_terminal_task(task)
    _resolve_conversion_output_prefix(task)
    ResourceDeletionService(session_factory=session_factory, dataset_storage=dataset_storage, queue_backend=queue_backend).delete(
        kind="task", resource_id=task.task_id, project_id=task.project_id,
    )


def _ensure_terminal_task(task: TaskRecord) -> None:
    """确保任务已进入可删除的终态。"""

    if task.state in _TERMINAL_STATES:
        return
    raise InvalidRequestError(
        "转换任务仍在运行或排队，不能删除",
        details={"task_id": task.task_id, "state": task.state},
    )


def _resolve_conversion_output_prefix(task: TaskRecord) -> str:
    """解析 conversion 任务运行目录前缀。"""

    result = dict(task.result)
    output_prefix = _read_optional_str(result, "output_object_prefix")
    if output_prefix is None:
        output_prefix = f"task-runs/conversion/{task.task_id}"
    normalized = PurePosixPath(output_prefix)
    expected = PurePosixPath("task-runs") / "conversion" / task.task_id
    if normalized != expected:
        raise InvalidRequestError(
            "转换任务运行目录不在允许删除的范围内",
            details={"task_id": task.task_id, "output_object_prefix": output_prefix},
        )
    return normalized.as_posix()


def _collect_model_build_ids(task: TaskRecord) -> set[str]:
    """从任务结果中收集本次 conversion 登记的 ModelBuild id。"""

    result = dict(task.result)
    build_ids: set[str] = set()
    raw_builds = result.get("builds")
    if isinstance(raw_builds, list):
        for item in raw_builds:
            if not isinstance(item, dict):
                continue
            build_id = _read_optional_str(item, "model_build_id")
            if build_id is not None:
                build_ids.add(build_id)
    direct_build_id = _read_optional_str(result, "model_build_id")
    if direct_build_id is not None:
        build_ids.add(direct_build_id)
    return build_ids


def _collect_protected_builds(
    *,
    unit_of_work: SqlAlchemyUnitOfWork,
    task: TaskRecord,
    build_ids: set[str],
) -> list[dict[str, object]]:
    """收集仍被部署实例引用的 build。"""

    if not build_ids:
        return []
    deployment_instances = unit_of_work.deployments.list_deployment_instances(task.project_id)
    protected_builds: list[dict[str, object]] = []
    for build_id in sorted(build_ids):
        referencing_instances = [
            deployment.deployment_instance_id
            for deployment in deployment_instances
            if deployment.model_build_id == build_id
        ]
        if referencing_instances:
            protected_builds.append(
                {
                    "model_build_id": build_id,
                    "deployment_instance_ids": referencing_instances,
                }
            )
    return protected_builds


def _collect_build_file_ids(
    *,
    unit_of_work: SqlAlchemyUnitOfWork,
    build_ids: set[str],
) -> set[str]:
    """收集 build 关联的 ModelFile id。"""

    file_ids: set[str] = set()
    for build_id in build_ids:
        build = unit_of_work.models.get_model_build(build_id)
        if build is not None:
            file_ids.update(build.file_ids)
        for model_file in unit_of_work.model_files.list_model_files(model_build_id=build_id):
            file_ids.add(model_file.file_id)
    return {file_id for file_id in file_ids if file_id.strip()}


def _read_optional_str(payload: dict[str, Any], key: str) -> str | None:
    """从字典中读取可选非空字符串。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
