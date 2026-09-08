"""资源存量清理 CLI：先扫描，再按资源身份重检并执行。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from uuid import uuid4

from backend.service.application.errors import ServiceError
from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.application.resource_deletion_plan import (
    build_resource_deletion_plan,
    include_orphan_dataset_directory,
    ID_FIELDS,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.infrastructure.queue.local_file import LocalFileQueueBackend
from backend.service.settings import get_backend_service_settings


@dataclass(frozen=True)
class OrphanDirectory:
    """可审核的无主目录身份与预检结果；路径不能作为执行参数。"""

    project_id: str
    dataset_id: str
    kind: str
    resource_id: str
    object_key: str
    can_delete: bool
    reason: str | None


def scan_orphan_dataset_directories(
    factory, storage, queue, project_id: str
) -> list[OrphanDirectory]:
    """扫描标准目录，保留仍被模型、工作流、任务或队列引用的候选。"""
    from copy import deepcopy
    from backend.service.application.ports.queue import normalize_queue_path_component

    normalize_queue_path_component(project_id, field_name="project_id")
    with factory.create_session() as session:
        inventory = SqlAlchemyUnitOfWork(session).resource_deletions.inventory()
    candidates = []
    root = storage.resolve_deletion_path(f"projects/{project_id}/datasets")
    if not root.is_dir():
        return candidates
    for dataset in sorted(root.iterdir()):
        if not dataset.is_dir():
            continue
        for directory, kind in (
            ("imports", "dataset-import"),
            ("exports", "dataset-export"),
            ("versions", "dataset-version"),
        ):
            parent = dataset / directory
            if not parent.is_dir():
                continue
            known_ids = {row[ID_FIELDS[kind]] for row in inventory[kind]}
            for path in sorted(parent.iterdir()):
                if not path.is_dir() or path.name in known_ids:
                    continue
                key = path.relative_to(storage.root_dir).as_posix()
                error = None
                try:
                    storage.resolve_deletion_path(key)
                    snapshot = deepcopy(inventory)
                    include_orphan_dataset_directory(
                        snapshot,
                        project_id=project_id,
                        dataset_id=dataset.name,
                        kind=kind,
                        resource_id=path.name,
                    )
                    plan = build_resource_deletion_plan(
                        inventory=snapshot,
                        storage=storage,
                        project_id=project_id,
                        kind=kind,
                        resource_id=path.name,
                        operation_id=f"scan-{uuid4().hex}",
                    )
                    messages = queue.list_tasks_by_references(
                        references=tuple(plan.queue_references)
                    )
                    if any(
                        message.status in {"queued", "leased"} for message in messages
                    ):
                        error = "仍有活动队列消息"
                except (ServiceError, ValueError, OSError) as cause:
                    error = str(cause)
                candidates.append(
                    OrphanDirectory(
                        project_id,
                        dataset.name,
                        kind,
                        path.name,
                        key,
                        error is None,
                        error,
                    )
                )
    return candidates


def main() -> None:
    """运行扫描、单个候选清理或持久清理重试，全部输出为结构化 JSON。"""
    parser = argparse.ArgumentParser(description="资源存量扫描与清理")
    parser.add_argument("action", choices=("scan", "delete-orphan", "retry"))
    parser.add_argument("--project-id")
    parser.add_argument("--dataset-id")
    parser.add_argument(
        "--kind", choices=("dataset-import", "dataset-export", "dataset-version")
    )
    parser.add_argument("--resource-id")
    parser.add_argument("--operation-id")
    args = parser.parse_args()
    settings = get_backend_service_settings()
    factory = SessionFactory(settings.to_database_settings())
    storage = LocalDatasetStorage(settings.to_dataset_storage_settings())
    queue = LocalFileQueueBackend(settings.to_queue_settings())
    service = ResourceDeletionService(
        session_factory=factory, dataset_storage=storage, queue_backend=queue
    )
    try:
        if args.action == "scan":
            if not args.project_id:
                parser.error("scan 需要 --project-id")
            result = [
                asdict(item)
                for item in scan_orphan_dataset_directories(
                    factory, storage, queue, args.project_id
                )
            ]
        elif args.action == "delete-orphan":
            if not all((args.project_id, args.dataset_id, args.kind, args.resource_id)):
                parser.error(
                    "delete-orphan 需要 --project-id、--dataset-id、--kind 和 --resource-id"
                )
            service.delete(
                kind=args.kind,
                resource_id=args.resource_id,
                project_id=args.project_id,
                orphan_dataset_id=args.dataset_id,
            )
            result = {"state": "completed", "resource_id": args.resource_id}
        else:
            if not args.operation_id:
                parser.error("retry 需要 --operation-id")
            service.retry(args.operation_id)
            result = {"state": "completed", "operation_id": args.operation_id}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        factory.engine.dispose()


if __name__ == "__main__":
    main()
