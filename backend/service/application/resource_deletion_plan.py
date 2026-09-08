"""按真实资源归属生成删除清单，不从任意字符串推断磁盘路径。"""

from __future__ import annotations

from pathlib import PurePosixPath

from backend.service.application.errors import (
    InvalidRequestError,
    ResourceInUseError,
    ResourceNotFoundError,
)
from backend.service.application.ports.queue import normalize_queue_path_component
from backend.service.domain.resource_deletion import (
    ResourceDeletionPlan,
    ResourceRef,
    StorageDeletionTarget,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


ID_FIELDS = {
    "imported-artifact": "artifact_id",
    "task": "task_id",
    "dataset-import": "dataset_import_id",
    "dataset-export": "dataset_export_id",
    "dataset-version": "dataset_version_id",
    "model-version": "model_version_id",
    "model-build": "model_build_id",
    "model-file": "file_id",
    "model": "model_id",
    "deployment": "deployment_instance_id",
    "outbox": "message_id",
}
REFERENCE_FIELDS = {
    "task_id",
    "parent_task_id",
    "training_task_id",
    "conversion_task_id",
    "dataset_import_id",
    "dataset_export_id",
    "dataset_version_id",
    "model_version_id",
    "source_model_version_id",
    "parent_version_id",
    "warm_start_model_version_id",
    "model_build_id",
    "deployment_instance_id",
    "file_id",
    "checkpoint_file_id",
    "labels_file_id",
    "metrics_file_id",
}
TERMINAL_TASK_STATES = {
    "succeeded",
    "completed",
    "failed",
    "cancelled",
    "canceled",
    "timed_out",
    "paused",
}


def referenced_ids(payload: object) -> set[str]:
    """仅枚举已知结构化引用字段；不匹配说明文字、任意路径或普通字符串。"""
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"import_provenance", "provenance_json"}:
                continue
            if key in REFERENCE_FIELDS and isinstance(value, str) and value:
                found.add(value)
            elif key in {"file_ids_json", "file_ids"} and isinstance(value, list):
                found.update(item for item in value if isinstance(item, str))
            elif isinstance(value, (dict, list)):
                found.update(referenced_ids(value))
    elif isinstance(payload, list):
        for value in payload:
            found.update(referenced_ids(value))
    return found


def include_orphan_dataset_directory(
    inventory: dict[str, list[dict]],
    *,
    project_id: str,
    dataset_id: str,
    kind: str,
    resource_id: str,
) -> None:
    """维护入口只接纳缺少主记录且无结构化引用的标准数据集目录。"""
    if kind not in {"dataset-import", "dataset-export", "dataset-version"}:
        raise InvalidRequestError("无主目录清理仅支持数据集导入、导出和版本")
    normalize_queue_path_component(dataset_id, field_name="dataset_id")
    if any(row[ID_FIELDS[kind]] == resource_id for row in inventory[kind]):
        raise ResourceInUseError("资源主记录仍存在，应使用正常删除入口")
    for row_kind, rows in inventory.items():
        for row in rows:
            if resource_id in referenced_ids(row):
                raise ResourceInUseError(
                    "无主目录仍被资源引用", details={"resource_kind": row_kind}
                )
    inventory[kind].append(
        {
            ID_FIELDS[kind]: resource_id,
            "project_id": project_id,
            "dataset_id": dataset_id,
            "status": "failed",
        }
    )


