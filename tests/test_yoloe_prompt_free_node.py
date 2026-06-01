"""YOLOE prompt-free-detect 节点测试。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes import prompt_free_detect
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._common import (
    YoloeDetectionPrediction,
    get_or_create_yoloe_prompt_free_runtime_session,
    resolve_yoloe_pretrained_variant,
)


def test_resolve_yoloe_pretrained_variant_reads_local_prompt_free_manifest() -> None:
    """验证本地 YOLOE prompt-free manifest 可以被正确解析。"""

    variant = resolve_yoloe_pretrained_variant(
        model_family="v8",
        model_scale="s",
        prompt_free=True,
    )

    assert variant.task_type == "segmentation"
    assert variant.variant_name == "v8-prompt-free"
    assert variant.checkpoint_path.name == "yoloe-v8s-seg-pf.pt"
    assert variant.metadata["node_primary_output"] == "detections.v1"


def test_prompt_free_detect_returns_detection_payload_and_summary(monkeypatch) -> None:
    """验证 prompt-free 节点会返回 detections 与 summary。"""

    captured: dict[str, object] = {}

    class _FakeSession:
        def predict(
            self,
            *,
            image_bytes: bytes,
            confidence_threshold: float,
            iou_threshold: float,
            max_detections: int,
        ) -> YoloeDetectionPrediction:
            captured["image_bytes_length"] = len(image_bytes)
            captured["confidence_threshold"] = confidence_threshold
            captured["iou_threshold"] = iou_threshold
            captured["max_detections"] = max_detections
            return YoloeDetectionPrediction(
                detections=(
                    {
                        "bbox_xyxy": [12.0, 24.0, 60.0, 80.0],
                        "score": 0.87,
                        "class_id": 504,
                        "class_name": "bolt",
                    },
                ),
                summary={
                    "model_family": "v8",
                    "model_scale": "s",
                    "variant_name": "v8-prompt-free",
                    "checkpoint_path": "fake-pf.pt",
                    "task_type": "segmentation",
                    "prompt_count": 0,
                    "detection_count": 1,
                    "device": "cpu",
                    "precision": "fp32",
                    "confidence_threshold": confidence_threshold,
                    "iou_threshold": iou_threshold,
                    "max_detections": max_detections,
                    "prompt_free": True,
                    "inference_mode": "prompt-free",
                    "vocabulary_size": 4585,
                    "top_classes": ["bolt"],
                },
                regions=(
                    {
                        "region_id": "region-1",
                        "bbox_xyxy": [12.0, 24.0, 60.0, 80.0],
                        "score": 0.87,
                        "class_id": 504,
                        "class_name": "bolt",
                        "polygon_xy": [[12.0, 24.0], [60.0, 24.0], [60.0, 80.0], [12.0, 80.0]],
                        "area": 2688,
                    },
                ),
            )

    def _fake_get_or_create_session(*, model_family: str, model_scale: str, device: str, precision: str):
        captured["session_kwargs"] = {
            "model_family": model_family,
            "model_scale": model_scale,
            "device": device,
            "precision": precision,
        }
        return _FakeSession()

    monkeypatch.setattr(
        prompt_free_detect,
        "get_or_create_yoloe_prompt_free_runtime_session",
        _fake_get_or_create_session,
    )

    image_bytes = _build_test_png_bytes()
    image_registry = ExecutionImageRegistry()
    registered_image = image_registry.register_image_bytes(
        content=image_bytes,
        media_type="image/png",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )
    request = WorkflowNodeExecutionRequest(
        node_id="node-prompt-free",
        node_definition=SimpleNamespace(node_type_id=prompt_free_detect.NODE_TYPE_ID),
        parameters={
            "model_family": "v8",
            "model_scale": "s",
            "confidence_threshold": 0.31,
            "iou_threshold": 0.55,
            "max_detections": 8,
            "device": "cpu",
            "precision": "fp32",
        },
        input_values={
            "image": build_memory_image_payload(
                image_handle=registered_image.image_handle,
                media_type="image/png",
                width=64,
                height=64,
            ),
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = prompt_free_detect.handle_node(request)

    assert captured["session_kwargs"] == {
        "model_family": "v8",
        "model_scale": "s",
        "device": "cpu",
        "precision": "fp32",
    }
    assert captured["confidence_threshold"] == 0.31
    assert captured["iou_threshold"] == 0.55
    assert captured["max_detections"] == 8
    assert output["detections"]["count"] == 1
    assert output["detections"]["items"][0]["class_name"] == "bolt"
    assert output["regions"]["count"] == 1
    assert output["regions"]["items"][0]["class_name"] == "bolt"
    assert output["summary"]["prompt_free"] is True
    assert output["summary"]["source_image"]["transport_kind"] == "memory"


def test_prompt_free_runtime_session_runs_project_native_smoke() -> None:
    """验证 prompt-free 节点会加载本地 project-native runtime。"""

    runtime_session = get_or_create_yoloe_prompt_free_runtime_session(
        model_family="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    prediction = runtime_session.predict(
        image_bytes=_build_test_png_bytes(),
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=5,
    )

    assert prediction.summary["project_native"] is True
    assert prediction.summary["prompt_free"] is True
    assert prediction.summary["variant_name"] == "v8-prompt-free"
    assert prediction.summary["vocabulary_size"] > 1000
    assert isinstance(prediction.detections, tuple)
    assert isinstance(prediction.regions, tuple)


def _build_test_png_bytes() -> bytes:
    """构造测试 PNG 图片。"""

    import cv2
    import numpy as np

    image = np.full((256, 256, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
