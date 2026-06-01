"""YOLOE visual-prompt-detect 节点测试。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes import visual_prompt_detect
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._common import (
    YoloeDetectionPrediction,
    get_or_create_yoloe_visual_prompt_runtime_session,
)


def test_visual_prompt_detect_returns_detection_payload_and_summary(monkeypatch) -> None:
    """验证视觉提示节点会返回 detections 与 summary。"""

    captured: dict[str, object] = {}

    class _FakeSession:
        def predict(
            self,
            *,
            image_bytes: bytes,
            prompt_image_bytes: bytes,
            prompts,
            confidence_threshold: float,
            iou_threshold: float,
            max_detections: int,
        ) -> YoloeDetectionPrediction:
            captured["image_bytes_length"] = len(image_bytes)
            captured["prompt_image_bytes_length"] = len(prompt_image_bytes)
            captured["prompts"] = prompts
            return YoloeDetectionPrediction(
                detections=(
                    {
                        "bbox_xyxy": [8.0, 12.0, 40.0, 44.0],
                        "score": 0.9,
                        "class_id": 0,
                        "class_name": "缺陷A",
                        "prompt_id": "prompt-1",
                    },
                ),
                summary={
                    "model_family": "v8",
                    "model_scale": "s",
                    "variant_name": "v8-default",
                    "checkpoint_path": "fake.pt",
                    "task_type": "segmentation",
                    "prompt_count": 1,
                    "detection_count": 1,
                    "device": "cpu",
                    "precision": "fp32",
                    "confidence_threshold": confidence_threshold,
                    "iou_threshold": iou_threshold,
                    "max_detections": max_detections,
                    "prompt_free": False,
                    "inference_mode": "visual-prompt",
                },
                regions=(
                    {
                        "region_id": "region-1",
                        "bbox_xyxy": [8.0, 12.0, 40.0, 44.0],
                        "score": 0.9,
                        "class_id": 0,
                        "class_name": "缺陷A",
                        "polygon_xy": [[8.0, 12.0], [40.0, 12.0], [40.0, 44.0], [8.0, 44.0]],
                        "area": 1024,
                        "prompt_id": "prompt-1",
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
        visual_prompt_detect,
        "get_or_create_yoloe_visual_prompt_runtime_session",
        _fake_get_or_create_session,
    )

    image_payload, prompt_image_payload, image_registry = _build_test_images()
    request = WorkflowNodeExecutionRequest(
        node_id="node-1",
        node_definition=SimpleNamespace(node_type_id=visual_prompt_detect.NODE_TYPE_ID),
        parameters={
            "model_family": "v8",
            "model_scale": "s",
            "confidence_threshold": 0.3,
            "iou_threshold": 0.6,
            "max_detections": 5,
            "device": "cpu",
            "precision": "fp32",
        },
        input_values={
            "image": image_payload,
            "prompt_image": prompt_image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-1",
                        "display_name": "缺陷A",
                        "prompt_kind": "box",
                        "bbox_xyxy": [10, 10, 32, 32],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = visual_prompt_detect.handle_node(request)

    assert captured["session_kwargs"] == {
        "model_family": "v8",
        "model_scale": "s",
        "device": "cpu",
        "precision": "fp32",
    }
    assert output["detections"]["count"] == 1
    assert output["regions"]["count"] == 1
    assert output["summary"]["prompt_count"] == 1
    assert output["summary"]["prompt_items"][0]["prompt_kind"] == "box"


def test_visual_prompt_detect_rejects_non_box_prompt() -> None:
    """验证第一阶段视觉提示节点拒绝非 box prompt。"""

    image_payload, prompt_image_payload, image_registry = _build_test_images()
    request = WorkflowNodeExecutionRequest(
        node_id="node-invalid",
        node_definition=SimpleNamespace(node_type_id=visual_prompt_detect.NODE_TYPE_ID),
        parameters={"model_family": "v8", "model_scale": "s"},
        input_values={
            "image": image_payload,
            "prompt_image": prompt_image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-1",
                        "prompt_kind": "point",
                        "point_xy": [10, 10],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    try:
        visual_prompt_detect.handle_node(request)
    except Exception as exc:
        assert "只支持 box prompt" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected visual prompt validation error")


def test_visual_prompt_runtime_session_is_not_backfilled_by_external_runtime() -> None:
    """验证 visual-prompt 节点会加载本地 project-native runtime。"""

    runtime_session = get_or_create_yoloe_visual_prompt_runtime_session(
        model_family="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    prediction = runtime_session.predict(
        image_bytes=_build_test_png_bytes(),
        prompt_image_bytes=_build_test_png_bytes(),
        prompts=(
            SimpleNamespace(
                prompt_id="prompt-1",
                prompt_kind="box",
                bbox_xyxy=(8.0, 8.0, 40.0, 40.0),
                display_name="缺陷A",
            ),
        ),
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=5,
    )

    assert prediction.summary["project_native"] is True
    assert prediction.summary["prompt_free"] is False
    assert prediction.summary["variant_name"] == "v8-default"
    assert prediction.summary["prompt_count"] == 1
    assert prediction.summary["visual_prompt_kind"] == "box"
    assert isinstance(prediction.detections, tuple)
    assert isinstance(prediction.regions, tuple)


def _build_test_images() -> tuple[dict[str, object], dict[str, object], ExecutionImageRegistry]:
    """构造 source/prompt 两张测试图。"""

    image_bytes = _build_test_png_bytes()
    prompt_image_bytes = _build_test_png_bytes()
    image_registry = ExecutionImageRegistry()
    source_entry = image_registry.register_image_bytes(
        content=image_bytes,
        media_type="image/png",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )
    prompt_entry = image_registry.register_image_bytes(
        content=prompt_image_bytes,
        media_type="image/png",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )
    return (
        build_memory_image_payload(
            image_handle=source_entry.image_handle,
            media_type="image/png",
            width=64,
            height=64,
        ),
        build_memory_image_payload(
            image_handle=prompt_entry.image_handle,
            media_type="image/png",
            width=64,
            height=64,
        ),
        image_registry,
    )


def _build_test_png_bytes() -> bytes:
    """构造测试 PNG 图片。"""

    import cv2
    import numpy as np

    image = np.full((64, 64, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