def build_resource_deletion_plan(
    *,
    inventory: dict[str, list[dict]],
    storage: LocalDatasetStorage,
    project_id: str,
    kind: str,
    resource_id: str,
    operation_id: str,
) -> ResourceDeletionPlan:
    """闭包包含所属产物，外部依赖在修改文件和数据库前阻止删除。"""
    for value in (project_id, resource_id, operation_id):
        normalize_queue_path_component(value, field_name="resource_id")
    selected: dict[tuple[str, str], dict] = {}

    def add(resource_kind: str, row: dict) -> None:
        """把聚合根加入去重清单。"""
        selected[resource_kind, str(row[ID_FIELDS[resource_kind]])] = row

    if kind == "dataset":
        for item_kind in ("dataset-version", "dataset-import", "dataset-export"):
            for row in inventory[item_kind]:
                if (
                    row.get("project_id") == project_id
                    and row.get("dataset_id") == resource_id
                ):
                    add(item_kind, row)
        if (
            not selected
            and not storage.resolve(
                f"projects/{project_id}/datasets/{resource_id}"
            ).is_dir()
        ):
            raise ResourceNotFoundError("找不到指定数据集")
    elif kind in ID_FIELDS and kind not in {"outbox", "model-file", "model"}:
        row = next(
            (row for row in inventory[kind] if row[ID_FIELDS[kind]] == resource_id),
            None,
        )
        if row is None:
            raise ResourceNotFoundError(
                "找不到指定资源", details={"resource_id": resource_id}
            )
        owner_project = row.get("project_id")
        if kind in {"model-version", "model-build"}:
            owner_project = next(
                (
                    item.get("project_id")
                    for item in inventory["model"]
                    if item["model_id"] == row["model_id"]
                ),
                None,
            )
        if owner_project != project_id:
            raise ResourceNotFoundError("找不到当前 Project 的指定资源")
        add(kind, row)
    else:
        raise InvalidRequestError("不支持此类资源删除")

    if kind == "deployment":
        # 可选回收只尝试此实例的导入产物；共享模型保留，不阻止删除实例。
        from copy import deepcopy
        reduced = deepcopy(inventory)
        reduced["deployment"] = [r for r in reduced["deployment"] if r["deployment_instance_id"] != resource_id]
        instance = selected["deployment", resource_id]
        for candidate_kind, field in (("model-build", "model_build_id"), ("model-version", "model_version_id")):
            candidate_id = instance.get(field)
            if not candidate_id or not any(r.get(field) == candidate_id and r.get("project_id") == project_id for r in reduced.get("imported-artifact", [])):
                continue
            try:
                candidate = build_resource_deletion_plan(inventory=reduced, storage=storage, project_id=project_id, kind=candidate_kind, resource_id=candidate_id, operation_id=operation_id)
            except ResourceInUseError:
                continue
            for ref in candidate.records:
                row = next((r for r in reduced.get(ref.kind, []) if r[ID_FIELDS[ref.kind]] == ref.resource_id), None)
                if row is not None:
                    add(ref.kind, row)
                    reduced[ref.kind].remove(row)

    # 只扩展所有权关系，不递归删除引用这些产物的业务对象。
    changed = True
    while changed:
        before = len(selected)
        version_ids = {rid for (rk, rid) in selected if rk == "dataset-version"}
        task_ids = {rid for (rk, rid) in selected if rk == "task"}
        for rk in ("dataset-import", "dataset-export"):
            for row in inventory[rk]:
                owner_task = row.get("task_id") or (row.get("metadata_json") or {}).get(
                    "task_id"
                )
                if (
                    row.get("dataset_version_id") in version_ids
                    or owner_task in task_ids
                ):
                    add(rk, row)
        linked_tasks = {
            row.get("task_id") or (row.get("metadata_json") or {}).get("task_id")
            for (rk, _rid), row in selected.items()
            if rk in {"dataset-import", "dataset-export"}
        }
        for row in inventory["task"]:
            if row["task_id"] in linked_tasks:
                add("task", row)
        for row in inventory["model-version"]:
            if row.get("training_task_id") in task_ids:
                add("model-version", row)
        for row in inventory["model-build"]:
            if row.get("conversion_task_id") in task_ids:
                add("model-build", row)
        owned_versions = {rid for (rk, rid) in selected if rk == "model-version"}
        owned_builds = {rid for (rk, rid) in selected if rk == "model-build"}
        for row in inventory.get("imported-artifact", []):
            if row.get("model_version_id") in owned_versions or row.get("model_build_id") in owned_builds:
                add("imported-artifact", row)
        for row in inventory["model-file"]:
            if (
                row.get("model_version_id") in owned_versions
                or row.get("model_build_id") in owned_builds
            ):
                add("model-file", row)
        for row in inventory["outbox"]:
            if (
                referenced_ids(
                    {"payload": row["payload_json"], "metadata": row["metadata_json"]}
                )
                & task_ids
            ):
                add("outbox", row)
        changed = before != len(selected)

    blockers: list[dict] = []
    deleted_ids = {rid for (rk, rid) in selected if rk not in {"outbox", "model"}}
    for (rk, rid), row in selected.items():
        state = row.get("state", row.get("status"))
        active = (
            (
                rk == "task"
                and (
                    state not in TERMINAL_TASK_STATES
                    or row.get("publication_state") in {"reserved", "published"}
                )
            )
            or (
                rk in {"dataset-import", "dataset-export"}
                and state not in {"completed", "failed"}
            )
            or (rk == "outbox" and state in {"pending", "leased"})
        )
        if active:
            blockers.append({"resource_kind": rk, "resource_id": rid, "state": state})
    for rk in ("task", "dataset-export", "model-version", "model-build", "deployment"):
        for row in inventory[rk]:
            rid = row[ID_FIELDS[rk]]
            if (rk, rid) in selected:
                continue
            # Task result 是历史结果；task_spec 是执行/重跑需要的输入。
            payload = (
                {
                    "spec": row.get("task_spec_json", {}),
                    "parent_task_id": row.get("parent_task_id"),
                }
                if rk == "task"
                else row
            )
            dependencies = referenced_ids(payload) & deleted_ids
            if dependencies:
                blockers.append(
                    {
                        "resource_kind": rk,
                        "resource_id": rid,
                        "references": sorted(dependencies),
                    }
                )
    for row in inventory["deployment-state"]:
        if ("deployment", row["deployment_instance_id"]) in selected and (
            row["desired_state"] != "stopped"
            or row["observed_state"] not in {"stopped", "unknown"}
        ):
            blockers.append(
                {
                    "resource_kind": "deployment",
                    "resource_id": row["deployment_instance_id"],
                    "state": row["observed_state"],
                }
            )
    for row in inventory["task-attempt"]:
        if ("task", row["task_id"]) in selected and row["state"] == "running":
            blockers.append(
                {
                    "resource_kind": "task-attempt",
                    "resource_id": row["attempt_id"],
                    "state": "running",
                }
            )
    if blockers:
        # 保留既有转换 DELETE 的公开错误字段，同时补充通用依赖清单。
        protected_builds = [
            {
                "model_build_id": rid,
                "deployment_instance_ids": [
                    row["deployment_instance_id"]
                    for row in inventory["deployment"]
                    if row.get("model_build_id") == rid
                ],
            }
            for rk, rid in selected
            if rk == "model-build"
            and any(row.get("model_build_id") == rid for row in inventory["deployment"])
        ]
        raise ResourceInUseError(
            "资源仍被使用，请先停止或解除依赖",
            details={"blockers": blockers, "protected_builds": protected_builds},
        )

    # 空 Model 聚合不永久残留；保留任一版本、build 或文件时不删除聚合。
    affected_models = {
        row.get("model_id")
        for (rk, _rid), row in selected.items()
        if rk.startswith("model-")
    }
    for row in inventory["model"]:
        if row["model_id"] not in affected_models:
            continue
        if not any(
            item.get("model_id") == row["model_id"]
            and (rk, item[ID_FIELDS[rk]]) not in selected
            for rk in ("model-version", "model-build", "model-file")
            for item in inventory[rk]
        ):
            add("model", row)

    paths: set[str] = set()
    for (rk, rid), row in selected.items():
        normalize_queue_path_component(rid, field_name="resource_id")
        if rk == "task":
            paths.update(
                [
                    f"task-runs/{rid}",
                    *(
                        f"task-runs/{category}/{rid}"
                        for category in (
                            "training",
                            "conversion",
                            "evaluation",
                            "inference",
                        )
                    ),
                ]
            )
        elif rk in {"dataset-import", "dataset-export", "dataset-version"}:
            dataset_id = normalize_queue_path_component(
                row["dataset_id"], field_name="dataset_id"
            )
            root = f"projects/{project_id}/datasets/{dataset_id}"
            category = {
                "dataset-import": "imports",
                "dataset-export": "exports",
                "dataset-version": "versions",
            }[rk]
            paths.add(f"{root}/{category}/{rid}")
            if rk == "dataset-export":
                paths.add(f"{root}/downloads/dataset-exports/{rid}.zip")
                metadata = row.get("metadata_json") or {}
                for value in (
                    row.get("export_path"),
                    metadata.get("output_object_prefix"),
                    metadata.get("package_object_key"),
                ):
                    if not isinstance(value, str) or not value.strip():
                        continue
                    key = (
                        storage.resolve_deletion_path(value)
                        .relative_to(storage.root_dir.absolute())
                        .as_posix()
                    )
                    # 专属默认路径与旧 exports 区可清理；公共目录或外部资产拒绝自动删除。
                    allowed = (
                        key.startswith(f"{root}/exports/{rid}/")
                        or key == f"{root}/exports/{rid}"
                        or key == f"{root}/downloads/dataset-exports/{rid}.zip"
                        or (
                            key.startswith("exports/")
                            and len(PurePosixPath(key).parts) >= 3
                        )
                    )
                    if not allowed:
                        raise ResourceInUseError(
                            "导出文件路径不在可确认归属的受管目录内",
                            details={"dataset_export_id": rid, "object_key": key},
                        )
                    paths.add(key)
        elif rk == "deployment":
            paths.add(f"deployments/instances/{rid}")
            transfer_root = storage.resolve("runtime/transfers/async-inference")
            if transfer_root.is_dir():
                paths.update(
                    path.relative_to(storage.root_dir).as_posix()
                    for path in transfer_root.glob(f"*/{rid}")
                )
        elif rk == "imported-artifact":
            prefix = row["object_prefix"]
            owner_id = row.get("model_version_id") or row.get("model_build_id")
            category = "versions" if row.get("model_version_id") else "builds"
            expected = f"projects/{project_id}/models/imported/{category}/{owner_id}"
            if prefix != expected:
                raise ResourceInUseError("导入模型存储归属不匹配，禁止删除")
            paths.add(prefix)
    if kind == "dataset":
        paths.add(f"projects/{project_id}/datasets/{resource_id}")

    # 旧版本允许多个导出指向同一路径；共享导出目录必须先解除引用。
    for row in inventory["dataset-export"]:
        if ("dataset-export", row["dataset_export_id"]) in selected:
            continue
        metadata = row.get("metadata_json") or {}
        for value in (
            row.get("export_path"),
            metadata.get("output_object_prefix"),
            metadata.get("package_object_key"),
        ):
            if not isinstance(value, str) or not value.strip():
                continue
            key = storage.resolve(value).relative_to(storage.root_dir).as_posix()
            if any(
                key == root or key.startswith(root + "/") or root.startswith(key + "/")
                for root in paths
            ):
                raise ResourceInUseError(
                    "输出仍被其他导出记录使用",
                    details={
                        "blockers": [
                            {
                                "resource_kind": "dataset-export",
                                "resource_id": row["dataset_export_id"],
                            }
                        ]
                    },
                )

    # ModelFile URI 的引用必须被已知任务目录覆盖；外部登记文件不擅自删除。
    for (rk, rid), row in selected.items():
        if rk != "model-file":
            continue
        uri = row["storage_uri"]
        if "://" in uri:
            raise ResourceInUseError(
                "模型文件不是本次任务拥有的本地文件", details={"file_id": rid}
            )
        key = (
            storage.resolve_deletion_path(uri)
            .relative_to(storage.root_dir.absolute())
            .as_posix()
        )
        if not any(key == root or key.startswith(root + "/") for root in paths):
            raise ResourceInUseError(
                "模型文件位于独立资产目录，请从所属任务清理",
                details={"file_id": rid, "object_key": key},
            )
    for row in inventory["model-file"]:
        if ("model-file", row["file_id"]) in selected or "://" in row["storage_uri"]:
            continue
        key = (
            storage.resolve(row["storage_uri"]).relative_to(storage.root_dir).as_posix()
        )
        if any(key == root or key.startswith(root + "/") for root in paths):
            raise ResourceInUseError(
                "输出仍被其他模型文件引用", details={"file_id": row["file_id"]}
            )

    _check_workflow_references(inventory, storage, deleted_ids, project_id=project_id, strict=kind == "deployment" or any(rk == "imported-artifact" for rk, _ in selected))
    minimal_paths: list[str] = []
    for path in sorted(paths, key=lambda item: (len(PurePosixPath(item).parts), item)):
        storage.resolve_deletion_path(path)
        if any(path.startswith(parent + "/") for parent in minimal_paths):
            continue
        minimal_paths.append(path)
    return ResourceDeletionPlan(
        operation_id=operation_id,
        project_id=project_id,
        target=ResourceRef(kind=kind, resource_id=resource_id),
        records=[ResourceRef(kind=rk, resource_id=rid) for rk, rid in selected],
        paths=[
            StorageDeletionTarget(
                source=path,
                staged=f"runtime/resource-deletion-staging/{operation_id}/items/{index:04d}",
            )
            for index, path in enumerate(minimal_paths)
        ],
        queue_references=[
            (ID_FIELDS[rk], rid)
            for rk, rid in selected
            if rk in {"task", "dataset-import", "dataset-export", "deployment"}
        ],
    )


