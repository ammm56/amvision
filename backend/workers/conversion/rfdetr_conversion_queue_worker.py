"""RF-DETR 转换队列 worker。"""

from __future__ import annotations

from pathlib import Path

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.backends import ConversionBackend, ConversionBackendRunRequest
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    SqlAlchemyTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.rfdetr_conversion_runner import LocalRfdetrConversionRunner


RFDETR_CONVERSION_QUEUE_NAME = "rfdetr-conversions"
RFDETR_CONVERSION_TASK_KIND = "rfdetr-conversion"


def _build_rfdetr_runtime_target(payload: dict, checkpoint_key: str) -> RuntimeTargetSnapshot:
    """构建 RF-DETR 转换所需的简化 RuntimeTargetSnapshot。"""
    input_size = payload.get("input_size", [384, 384])
    if isinstance(input_size, (list, tuple)) and len(input_size) == 2:
        input_size_tuple = (int(input_size[0]), int(input_size[1]))
    else:
        input_size_tuple = (384, 384)

    checkpoint_path = Path(checkpoint_key) if checkpoint_key else Path("")

    return RuntimeTargetSnapshot(
        project_id=payload.get("project_id", ""),
        model_id=payload.get("model_id", ""),
        model_version_id=payload.get("source_model_version_id", ""),
        model_build_id=None,
        model_name=f"rfdetr-{payload.get('model_scale', 'nano')}",
        model_scale=payload.get("model_scale", "nano"),
        task_type="detection",
        source_kind="training",
        runtime_profile_id=None,
        runtime_backend="pytorch",
        device_name="cpu",
        runtime_precision=payload.get("precision", "fp32"),
        input_size=input_size_tuple,
        labels=(),
        runtime_artifact_file_id="",
        runtime_artifact_storage_uri="",
        runtime_artifact_path=checkpoint_path,
        runtime_artifact_file_type="rfdetr-checkpoint",
        checkpoint_file_id=None,
        checkpoint_storage_uri=None,
        checkpoint_path=checkpoint_path,
        labels_storage_uri=None,
    )


class RfdetrConversionQueueWorker:
    """消费 RF-DETR 转换队列。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        conversion_runner: ConversionBackend | None = None,
        worker_id: str = "rfdetr-conversion-worker",
    ) -> None:
        """初始化 RF-DETR 转换队列 worker。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地文件存储服务。
        - queue_backend：队列后端。
        - conversion_runner：可选转换执行器。
        - worker_id：worker 标识。
        """
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.conversion_runner = conversion_runner
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条 RF-DETR 转换队列任务。"""
        queue_task = self.queue_backend.claim_next(
            queue_name=RFDETR_CONVERSION_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False

        try:
            task_id = self._read_task_id(queue_task)
            task_service = SqlAlchemyTaskService(session_factory=self.session_factory)

            # 记录开始事件
            task_service.append_task_event(AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="RF-DETR 转换开始",
                payload={"state": "running", "stage": "converting"},
            ))

            # 获取任务元数据
            task = task_service.get_task(task_id)
            payload = (task.metadata or {}).get("queue_payload", {})

            runner = self.conversion_runner or LocalRfdetrConversionRunner(
                dataset_storage=self.dataset_storage,
            )

            # 构建输出目录前缀
            output_prefix = f"task-runs/{task_id}/conversions"

            # 获取 checkpoint 路径
            checkpoint_key = payload.get("checkpoint_object_key", "")
            source_model_version_id = payload.get("source_model_version_id", "")

            # 构建 runtime target
            runtime_target = _build_rfdetr_runtime_target(payload, checkpoint_key)

            # 执行转换
            run_result = runner.run_conversion(ConversionBackendRunRequest(
                conversion_task_id=task_id,
                source_runtime_target=runtime_target,
                target_formats=(payload.get("target_format", "onnx"),),
                plan_steps=(),  # RF-DETR 转换不需要 plan_steps
                output_object_prefix=output_prefix,
                model_type="rfdetr",
                task_type="detection",
                metadata={
                    "queue_task_id": queue_task.task_id,
                    "checkpoint_object_key": checkpoint_key,
                    "target_format": payload.get("target_format", "onnx"),
                    "precision": payload.get("precision", "fp32"),
                    "model_scale": payload.get("model_scale", "nano"),
                    "num_classes": payload.get("num_classes", 80),
                    "input_size": payload.get("input_size", [384, 384]),
                    "source_model_version_id": source_model_version_id,
                },
            ))

            # 从 metadata 中提取报告信息
            report_object_key = run_result.metadata.get("report_object_key", "")
            produced_formats = run_result.metadata.get("produced_formats", [])

            # 记录完成事件
            task_service.append_task_event(AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="RF-DETR 转换完成",
                payload={
                    "state": "succeeded",
                    "output_object_prefix": output_prefix,
                    "report_object_key": report_object_key,
                    "produced_formats": produced_formats,
                    "outputs": [
                        {"target_format": o.target_format, "object_uri": o.object_uri, "file_type": o.file_type}
                        for o in run_result.outputs
                    ],
                },
            ))

        except ServiceError as error:
            self.queue_backend.fail(
                queue_task,
                error_message=error.message,
                metadata={
                    "task_id": queue_task.payload.get("task_id"),
                    "source_model_version_id": queue_task.metadata.get("source_model_version_id"),
                },
            )
            return True
        except Exception as error:
            self.queue_backend.fail(
                queue_task,
                error_message=str(error),
                metadata={
                    "task_id": queue_task.payload.get("task_id"),
                    "source_model_version_id": queue_task.metadata.get("source_model_version_id"),
                    "error_type": error.__class__.__name__,
                },
            )
            return True

        self.queue_backend.complete(
            queue_task,
            metadata={
                "task_id": run_result.conversion_task_id,
                "status": "succeeded",
                "source_model_version_id": source_model_version_id,
                "output_object_prefix": output_prefix,
                "report_object_key": report_object_key,
                "produced_formats": produced_formats,
                "build_count": len(run_result.outputs),
            },
        )
        return True

    @staticmethod
    def _read_task_id(queue_task: QueueMessage) -> str:
        """从队列负载中读取转换任务 id。"""
        import json

        payload = queue_task.payload
        if isinstance(payload, dict):
            task_id = payload.get("task_id")
        else:
            task_id = json.loads(payload).get("task_id")

        if not isinstance(task_id, str) or not task_id.strip():
            raise InvalidRequestError(
                "转换队列任务缺少 task_id",
                details={"queue_task_id": queue_task.task_id},
            )
        return task_id
