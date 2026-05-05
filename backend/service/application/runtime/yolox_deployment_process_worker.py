"""YOLOX deployment 子进程执行入口。"""

from __future__ import annotations

import os
from threading import BoundedSemaphore, Thread
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceError, ServiceConfigurationError
from backend.service.application.runtime.yolox_inference_runtime_pool import (
    YoloXDeploymentRuntimePool,
    YoloXDeploymentRuntimePoolConfig,
)
from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionRequest,
    serialize_detection,
    serialize_runtime_session_info,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def run_yolox_deployment_process_worker(
    *,
    config: Any,
    dataset_storage_root_dir: str,
    request_queue: Any,
    response_queue: Any,
    operator_thread_count: int,
) -> None:
    """运行单个 deployment 的子进程工作循环。

    参数：
    - config：当前 deployment 进程绑定的稳定配置。
    - dataset_storage_root_dir：本地文件存储根目录。
    - request_queue：父进程发送控制命令与推理请求的队列。
    - response_queue：子进程回传控制结果与推理结果的队列。
    - operator_thread_count：子进程内部推理库允许使用的算子线程数。
    """

    _configure_process_threads(operator_thread_count)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=dataset_storage_root_dir)
    )
    runtime_pool = YoloXDeploymentRuntimePool(dataset_storage=dataset_storage)
    runtime_pool_config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id=config.deployment_instance_id,
        runtime_target=config.runtime_target,
        instance_count=config.instance_count,
    )
    runtime_pool.ensure_deployment(runtime_pool_config)
    infer_slots = BoundedSemaphore(max(1, config.instance_count))

    while True:
        message = request_queue.get()
        if not isinstance(message, dict):
            continue
        request_id = str(message.get("request_id") or "")
        action = str(message.get("action") or "")
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}

        if action == "shutdown":
            _put_ok_response(
                response_queue=response_queue,
                request_id=request_id,
                payload={"state": "stopped", "process_id": os.getpid()},
            )
            return

        if action == "start":
            _put_ok_response(
                response_queue=response_queue,
                request_id=request_id,
                payload=_serialize_health(
                    runtime_pool.get_health(runtime_pool_config),
                ),
            )
            continue

        if action == "warmup":
            try:
                runtime_pool.warmup_deployment(runtime_pool_config)
                _put_ok_response(
                    response_queue=response_queue,
                    request_id=request_id,
                    payload=_serialize_health(
                        runtime_pool.get_health(runtime_pool_config),
                    ),
                )
            except Exception as error:
                _put_error_response(response_queue=response_queue, request_id=request_id, error=error)
            continue

        if action == "health":
            try:
                _put_ok_response(
                    response_queue=response_queue,
                    request_id=request_id,
                    payload=_serialize_health(
                        runtime_pool.get_health(runtime_pool_config),
                    ),
                )
            except Exception as error:
                _put_error_response(response_queue=response_queue, request_id=request_id, error=error)
            continue

        if action == "reset":
            try:
                _put_ok_response(
                    response_queue=response_queue,
                    request_id=request_id,
                    payload=_serialize_health(
                        runtime_pool.reset_deployment(runtime_pool_config),
                    ),
                )
            except Exception as error:
                _put_error_response(response_queue=response_queue, request_id=request_id, error=error)
            continue

        if action == "infer":
            if not infer_slots.acquire(blocking=False):
                _put_error_response(
                    response_queue=response_queue,
                    request_id=request_id,
                    error=InvalidRequestError(
                        "当前 deployment 推理线程已满载，请稍后重试",
                        details={
                            "deployment_instance_id": config.deployment_instance_id,
                            "instance_count": config.instance_count,
                        },
                    ),
                )
                continue
            Thread(
                target=_run_inference_request,
                kwargs={
                    "response_queue": response_queue,
                    "request_id": request_id,
                    "runtime_pool": runtime_pool,
                    "runtime_pool_config": runtime_pool_config,
                    "payload": payload,
                    "infer_slots": infer_slots,
                },
                daemon=True,
                name=f"deployment-infer-{config.deployment_instance_id}",
            ).start()
            continue

        _put_error_response(
            response_queue=response_queue,
            request_id=request_id,
            error=InvalidRequestError(
                "deployment 子进程收到未知命令",
                details={"action": action},
            ),
        )


