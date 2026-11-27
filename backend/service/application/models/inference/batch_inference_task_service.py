"""批量推理任务应用服务（支持 async 与 sync 双通道部署，串行执行）。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from threading import Thread
from time import perf_counter
from typing import Callable
from uuid import uuid4

from backend.service.application.deployments.deployment_instance_service import (
    SqlAlchemyDeploymentInstanceService,
)
from backend.service.application.errors import (
    InvalidRequestError,
    PersistenceOperationError,
    ResourceConflictError,
    ResourceNotFoundError,
    ServiceError,
)
from backend.service.application.models.inference.classification_inference_payloads import (
    ClassificationNormalizedInferenceInput,
    attach_classification_inference_serialize_timing,
    build_classification_inference_payload,
    serialize_classification_inference_payload,
)
from backend.service.application.models.inference.detection_inference_payloads import (
    DetectionNormalizedInferenceInput,
    _validate_image_bytes,
    attach_detection_inference_serialize_timing,
    build_detection_inference_payload,
    serialize_detection_inference_payload,
)
from backend.service.application.models.inference.detection_inference_task_service import (
    DetectionInferenceExecutionResult,
)
from backend.service.application.models.inference.direct_inference_record_service import (
    SUPPORTED_INFERENCE_TASK_TYPES,
    build_result_summary,
    compute_result_item_count,
    normalize_inference_task_type,
)
from backend.service.application.models.inference.inference_gateway import (
    AsyncInferenceExecutor,
    QueueBackedAsyncInferenceClient,
    deserialize_async_inference_execution_result_payload,
)
from backend.service.application.models.inference.obb_inference_payloads import (
    ObbNormalizedInferenceInput,
    attach_obb_inference_serialize_timing,
    build_obb_inference_payload,
    serialize_obb_inference_payload,
)
from backend.service.application.models.inference.pose_inference_payloads import (
    PoseNormalizedInferenceInput,
    attach_pose_inference_serialize_timing,
    build_pose_inference_payload,
    serialize_pose_inference_payload,
)
from backend.service.application.models.inference.segmentation_inference_payloads import (
    SegmentationNormalizedInferenceInput,
    attach_segmentation_inference_serialize_timing,
    build_segmentation_inference_payload,
    serialize_segmentation_inference_payload,
)
from backend.service.application.ports.queue import QueueBackend
from backend.service.application.project_mutation import ProjectMutationAdmissionService
from backend.service.application.project_public_files import (
    resolve_public_project_file_reference,
)
from backend.service.application.datasets.content import content_key
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessConfig,
    DeploymentProcessSupervisor,
)
from backend.service.application.runtime.tasks.task_prediction_runtime import (
    build_prediction_request_from_payload,
)
from backend.service.application.runtime.serialization.detection.prediction import (
    serialize_detection,
    serialize_runtime_session_info,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.infrastructure.object_store.object_key_layout import (
    build_public_project_file_id,
)
from backend.service.infrastructure.persistence.batch_inference_task_orm import (
    BatchInferenceTaskItemRecord,
    BatchInferenceTaskRecord,
)

BATCH_INFERENCE_TERMINAL_STATES: frozenset[str] = frozenset(
    {"succeeded", "partial_failed", "failed", "cancelled"}
)
_SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
)
_MAX_BATCH_ITEMS = 500


def _now_isoformat() -> str:
    """生成 ISO8601 UTC 时间戳。"""

    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class UploadedBatchImageInput:
    """描述批量任务中一张本地上传的输入图片。"""

    filename: str
    content: bytes


@dataclass(frozen=True)
class CreateBatchInferenceTaskCommand:
    """创建批量推理任务所需的规范化请求。"""

    project_id: str
    task_type: str
    deployment_instance_id: str
    display_name: str
    source_kind: str  # upload | dataset_version | project_files
    runtime_mode: str = "auto"  # auto | async | sync
    uploaded_images: tuple[UploadedBatchImageInput, ...] = ()
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    dataset_split: str = ""
    sample_ids: tuple[str, ...] = ()
    input_file_ids: tuple[str, ...] = ()
    score_threshold: float = 0.3
    top_k: int = 5
    mask_threshold: float = 0.5
    keypoint_confidence_threshold: float = 0.3
    save_result_image: bool = True
    extra_options: dict[str, object] = field(default_factory=dict)
    created_by: str | None = None
    async_inference_owner_id: str = "backend-service"


@dataclass(frozen=True)
class _ResolvedBatchItemInput:
    """解析并校验完成后的单条批量输入。"""

    input_label: str
    input_source_kind: str
    input_file_id: str | None
    input_uri: str
    input_image_object_key: str
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    sample_id: str | None = None


class SqlAlchemyBatchInferenceTaskService:
    """管理批量推理任务的创建、双通道后台执行、进度更新、取消、查看与删除。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        sync_supervisor: DeploymentProcessSupervisor | None = None,
        async_executor: AsyncInferenceExecutor | None = None,
        spawn_background: bool = True,
        on_worker_spawn: Callable[[Thread], None] | None = None,
    ) -> None:
        """初始化批量推理任务服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.sync_supervisor = sync_supervisor
        self.async_executor = async_executor or QueueBackedAsyncInferenceClient(
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
        self.spawn_background = spawn_background
        self.on_worker_spawn = on_worker_spawn
        self.project_mutations = ProjectMutationAdmissionService(session_factory)
        self.deployments = SqlAlchemyDeploymentInstanceService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """打开并在退出时关闭 Unit of Work。"""

        uow = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield uow
        finally:
            uow.close()

    @staticmethod
    def _inspect_channel_running(
        supervisor: DeploymentProcessSupervisor | None,
        process_config: DeploymentProcessConfig,
    ) -> tuple[bool, str]:
        """检查指定通道监督器是否处于 running 状态，返回 (is_running, state)。"""

        if supervisor is None:
            return False, "unavailable"
        supervisor.ensure_deployment(process_config)
        process_state = supervisor.get_status(process_config).process_state
        return process_state == "running", process_state

    def _resolve_execution_runtime_mode(
        self,
        *,
        requested_mode: str,
        deployment_instance_id: str,
        process_config: DeploymentProcessConfig,
        sync_supervisor: DeploymentProcessSupervisor | None,
        async_supervisor: DeploymentProcessSupervisor | None,
    ) -> str:
        """解析并校验批量任务使用的实际执行通道（async 或 sync）。"""

        normalized = (requested_mode or "auto").strip().lower()
        if normalized not in {"auto", "async", "sync"}:
            raise InvalidRequestError(
                "批量推理 runtime_mode 不合法",
                details={"runtime_mode": requested_mode, "supported": ["auto", "async", "sync"]},
            )
        async_running, async_state = self._inspect_channel_running(
            async_supervisor, process_config
        )
        sync_running, sync_state = self._inspect_channel_running(
            sync_supervisor, process_config
        )
        if normalized == "async":
            if not async_running:
                raise InvalidRequestError(
                    "所选部署的异步通道尚未启动，请先启动 async 通道或切换为同步通道",
                    details={
                        "deployment_instance_id": deployment_instance_id,
                        "runtime_mode": "async",
                        "process_state": async_state,
                    },
                )
            return "async"
        if normalized == "sync":
            if not sync_running:
                raise InvalidRequestError(
                    "所选部署的同步通道尚未启动，请先在部署页面启动 sync 通道",
                    details={
                        "deployment_instance_id": deployment_instance_id,
                        "runtime_mode": "sync",
                        "process_state": sync_state,
                    },
                )
            return "sync"
        if async_running:
            return "async"
        if sync_running:
            return "sync"
        raise InvalidRequestError(
            "所选部署的同步与异步通道均未启动，请先在部署页面启动任一通道",
            details={
                "deployment_instance_id": deployment_instance_id,
                "runtime_mode": "auto",
                "async_process_state": async_state,
                "sync_process_state": sync_state,
            },
        )

    def create_batch_task(
        self,
        command: CreateBatchInferenceTaskCommand,
        *,
        sync_supervisor: DeploymentProcessSupervisor | None = None,
        async_supervisor: DeploymentProcessSupervisor | None = None,
        async_gateway_registry: object | None = None,
    ) -> BatchInferenceTaskRecord:
        """校验目标部署通道（支持 async 或 sync）并创建批量推理任务，返回任务主记录。"""

        task_type = normalize_inference_task_type(command.task_type)
        deployment_view = self.deployments.get_visible_deployment_instance(
            command.deployment_instance_id,
            visible_project_ids=(command.project_id,),
        )
        if deployment_view.task_type != task_type:
            raise InvalidRequestError(
                "所选部署实例的任务类型与批量推理请求不一致",
                details={
                    "deployment_instance_id": command.deployment_instance_id,
                    "expected_task_type": task_type,
                    "actual_task_type": deployment_view.task_type,
                },
            )
        process_config = self.deployments.resolve_process_config(
            command.deployment_instance_id
        )
        effective_sync_supervisor = sync_supervisor or self.sync_supervisor
        requested_mode = (command.runtime_mode or "auto").strip().lower()
        execution_runtime_mode = self._resolve_execution_runtime_mode(
            requested_mode=requested_mode,
            deployment_instance_id=command.deployment_instance_id,
            process_config=process_config,
            sync_supervisor=effective_sync_supervisor,
            async_supervisor=async_supervisor,
        )
        if execution_runtime_mode == "async" and async_gateway_registry is not None:
            ensure_dispatcher = getattr(
                async_gateway_registry,
                "ensure_dispatcher_for_deployment",
                None,
            )
            if callable(ensure_dispatcher):
                ensure_dispatcher(command.deployment_instance_id)

        batch_task_id = f"batch-infer-{uuid4().hex}"
        output_prefix = (
            f"projects/{command.project_id}/results/batch-inference/{batch_task_id}"
        )
        resolved_items, source_summary = self._resolve_batch_inputs(
            command=command,
            output_prefix=output_prefix,
        )
        if len(resolved_items) > _MAX_BATCH_ITEMS:
            raise InvalidRequestError(
                f"单次批量推理最多支持 {_MAX_BATCH_ITEMS} 张图片",
                details={"total_items": len(resolved_items)},
            )

        now = _now_isoformat()
        display_name = (
            command.display_name.strip()
            or f"批量推理 · {deployment_view.display_name} ({len(resolved_items)}图)"
        )
        parameters = {
            "score_threshold": command.score_threshold,
            "top_k": command.top_k,
            "mask_threshold": command.mask_threshold,
            "keypoint_confidence_threshold": command.keypoint_confidence_threshold,
            "save_result_image": command.save_result_image,
            "extra_options": dict(command.extra_options),
            "async_inference_owner_id": command.async_inference_owner_id,
            "requested_runtime_mode": requested_mode,
            "execution_runtime_mode": execution_runtime_mode,
        }
        batch_record = BatchInferenceTaskRecord(
            batch_task_id=batch_task_id,
            project_id=command.project_id,
            task_type=task_type,
            display_name=display_name,
            deployment_instance_id=command.deployment_instance_id,
            deployment_display_name=deployment_view.display_name,
            model_version_id=deployment_view.model_version_id,
            model_build_id=deployment_view.model_build_id,
            source_kind=command.source_kind,
            source_summary_json=source_summary,
            parameters_json=parameters,
            state="queued",
            total_items=len(resolved_items),
            completed_items=0,
            succeeded_items=0,
            failed_items=0,
            skipped_items=0,
            output_object_prefix=output_prefix,
            error_message=None,
            created_by=command.created_by,
            created_at=now,
            started_at=None,
            finished_at=None,
            updated_at=now,
        )
        item_records = [
            BatchInferenceTaskItemRecord(
                item_id=f"{batch_task_id}-item-{index:04d}",
                batch_task_id=batch_task_id,
                sequence_no=index,
                input_label=item.input_label,
                input_source_kind=item.input_source_kind,
                input_file_id=item.input_file_id,
                input_uri=item.input_uri,
                input_image_object_key=item.input_image_object_key,
                dataset_id=item.dataset_id,
                dataset_version_id=item.dataset_version_id,
                sample_id=item.sample_id,
                state="pending",
                result_summary_json={},
            )
            for index, item in enumerate(resolved_items, start=1)
        ]

        try:
            with self.project_mutations.operation(
                project_id=command.project_id,
                mutation_kind="batch-inference-create",
                resource_id=batch_task_id,
            ):
                with self._open_unit_of_work() as uow:
                    uow.batch_inference_tasks.add_task(batch_record, item_records)
                    uow.commit()
                    uow.session.refresh(batch_record)
                    uow.session.expunge(batch_record)
        except Exception:
            self._safe_cleanup_tree(output_prefix)
            raise

        if self.spawn_background:
            worker = Thread(
                target=self.process_batch_task,
                args=(batch_task_id,),
                kwargs={"sync_supervisor": effective_sync_supervisor},
                name=f"batch-infer-{batch_task_id[:16]}",
                daemon=True,
            )
            if self.on_worker_spawn is not None:
                self.on_worker_spawn(worker)
            worker.start()

        return batch_record

    def process_batch_task(
        self,
        batch_task_id: str,
        *,
        sync_supervisor: DeploymentProcessSupervisor | None = None,
    ) -> BatchInferenceTaskRecord:
        """顺序执行批量任务中的单图推理并持久更新进度；支持任务取消与单图容错。"""

        effective_sync_supervisor = sync_supervisor or self.sync_supervisor
        with self._open_unit_of_work() as uow:
            task = uow.batch_inference_tasks.get(batch_task_id)
            if task is None:
                raise ResourceNotFoundError(
                    "找不到指定的批量推理任务",
                    details={"batch_task_id": batch_task_id},
                )
            if task.state in BATCH_INFERENCE_TERMINAL_STATES:
                return task
            now = _now_isoformat()
            task.state = "running"
            task.started_at = task.started_at or now
            task.updated_at = now
            items = uow.batch_inference_tasks.list_items(batch_task_id)
            item_ids = [item.item_id for item in items if item.state == "pending"]
            process_config = self.deployments.resolve_process_config(
                task.deployment_instance_id
            )
            task_type = task.task_type
            parameters = dict(task.parameters_json or {})
            owner_id = str(parameters.get("async_inference_owner_id") or "backend-service")
            execution_runtime_mode = str(
                parameters.get("execution_runtime_mode") or "async"
            )
            uow.commit()

        for item_id in item_ids:
            with self._open_unit_of_work() as uow:
                current_task = uow.batch_inference_tasks.get(batch_task_id)
                if current_task is None:
                    return current_task  # type: ignore[return-value]
                if current_task.state == "cancelled":
                    self._cancel_remaining_items(uow, current_task)
                    uow.commit()
                    return current_task
                item = uow.batch_inference_tasks.get_item(batch_task_id, item_id)
                if item is None or item.state != "pending":
                    continue
                item.state = "running"
                item.started_at = _now_isoformat()
                current_task.updated_at = item.started_at
                item_snapshot = {
                    "item_id": item.item_id,
                    "input_uri": item.input_uri or item.input_image_object_key or "",
                    "input_source_kind": item.input_source_kind,
                    "input_file_id": item.input_file_id,
                }
                batch_prefix = current_task.output_object_prefix
                uow.commit()

            try:
                outcome = self._execute_single_item(
                    batch_task_id=batch_task_id,
                    batch_output_prefix=batch_prefix,
                    item_id=item_id,
                    task_type=task_type,
                    execution_runtime_mode=execution_runtime_mode,
                    sync_supervisor=effective_sync_supervisor,
                    process_config=process_config,
                    parameters=parameters,
                    owner_id=owner_id,
                    input_uri=str(item_snapshot["input_uri"]),
                    input_source_kind=str(item_snapshot["input_source_kind"]),
                    input_file_id=(
                        str(item_snapshot["input_file_id"])
                        if item_snapshot["input_file_id"]
                        else None
                    ),
                )
                with self._open_unit_of_work() as uow:
                    current_task = uow.batch_inference_tasks.get(batch_task_id)
                    item = uow.batch_inference_tasks.get_item(batch_task_id, item_id)
                    if current_task is not None and item is not None:
                        item.state = "succeeded"
                        item.item_count = outcome["item_count"]
                        item.latency_ms = outcome["latency_ms"]
                        item.image_width = outcome["image_width"]
                        item.image_height = outcome["image_height"]
                        item.result_object_key = outcome["result_object_key"]
                        item.preview_image_object_key = outcome["preview_image_object_key"]
                        item.result_summary_json = outcome["result_summary"]
                        item.finished_at = _now_isoformat()
                        current_task.completed_items += 1
                        current_task.succeeded_items += 1
                        current_task.updated_at = item.finished_at
                        uow.commit()
            except Exception as error:
                error_code = (
                    getattr(error, "code", None) or type(error).__name__
                )
                error_message = (
                    error.message if isinstance(error, ServiceError) else str(error)
                )
                with self._open_unit_of_work() as uow:
                    current_task = uow.batch_inference_tasks.get(batch_task_id)
                    item = uow.batch_inference_tasks.get_item(batch_task_id, item_id)
                    if current_task is not None and item is not None:
                        item.state = "failed"
                        item.error_code = error_code
                        item.error_message = error_message
                        item.finished_at = _now_isoformat()
                        current_task.completed_items += 1
                        current_task.failed_items += 1
                        current_task.updated_at = item.finished_at
                        uow.commit()

        with self._open_unit_of_work() as uow:
            task = uow.batch_inference_tasks.get(batch_task_id)
            if task is None:
                raise ResourceNotFoundError(
                    "找不到指定的批量推理任务",
                    details={"batch_task_id": batch_task_id},
                )
            now = _now_isoformat()
            if task.state == "cancelled":
                self._cancel_remaining_items(uow, task)
            elif task.failed_items == 0:
                task.state = "succeeded"
            elif task.succeeded_items > 0:
                task.state = "partial_failed"
            else:
                task.state = "failed"
                task.error_message = "批量任务中所有图像均推理失败"
            task.finished_at = now
            task.updated_at = now
            uow.commit()
            uow.session.refresh(task)
            uow.session.expunge(task)
            return task

    def list_batch_tasks(
        self,
        *,
        project_id: str,
        task_type: str | None = None,
        state: str | None = None,
        deployment_instance_id: str | None = None,
        q: str | None = None,
    ) -> list[BatchInferenceTaskRecord]:
        """按筛选条件查询批量推理任务列表。"""

        normalized_task_type = (
            normalize_inference_task_type(task_type) if task_type else None
        )
        with self._open_unit_of_work() as uow:
            rows = uow.batch_inference_tasks.list(
                project_id,
                task_type=normalized_task_type,
                state=state,
                deployment_instance_id=deployment_instance_id,
                q=q,
            )
            for row in rows:
                uow.session.expunge(row)
            return rows

    def get_batch_task(
        self,
        batch_task_id: str,
        *,
        visible_project_ids: tuple[str, ...] = (),
    ) -> BatchInferenceTaskRecord:
        """读取并校验指定批量推理任务访问权限。"""

        with self._open_unit_of_work() as uow:
            task = uow.batch_inference_tasks.get(batch_task_id)
            if task is not None:
                uow.session.expunge(task)
        if task is None:
            raise ResourceNotFoundError(
                "找不到指定的批量推理任务",
                details={"batch_task_id": batch_task_id},
            )
        if visible_project_ids and task.project_id not in visible_project_ids:
            raise ResourceNotFoundError(
                "找不到指定的批量推理任务",
                details={"batch_task_id": batch_task_id},
            )
        return task

    def list_batch_items(
        self,
        batch_task_id: str,
        *,
        visible_project_ids: tuple[str, ...] = (),
        state: str | None = None,
        q: str | None = None,
    ) -> list[BatchInferenceTaskItemRecord]:
        """读取批量推理任务下的图像子项列表。"""

        self.get_batch_task(batch_task_id, visible_project_ids=visible_project_ids)
        with self._open_unit_of_work() as uow:
            items = uow.batch_inference_tasks.list_items(
                batch_task_id,
                state=state,
                q=q,
            )
            for item in items:
                uow.session.expunge(item)
            return items

    def get_batch_item_result(
        self,
        batch_task_id: str,
        item_id: str,
        *,
        visible_project_ids: tuple[str, ...] = (),
    ) -> tuple[BatchInferenceTaskItemRecord, str, dict[str, object]]:
        """读取单个图像子项的推理结果 JSON 与文件状态。"""

        self.get_batch_task(batch_task_id, visible_project_ids=visible_project_ids)
        with self._open_unit_of_work() as uow:
            item = uow.batch_inference_tasks.get_item(batch_task_id, item_id)
            if item is not None:
                uow.session.expunge(item)
        if item is None:
            raise ResourceNotFoundError(
                "找不到指定的批量推理子项",
                details={"batch_task_id": batch_task_id, "item_id": item_id},
            )
        if not item.result_object_key:
            return item, "pending" if item.state in {"pending", "running"} else "missing", {}
        path = self.dataset_storage.resolve(item.result_object_key)
        if not path.is_file():
            return item, "missing", {}
        payload = self.dataset_storage.read_json(item.result_object_key)
        if not isinstance(payload, dict):
            return item, "missing", {}
        return item, "ready", payload

    def resolve_batch_item_image_path(
        self,
        batch_task_id: str,
        item_id: str,
        *,
        kind: str,
        visible_project_ids: tuple[str, ...] = (),
    ) -> tuple[str, Path]:
        """安全解析批量子项的输入图或预览图本地文件路径。"""

        task = self.get_batch_task(batch_task_id, visible_project_ids=visible_project_ids)
        with self._open_unit_of_work() as uow:
            item = uow.batch_inference_tasks.get_item(batch_task_id, item_id)
        if item is None:
            raise ResourceNotFoundError(
                "找不到指定的批量推理子项",
                details={"batch_task_id": batch_task_id, "item_id": item_id},
            )
        object_key = (
            item.preview_image_object_key
            if kind == "preview"
            else item.input_image_object_key
        )
        if not object_key:
            raise ResourceNotFoundError(
                "当前子项没有可读取的图片文件",
                details={"batch_task_id": batch_task_id, "item_id": item_id, "kind": kind},
            )
        root = self.dataset_storage.resolve(f"projects/{task.project_id}").resolve()
        candidate = self.dataset_storage.resolve(object_key).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ResourceNotFoundError(
                "子项关联的图片文件不存在或已移除",
                details={"batch_task_id": batch_task_id, "item_id": item_id, "kind": kind},
            )
        return object_key, candidate

    def cancel_batch_task(
        self,
        batch_task_id: str,
        *,
        visible_project_ids: tuple[str, ...] = (),
    ) -> BatchInferenceTaskRecord:
        """取消排队中或执行中的批量推理任务。"""

        task = self.get_batch_task(batch_task_id, visible_project_ids=visible_project_ids)
        if task.state in BATCH_INFERENCE_TERMINAL_STATES:
            return task
        with self._open_unit_of_work() as uow:
            current = uow.batch_inference_tasks.get(batch_task_id)
            if current is None:
                raise ResourceNotFoundError(
                    "找不到指定的批量推理任务",
                    details={"batch_task_id": batch_task_id},
                )
            if current.state in BATCH_INFERENCE_TERMINAL_STATES:
                uow.session.expunge(current)
                return current
            now = _now_isoformat()
            was_queued = current.state == "queued"
            current.state = "cancelled"
            current.updated_at = now
            if was_queued:
                self._cancel_remaining_items(uow, current)
                current.finished_at = now
            uow.commit()
            uow.session.refresh(current)
            uow.session.expunge(current)
            return current

    def delete_batch_task(
        self,
        batch_task_id: str,
        *,
        visible_project_ids: tuple[str, ...] = (),
    ) -> None:
        """仅允许删除已结束的批量推理任务；先清文件再删数据库记录。"""

        task = self.get_batch_task(batch_task_id, visible_project_ids=visible_project_ids)
        if task.state not in BATCH_INFERENCE_TERMINAL_STATES:
            raise ResourceConflictError(
                "批量推理任务仍在执行，请先取消后再删除",
                details={"batch_task_id": batch_task_id, "state": task.state},
            )
        try:
            self.dataset_storage.delete_tree(task.output_object_prefix)
        except OSError as error:
            raise PersistenceOperationError(
                "清理批量推理产物文件失败，记录已保留；请解除文件占用后重试删除",
                details={"batch_task_id": batch_task_id, "error": str(error)},
            ) from error

        with self.project_mutations.operation(
            project_id=task.project_id,
            mutation_kind="batch-inference-delete",
            resource_id=batch_task_id,
        ):
            with self._open_unit_of_work() as uow:
                current = uow.batch_inference_tasks.get(batch_task_id)
                if current is not None:
                    uow.batch_inference_tasks.delete_task(current)
                    uow.commit()

    def _resolve_batch_inputs(
        self,
        *,
        command: CreateBatchInferenceTaskCommand,
        output_prefix: str,
    ) -> tuple[list[_ResolvedBatchItemInput], dict[str, object]]:
        """按三选一来源校验并展开全部待推理图像。"""

        if command.source_kind == "upload":
            if not command.uploaded_images:
                raise InvalidRequestError("upload 来源至少需要上传 1 张图片")
            resolved: list[_ResolvedBatchItemInput] = []
            for idx, item in enumerate(command.uploaded_images, start=1):
                if not item.content:
                    raise InvalidRequestError(f"上传图片不能为空：{item.filename}")
                _validate_image_bytes(image_bytes=item.content, field_name="input_images")
                safe_name = Path(item.filename or f"image_{idx}.jpg").name
                object_key = f"{output_prefix}/inputs/{idx:04d}_{safe_name}"
                self.dataset_storage.write_bytes(object_key, item.content)
                resolved.append(
                    _ResolvedBatchItemInput(
                        input_label=safe_name,
                        input_source_kind="multipart",
                        input_file_id=build_public_project_file_id(
                            project_id=command.project_id,
                            object_key=object_key,
                        ),
                        input_uri=object_key,
                        input_image_object_key=object_key,
                    )
                )
            return resolved, {"file_count": len(resolved)}

        if command.source_kind == "dataset_version":
            if not command.dataset_id or not command.dataset_version_id:
                raise InvalidRequestError("dataset_version 来源必须指定 dataset_id 与 dataset_version_id")
            with self._open_unit_of_work() as uow:
                version = uow.dataset_catalog.version_identity(
                    command.dataset_id,
                    command.dataset_version_id,
                )
                if version["project_id"] != command.project_id:
                    raise ResourceNotFoundError("找不到指定的数据集版本")
                root_key = content_key(
                    command.project_id,
                    command.dataset_id,
                    command.dataset_version_id,
                    version["metadata"],
                )
                if command.sample_ids:
                    samples = [
                        uow.dataset_catalog.sample(command.dataset_version_id, sample_id)
                        for sample_id in command.sample_ids
                    ]
                else:
                    page = uow.dataset_catalog.samples(
                        command.dataset_version_id,
                        split=command.dataset_split or "",
                        offset=0,
                        limit=_MAX_BATCH_ITEMS,
                    )
                    samples = list(page["items"])
            if not samples:
                raise InvalidRequestError("所选数据集版本或划分下没有可推理的图片样本")
            resolved = []
            for sample in samples:
                rel_key = str(
                    sample["metadata"].get("image_object_key")
                    or f"images/{sample['split']}/{sample['sample_id']}/{sample['file_name']}"
                )
                relative = PurePosixPath(rel_key.replace("\\", "/"))
                if relative.is_absolute() or ".." in relative.parts or ":" in rel_key:
                    raise InvalidRequestError("样本图片路径无效")
                object_key = f"{root_key}/{relative.as_posix()}"
                if not self.dataset_storage.resolve(object_key).is_file():
                    raise ResourceNotFoundError(
                        "样本图片不存在或已移除",
                        details={"sample_id": sample["sample_id"], "object_key": object_key},
                    )
                resolved.append(
                    _ResolvedBatchItemInput(
                        input_label=str(sample["file_name"] or sample["sample_id"]),
                        input_source_kind="dataset_sample",
                        input_file_id=build_public_project_file_id(
                            project_id=command.project_id,
                            object_key=object_key,
                        ),
                        input_uri=object_key,
                        input_image_object_key=object_key,
                        dataset_id=command.dataset_id,
                        dataset_version_id=command.dataset_version_id,
                        sample_id=str(sample["sample_id"]),
                    )
                )
            return resolved, {
                "dataset_id": command.dataset_id,
                "dataset_version_id": command.dataset_version_id,
                "split": command.dataset_split,
                "sample_count": len(resolved),
            }

        if command.source_kind == "project_files":
            if not command.input_file_ids:
                raise InvalidRequestError("project_files 来源至少需要选择 1 个文件")
            resolved = []
            for file_id in command.input_file_ids:
                ref = resolve_public_project_file_reference(
                    dataset_storage=self.dataset_storage,
                    file_id=file_id,
                    expected_project_id=command.project_id,
                )
                path = self.dataset_storage.resolve(ref.object_key)
                if path.suffix.lower() not in _SUPPORTED_IMAGE_EXTENSIONS:
                    raise InvalidRequestError(
                        "所选项目文件不是支持的图片格式",
                        details={"object_key": ref.object_key},
                    )
                resolved.append(
                    _ResolvedBatchItemInput(
                        input_label=path.name,
                        input_source_kind="input_file_id",
                        input_file_id=file_id,
                        input_uri=ref.object_key,
                        input_image_object_key=ref.object_key,
                    )
                )
            return resolved, {"file_count": len(resolved)}

        raise InvalidRequestError(
            "不支持的批量输入来源",
            details={
                "source_kind": command.source_kind,
                "supported_sources": ["upload", "dataset_version", "project_files"],
            },
        )

    def _execute_single_item(
        self,
        *,
        batch_task_id: str,
        batch_output_prefix: str,
        item_id: str,
        task_type: str,
        execution_runtime_mode: str,
        sync_supervisor: DeploymentProcessSupervisor | None,
        process_config: DeploymentProcessConfig,
        parameters: dict[str, object],
        owner_id: str,
        input_uri: str,
        input_source_kind: str,
        input_file_id: str | None,
    ) -> dict[str, object]:
        """按 execution_runtime_mode（async 或 sync）顺序执行单张图像并落盘结果。"""

        score_threshold = float(parameters.get("score_threshold", 0.3))
        top_k = int(parameters.get("top_k", 5))
        mask_threshold = float(parameters.get("mask_threshold", 0.5))
        keypoint_threshold = float(parameters.get("keypoint_confidence_threshold", 0.3))
        save_result_image = bool(parameters.get("save_result_image", True))
        extra_options = dict(parameters.get("extra_options") or {})

        payload_spec: dict[str, object] = {
            "input_uri": input_uri,
            "save_result_image": save_result_image,
            "extra_options": extra_options,
            "score_threshold": score_threshold,
            "top_k": top_k,
            "mask_threshold": mask_threshold,
            "keypoint_confidence_threshold": keypoint_threshold,
        }
        prediction_request = build_prediction_request_from_payload(
            task_type=task_type,
            payload=payload_spec,
        )
        if execution_runtime_mode == "sync":
            if sync_supervisor is None:
                raise InvalidRequestError(
                    "同步通道监督器不可用，无法执行同步批量推理",
                    details={"deployment_instance_id": process_config.deployment_instance_id},
                )
            # 严格遵守零等待队列与零自动重试原则：直接单次调用 sync supervisor，失败立即上抛记录为子项失败。
            execution = sync_supervisor.run_inference(
                config=process_config,
                request=prediction_request,
            )
            instance_id = execution.instance_id
            execution_result = execution.execution_result
        else:
            raw_response = self.async_executor.execute_inference(
                process_config=process_config,
                request=prediction_request,
                owner_id=owner_id,
            )
            deserialized = deserialize_async_inference_execution_result_payload(
                task_type=task_type,
                payload=raw_response,
            )
            instance_id = deserialized.get("instance_id")
            execution_result = deserialized["execution_result"]

        item_prefix = f"{batch_output_prefix}/items/{item_id}"
        result_object_key = f"{item_prefix}/raw-result.json"
        preview_bytes = getattr(execution_result, "preview_image_bytes", None)
        preview_key: str | None = None
        if save_result_image and isinstance(preview_bytes, bytes) and preview_bytes:
            preview_key = f"{item_prefix}/preview.jpg"
            self.dataset_storage.write_bytes(preview_key, preview_bytes)

        serialize_started = perf_counter()
        serialized_payload = self._serialize_item_payload(
            task_type=task_type,
            request_id=item_id,
            batch_task_id=batch_task_id,
            deployment_instance_id=process_config.deployment_instance_id,
            instance_id=str(instance_id) if instance_id else None,
            process_config=process_config,
            input_uri=input_uri,
            input_source_kind=input_source_kind,
            input_file_id=input_file_id,
            parameters=parameters,
            execution_result=execution_result,
            preview_image_uri=preview_key,
            result_object_key=result_object_key,
            serialize_ms=(perf_counter() - serialize_started) * 1000,
        )
        self.dataset_storage.write_json(result_object_key, serialized_payload)

        return {
            "item_count": compute_result_item_count(task_type, serialized_payload),
            "latency_ms": serialized_payload.get("latency_ms"),
            "image_width": serialized_payload.get("image_width"),
            "image_height": serialized_payload.get("image_height"),
            "result_object_key": result_object_key,
            "preview_image_object_key": preview_key,
            "result_summary": build_result_summary(task_type, serialized_payload),
        }

    def _serialize_item_payload(
        self,
        *,
        task_type: str,
        request_id: str,
        batch_task_id: str,
        deployment_instance_id: str,
        instance_id: str | None,
        process_config: DeploymentProcessConfig,
        input_uri: str,
        input_source_kind: str,
        input_file_id: str | None,
        parameters: dict[str, object],
        execution_result: object,
        preview_image_uri: str | None,
        result_object_key: str,
        serialize_ms: float,
    ) -> dict[str, object]:
        """使用与单图正式推理一致的序列化器构造单图结果 JSON。"""

        runtime_target = process_config.runtime_target
        save_result_image = bool(parameters.get("save_result_image", True))

        if task_type == "detection":
            normalized = DetectionNormalizedInferenceInput(
                input_uri=input_uri,
                input_source_kind=input_source_kind,
                input_file_id=input_file_id,
                input_transport_mode="storage",
            )
            compat_exec = DetectionInferenceExecutionResult(
                instance_id=instance_id,
                detections=tuple(
                    serialize_detection(item)
                    for item in getattr(execution_result, "detections")
                ),
                latency_ms=getattr(execution_result, "latency_ms", None),
                image_width=getattr(execution_result, "image_width"),
                image_height=getattr(execution_result, "image_height"),
                preview_image_bytes=getattr(execution_result, "preview_image_bytes", None),
                runtime_session_info=serialize_runtime_session_info(
                    getattr(execution_result, "runtime_session_info")
                ),
            )
            payload = serialize_detection_inference_payload(
                build_detection_inference_payload(
                    request_id=request_id,
                    inference_task_id=batch_task_id,
                    deployment_instance_id=deployment_instance_id,
                    instance_id=instance_id,
                    runtime_target=runtime_target,
                    normalized_input=normalized,
                    score_threshold=float(parameters.get("score_threshold", 0.3)),
                    save_result_image=save_result_image,
                    return_preview_image_base64=False,
                    execution_result=compat_exec,
                    preview_image_uri=preview_image_uri,
                    result_object_key=result_object_key,
                )
            )
            return attach_detection_inference_serialize_timing(
                payload=payload,
                serialize_ms=serialize_ms,
            )

        if task_type == "classification":
            normalized = ClassificationNormalizedInferenceInput(
                input_uri=input_uri,
                input_source_kind=input_source_kind,
                input_file_id=input_file_id,
                input_transport_mode="storage",
            )
            payload = serialize_classification_inference_payload(
                build_classification_inference_payload(
                    request_id=request_id,
                    inference_task_id=batch_task_id,
                    deployment_instance_id=deployment_instance_id,
                    instance_id=instance_id,
                    runtime_target=runtime_target,
                    normalized_input=normalized,
                    top_k=int(parameters.get("top_k", 5)),
                    save_result_image=save_result_image,
                    return_preview_image_base64=False,
                    execution_result=execution_result,  # type: ignore[arg-type]
                    preview_image_uri=preview_image_uri,
                    result_object_key=result_object_key,
                )
            )
            return attach_classification_inference_serialize_timing(
                payload=payload,
                serialize_ms=serialize_ms,
            )

        if task_type == "segmentation":
            normalized = SegmentationNormalizedInferenceInput(
                input_uri=input_uri,
                input_source_kind=input_source_kind,
                input_file_id=input_file_id,
                input_transport_mode="storage",
            )
            payload = serialize_segmentation_inference_payload(
                build_segmentation_inference_payload(
                    request_id=request_id,
                    inference_task_id=batch_task_id,
                    deployment_instance_id=deployment_instance_id,
                    instance_id=instance_id,
                    runtime_target=runtime_target,
                    normalized_input=normalized,
                    score_threshold=float(parameters.get("score_threshold", 0.3)),
                    mask_threshold=float(parameters.get("mask_threshold", 0.5)),
                    save_result_image=save_result_image,
                    return_preview_image_base64=False,
                    execution_result=execution_result,  # type: ignore[arg-type]
                    preview_image_uri=preview_image_uri,
                    result_object_key=result_object_key,
                )
            )
            return attach_segmentation_inference_serialize_timing(
                payload=payload,
                serialize_ms=serialize_ms,
            )

        if task_type == "pose":
            normalized = PoseNormalizedInferenceInput(
                input_uri=input_uri,
                input_source_kind=input_source_kind,
                input_file_id=input_file_id,
                input_transport_mode="storage",
            )
            payload = serialize_pose_inference_payload(
                build_pose_inference_payload(
                    request_id=request_id,
                    inference_task_id=batch_task_id,
                    deployment_instance_id=deployment_instance_id,
                    instance_id=instance_id,
                    runtime_target=runtime_target,
                    normalized_input=normalized,
                    score_threshold=float(parameters.get("score_threshold", 0.3)),
                    keypoint_confidence_threshold=float(
                        parameters.get("keypoint_confidence_threshold", 0.3)
                    ),
                    save_result_image=save_result_image,
                    return_preview_image_base64=False,
                    execution_result=execution_result,  # type: ignore[arg-type]
                    preview_image_uri=preview_image_uri,
                    result_object_key=result_object_key,
                )
            )
            return attach_pose_inference_serialize_timing(
                payload=payload,
                serialize_ms=serialize_ms,
            )

        if task_type == "obb":
            normalized = ObbNormalizedInferenceInput(
                input_uri=input_uri,
                input_source_kind=input_source_kind,
                input_file_id=input_file_id,
                input_transport_mode="storage",
            )
            payload = serialize_obb_inference_payload(
                build_obb_inference_payload(
                    request_id=request_id,
                    inference_task_id=batch_task_id,
                    deployment_instance_id=deployment_instance_id,
                    instance_id=instance_id,
                    runtime_target=runtime_target,
                    normalized_input=normalized,
                    score_threshold=float(parameters.get("score_threshold", 0.3)),
                    save_result_image=save_result_image,
                    return_preview_image_base64=False,
                    execution_result=execution_result,  # type: ignore[arg-type]
                    preview_image_uri=preview_image_uri,
                    result_object_key=result_object_key,
                )
            )
            return attach_obb_inference_serialize_timing(
                payload=payload,
                serialize_ms=serialize_ms,
            )

        raise InvalidRequestError(
            "不支持的任务类型",
            details={"task_type": task_type, "supported": list(SUPPORTED_INFERENCE_TASK_TYPES)},
        )

    @staticmethod
    def _cancel_remaining_items(
        uow: SqlAlchemyUnitOfWork,
        task: BatchInferenceTaskRecord,
    ) -> None:
        """把尚未执行的子项统一标记为 cancelled 并累加 skipped_items。"""

        now = _now_isoformat()
        pending_items = uow.batch_inference_tasks.list_items(
            task.batch_task_id,
            state="pending",
        )
        for item in pending_items:
            item.state = "cancelled"
            item.finished_at = now
            task.skipped_items += 1
        task.updated_at = now

    def _safe_cleanup_tree(self, object_prefix: str) -> None:
        """创建回滚时尽力清理暂存目录。"""

        try:
            self.dataset_storage.delete_tree(object_prefix)
        except Exception:
            return
