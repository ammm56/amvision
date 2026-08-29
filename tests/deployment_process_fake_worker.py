"""deployment 进程监督器测试使用的轻量 fake worker。"""

from __future__ import annotations

import os
from queue import Empty
from time import sleep
from typing import Any

from backend.contracts.buffers import BufferLease
from backend.service.application.local_buffers import LocalBufferBrokerClient
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def fake_deployment_process_worker(
    *,
    config: Any,
    dataset_storage_root_dir: str,
    request_queue: Any,
    response_queue: Any,
    operator_thread_count: int,
    supervisor_settings: dict[str, object] | None = None,
    local_buffer_broker_event_channel: Any | None = None,
) -> None:
    """提供可预测响应的 fake deployment 子进程。

    这个函数单独放在轻量 support 模块里，避免 Windows spawn 子进程重新导入完整测试文件。
    """

    del operator_thread_count
    del supervisor_settings
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=dataset_storage_root_dir)
    )
    local_buffer_client = (
        LocalBufferBrokerClient(local_buffer_broker_event_channel)
        if local_buffer_broker_event_channel is not None
        else None
    )

    warmed_instance_indexes: set[int] = set()
    keep_warm_activated = False
    next_instance_index = 0

    while True:
        try:
            message = request_queue.get(timeout=0.2)
        except Empty:
            continue

        request_id = str(message.get("request_id") or "")
        action = str(message.get("action") or "")
        payload = (
            message.get("payload") if isinstance(message.get("payload"), dict) else {}
        )

        if action == "shutdown":
            if local_buffer_client is not None:
                local_buffer_client.close()
            response_queue.put({"request_id": request_id, "ok": True, "payload": {}})
            return
        if action == "start":
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": _build_health_payload(
                        config=config,
                        warmed_instance_indexes=warmed_instance_indexes,
                        keep_warm_activated=keep_warm_activated,
                    ),
                }
            )
            continue
        if action == "warmup":
            if config.deployment_instance_id.endswith("slow-warmup"):
                sleep(0.5)
            for instance_index in range(config.instance_count):
                warmed_instance_indexes.add(instance_index)
            keep_warm_activated = True
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": _build_health_payload(
                        config=config,
                        warmed_instance_indexes=warmed_instance_indexes,
                        keep_warm_activated=keep_warm_activated,
                    ),
                }
            )
            continue
        if action == "health":
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": _build_health_payload(
                        config=config,
                        warmed_instance_indexes=warmed_instance_indexes,
                        keep_warm_activated=keep_warm_activated,
                    ),
                }
            )
            continue
        if action == "reset":
            warmed_instance_indexes.clear()
            keep_warm_activated = False
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": _build_health_payload(
                        config=config,
                        warmed_instance_indexes=warmed_instance_indexes,
                        keep_warm_activated=keep_warm_activated,
                    ),
                }
            )
            continue
        if action == "infer":
            prediction_request = (
                payload.get("prediction_request")
                if isinstance(payload.get("prediction_request"), dict)
                else {}
            )
            instance_index = next_instance_index % config.instance_count
            next_instance_index += 1
            warmed_instance_indexes.add(instance_index)
            preview_image_transfer = None
            if prediction_request.get("save_result_image"):
                lease_payload = payload.get("preview_output_lease")
                preview_content = b"preview-jpg"
                object_key = payload.get("preview_output_object_key")
                if isinstance(object_key, str) and object_key.strip():
                    dataset_storage.write_bytes(object_key, preview_content)
                    preview_image_transfer = {
                        "object_key": object_key,
                        "size": len(preview_content),
                        "media_type": "image/jpeg",
                    }
                else:
                    if not isinstance(lease_payload, dict):
                        raise RuntimeError("fake worker 缺少结果图片输出位置")
                    if local_buffer_client is None:
                        raise RuntimeError("fake worker 缺少 LocalBuffer writer")
                    local_buffer_client.write_lease_bytes(
                        lease=BufferLease.model_validate(lease_payload),
                        content=preview_content,
                    )
                    preview_image_transfer = {
                        "size": len(preview_content),
                        "media_type": "image/jpeg",
                    }
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": {
                        "instance_id": f"{config.deployment_instance_id}:instance-{instance_index}",
                        "execution_result": {
                            "detections": [
                                {
                                    "bbox_xyxy": [8.0, 10.0, 18.0, 22.0],
                                    "score": 0.91,
                                    "class_id": 0,
                                    "class_name": "bolt",
                                }
                            ],
                            "latency_ms": 7.5,
                            "image_width": 64,
                            "image_height": 64,
                            "runtime_session_info": {
                                "backend_name": config.runtime_target.runtime_backend,
                                "model_uri": config.runtime_target.runtime_artifact_storage_uri,
                                "device_name": config.runtime_target.device_name,
                                "input_spec": {
                                    "name": "images",
                                    "shape": [1, 3, 64, 64],
                                    "dtype": "float32",
                                },
                                "output_spec": {
                                    "name": "detections",
                                    "shape": [-1, 7],
                                    "dtype": "float32",
                                },
                                "metadata": {
                                    "model_version_id": config.runtime_target.model_version_id,
                                    "input_transport_kind": (
                                        prediction_request.get("input_image_payload")
                                        or {}
                                    ).get("transport_kind"),
                                    "worker_pid": os.getpid(),
                                },
                            },
                        },
                        "preview_image_transfer": preview_image_transfer,
                    },
                }
            )
            continue
        if action == "infer_batch":
            prediction_requests = payload.get("prediction_requests")
            if not isinstance(prediction_requests, list) or not prediction_requests:
                raise RuntimeError("fake worker 缺少 prediction_requests")
            instance_index = next_instance_index % config.instance_count
            next_instance_index += 1
            warmed_instance_indexes.add(instance_index)
            execution_results = []
            for prediction_request in prediction_requests:
                if not isinstance(prediction_request, dict):
                    raise RuntimeError("fake worker prediction_request 不是 object")
                execution_results.append(
                    {
                        "detections": [
                            {
                                "bbox_xyxy": [8.0, 10.0, 18.0, 22.0],
                                "score": 0.91,
                                "class_id": 0,
                                "class_name": "bolt",
                            }
                        ],
                        "latency_ms": 7.5,
                        "image_width": 64,
                        "image_height": 64,
                        "runtime_session_info": {
                            "backend_name": config.runtime_target.runtime_backend,
                            "model_uri": (
                                config.runtime_target.runtime_artifact_storage_uri
                            ),
                            "device_name": config.runtime_target.device_name,
                            "input_spec": {
                                "name": "images",
                                "shape": [1, 3, 64, 64],
                                "dtype": "float32",
                            },
                            "output_spec": {
                                "name": "detections",
                                "shape": [-1, 7],
                                "dtype": "float32",
                            },
                            "metadata": {
                                "model_version_id": (
                                    config.runtime_target.model_version_id
                                ),
                                "input_transport_kind": (
                                    prediction_request.get("input_image_payload")
                                    or {}
                                ).get("transport_kind"),
                                "worker_pid": os.getpid(),
                            },
                        },
                    }
                )
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": {
                        "instance_id": (
                            f"{config.deployment_instance_id}:instance-{instance_index}"
                        ),
                        "execution_results": execution_results,
                    },
                }
            )
            continue

        response_queue.put(
            {
                "request_id": request_id,
                "ok": False,
                "error": {
                    "code": "invalid_request",
                    "message": "unsupported action",
                    "details": {"action": action},
                },
            }
        )


def _build_health_payload(
    *,
    config: Any,
    warmed_instance_indexes: set[int],
    keep_warm_activated: bool,
) -> dict[str, object]:
    """构建 fake worker 返回的 health 负载。"""

    instances = []
    for instance_index in range(config.instance_count):
        instances.append(
            {
                "instance_id": f"{config.deployment_instance_id}:instance-{instance_index}",
                "healthy": True,
                "warmed": instance_index in warmed_instance_indexes,
                "busy": False,
                "last_error": None,
            }
        )
    return {
        "process_id": os.getpid(),
        "healthy_instance_count": config.instance_count,
        "warmed_instance_count": len(warmed_instance_indexes),
        "pinned_output_total_bytes": len(warmed_instance_indexes) * 524288,
        "instances": instances,
        "keep_warm": {
            "enabled": True,
            "activated": keep_warm_activated,
            "paused": False,
            "idle": True,
            "interval_seconds": 0.1,
            "yield_timeout_seconds": 1.0,
            "success_count": 0,
            "success_count_rollover_count": 0,
            "error_count": 0,
            "error_count_rollover_count": 0,
            "last_error": None,
        },
    }