def _check_workflow_references(
    inventory: dict, storage: LocalDatasetStorage, deleted_ids: set[str], *, project_id: str | None = None, strict: bool = False
) -> None:
    """检查已发布快照和磁盘草稿内的显式资源引用。"""
    snapshots: set[str] = set()
    required_snapshots: set[str] = set()
    for kind in ("workflow-version", "workflow-runtime"):
        for row in inventory[kind]:
            for field in (
                "application_snapshot_object_key",
                "template_snapshot_object_key",
                "dependency_manifest_object_key",
            ):
                if row.get(field):
                    snapshots.add(row[field])
                    if row.get("project_id") == project_id:
                        required_snapshots.add(row[field])
    project_root = storage.resolve("workflows/projects")
    if project_root.is_dir():
        for name in ("application.json", "template.json"):
            snapshots.update(
                path.relative_to(storage.root_dir).as_posix()
                for path in project_root.rglob(name)
            )
    for key in snapshots:
        if not storage.resolve(key).is_file():
            if strict and key in required_snapshots:
                raise ResourceInUseError("Workflow 快照缺失，无法确认导入模型是否仍被使用", details={"snapshot_object_key": key})
            continue
        references = referenced_ids(storage.read_json(key)) & deleted_ids
        if references:
            raise ResourceInUseError(
                "Workflow 仍引用待删除资源",
                details={
                    "blockers": [
                        {
                            "resource_kind": "workflow",
                            "snapshot_object_key": key,
                            "references": sorted(references),
                        }
                    ]
                },
            )
