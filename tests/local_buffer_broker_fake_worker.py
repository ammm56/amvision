"""LocalBufferBroker 相关 deployment fake worker。"""

from __future__ import annotations

from queue import Empty
from typing import Any

from backend.service.application.local_buffers import LocalBufferBrokerEventChannel


def fake_deployment_worker_records_broker_event_channel(
    *,
    config: Any,
    dataset_storage_root_dir: str,
    request_queue: Any,
    response_queue: Any,
    operator_thread_count: int,
    supervisor_settings: dict[str, object] | None = None,
    local_buffer_broker_event_channel: LocalBufferBrokerEventChannel | None = None,
) -> None:
    """记录 broker event channel 的 fake deployment worker。"""

    del dataset_storage_root_dir
    del operator_thread_count
    del supervisor_settings
    broker_timeout_seconds = (
        local_buffer_broker_event_channel.request_timeout_seconds
        if local_buffer_broker_event_channel is not None
        else 0.0
    )
    while True:
        try:
            message = request_queue.get(timeout=0.2)
        except Empty:
            continue
        request_id = str(message.get("request_id") or "")
        action = str(message.get("action") or "")
        if action == "shutdown":
            response_queue.put({"request_id": request_id, "ok": True, "payload": {}})
            return
        if action == "infer":
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": {
                        "instance_id": f"{config.deployment_instance_id}:instance-0",
                        "execution_result": {
                            "detections": [],
                            "latency_ms": 1.0,
                            "image_width": 1,
                            "image_height": 1,
                            "preview_image_bytes_base64": None,
                            "runtime_session_info": {
                                "backend_name": config.runtime_target.runtime_backend,
                                "model_uri": config.runtime_target.runtime_artifact_storage_uri,
                                "device_name": config.runtime_target.device_name,
                                "input_spec": {"name": "images", "shape": [1, 3, 1, 1], "dtype": "float32"},
                                "output_spec": {"name": "detections", "shape": [0, 7], "dtype": "float32"},
                                "metadata": {"broker_timeout_seconds": broker_timeout_seconds},
                            },
                        },
                    },
                }
            )
            continue
        response_queue.put({"request_id": request_id, "ok": True, "payload": {}})