def _run_inference_request(
    *,
    response_queue: Any,
    request_id: str,
    runtime_pool: YoloXDeploymentRuntimePool,
    runtime_pool_config: YoloXDeploymentRuntimePoolConfig,
    payload: dict[str, object],
    infer_slots: BoundedSemaphore,
) -> None:
    """在独立线程中执行一次 deployment 推理请求。"""

    try:
        execution = runtime_pool.run_inference(
            config=runtime_pool_config,
            request=YoloXPredictionRequest(
                input_uri=_require_payload_str(payload, "input_uri"),
                score_threshold=_require_payload_float(payload, "score_threshold"),
                save_result_image=bool(payload.get("save_result_image") is True),
                extra_options=_read_payload_dict(payload, "extra_options"),
            ),
        )
        _put_ok_response(
            response_queue=response_queue,
            request_id=request_id,
            payload={
                "instance_id": execution.instance_id,
                "detections": [
                    serialize_detection(item)
                    for item in execution.execution_result.detections
                ],
                "latency_ms": execution.execution_result.latency_ms,
                "image_width": execution.execution_result.image_width,
                "image_height": execution.execution_result.image_height,
                "preview_image_bytes": execution.execution_result.preview_image_bytes,
                "runtime_session_info": serialize_runtime_session_info(
                    execution.execution_result.runtime_session_info
                ),
            },
        )
    except Exception as error:
        _put_error_response(response_queue=response_queue, request_id=request_id, error=error)
    finally:
        infer_slots.release()


def _serialize_health(health: object) -> dict[str, object]:
    """把 runtime health 转换为跨进程字典。"""

    return {
        "instance_count": int(getattr(health, "instance_count")),
        "healthy_instance_count": int(getattr(health, "healthy_instance_count")),
        "warmed_instance_count": int(getattr(health, "warmed_instance_count")),
        "instances": [
            {
                "instance_id": item.instance_id,
                "healthy": item.healthy,
                "warmed": item.warmed,
                "busy": item.busy,
                "last_error": item.last_error,
            }
            for item in getattr(health, "instances")
        ],
        "process_id": os.getpid(),
    }


def _configure_process_threads(operator_thread_count: int) -> None:
    """配置 deployment 子进程内部算子线程上限。"""

    thread_count = max(1, int(operator_thread_count))
    os.environ["OMP_NUM_THREADS"] = str(thread_count)
    os.environ["MKL_NUM_THREADS"] = str(thread_count)
    os.environ["OPENBLAS_NUM_THREADS"] = str(thread_count)
    os.environ["NUMEXPR_NUM_THREADS"] = str(thread_count)
    try:
        import cv2  # noqa: PLC0415

        cv2.setNumThreads(thread_count)
    except Exception:
        pass
    try:
        import torch  # noqa: PLC0415

        torch.set_num_threads(thread_count)
        if hasattr(torch, "set_num_interop_threads"):
            torch.set_num_interop_threads(thread_count)
    except Exception:
        pass


def _put_ok_response(*, response_queue: Any, request_id: str, payload: dict[str, object]) -> None:
    """写入成功响应。"""

    response_queue.put({"request_id": request_id, "ok": True, "payload": payload})


def _put_error_response(*, response_queue: Any, request_id: str, error: Exception) -> None:
    """写入失败响应。"""

    if isinstance(error, ServiceError):
        response_queue.put(
            {
                "request_id": request_id,
                "ok": False,
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": dict(error.details),
                },
            }
        )
        return
    response_queue.put(
        {
            "request_id": request_id,
            "ok": False,
            "error": {
                "code": ServiceConfigurationError().code,
                "message": str(error),
                "details": {"error_type": error.__class__.__name__},
            },
        }
    )


def _require_payload_str(payload: dict[str, object], key: str) -> str:
    """从跨进程请求负载中读取必填字符串。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise InvalidRequestError("deployment 推理请求缺少必要字符串字段", details={"field": key})


def _require_payload_float(payload: dict[str, object], key: str) -> float:
    """从跨进程请求负载中读取必填浮点数。"""

    value = payload.get(key)
    if isinstance(value, int | float):
        return float(value)
    raise InvalidRequestError("deployment 推理请求缺少必要数值字段", details={"field": key})


def _read_payload_dict(payload: dict[str, object], key: str) -> dict[str, object]:
    """从跨进程请求负载中读取可选对象字段。"""

    value = payload.get(key)
    if isinstance(value, dict):
        return {str(item_key): item_value for item_key, item_value in value.items()}
    return {}