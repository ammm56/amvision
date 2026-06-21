"""deployment 进程监督器测试使用的轻量 fake worker。"""

from __future__ import annotations

import base64
import os
from queue import Empty
from typing import Any


def fake_deployment_process_worker(
    *,
    config: Any,
    dataset_storage_root_dir: str,
    request_queue: Any,
    response_queue: Any,
    operator_thread_count: int,
    supervisor_settings: dict[str, object] | None = None,
) -> None:
    """提供可预测响应的 fake deployment 子进程。

    这个函数单独放在轻量 support 模块里，避免 Windows spawn 子进程重新导入完整测试文件。
    """

    del dataset_storage_root_dir
    del operator_thread_count
    del supervisor_settings

    warmed_instance_indexes: set[int] = set()
    next_instance_index = 0

    while True:
        try:
            message = request_queue.get(timeout=0.2)
        except Empty:
            continue

        request_id = str(message.get("request_id") or "")
        action = str(message.get("action") or "")
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}

        if action == "shutdown":
            response_queue.put({"request_id": request_id, "ok": True, "payload": {}})
            return
        if action == "start":
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": _build_health_payload(config=config, warmed_instance_indexes=warmed_instance_indexes),
                }
            )
            continue
        if action == "warmup":
            for instance_index in range(config.instance_count):
                warmed_instance_indexes.add(instance_index)
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": _build_health_payload(config=config, warmed_instance_indexes=warmed_instance_indexes),
                }
            )
            continue
        if action == "health":
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": _build_health_payload(config=config, warmed_instance_indexes=warmed_instance_indexes),
                }
            )
            continue
        if action == "reset":
            warmed_instance_indexes.clear()
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": _build_health_payload(config=config, warmed_instance_indexes=warmed_instance_indexes),
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
                            "preview_image_bytes_base64": (
                                base64.b64encode(b"preview-jpg").decode("ascii")
                                if prediction_request.get("save_result_image")
                                else None
                            ),
                            "runtime_session_info": {
                                "backend_name": config.runtime_target.runtime_backend,
                                "model_uri": config.runtime_target.runtime_artifact_storage_uri,
                                "device_name": config.runtime_target.device_name,
                                "input_spec": {"name": "images", "shape": [1, 3, 64, 64], "dtype": "float32"},
                                "output_spec": {"name": "detections", "shape": [-1, 7], "dtype": "float32"},
                                "metadata": {
                                    "model_version_id": config.runtime_target.model_version_id,
                                    "input_uri": prediction_request.get("input_uri"),
                                    "worker_pid": os.getpid(),
                                },
                            },
                        },
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
    }
