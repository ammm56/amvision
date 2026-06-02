"""YOLOE visual-prompt-detect 节点测试。"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import torch

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes import visual_prompt_detect
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._common import (
    YoloeDetectionPrediction,
    YoloeVisualPromptItem,
    get_or_create_yoloe_visual_prompt_runtime_session,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._project_native_runtime import _build_visual_prompt_tensor


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
    assert output["summary"]["prompt_items"][0]["raw_item_count"] == 1


def test_visual_prompt_detect_accepts_point_prompt(monkeypatch) -> None:
    """验证视觉提示节点支持 point prompt。"""

    captured = _prepare_visual_prompt_capture(monkeypatch)
    image_payload, prompt_image_payload, image_registry = _build_test_images()
    request = WorkflowNodeExecutionRequest(
        node_id="node-point",
        node_definition=SimpleNamespace(node_type_id=visual_prompt_detect.NODE_TYPE_ID),
        parameters={"model_family": "v8", "model_scale": "s"},
        input_values={
            "image": image_payload,
            "prompt_image": prompt_image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-point",
                        "prompt_kind": "point",
                        "point_xy": [12, 18],
                        "point_label": "positive",
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = visual_prompt_detect.handle_node(request)

    prompt_item = captured["prompts"][0]
    assert prompt_item.prompt_kind == "point"
    assert prompt_item.point_xy == (12.0, 18.0)
    assert prompt_item.point_label == "positive"
    assert output["summary"]["prompt_items"][0]["point_xy"] == [12.0, 18.0]


def test_visual_prompt_detect_accepts_polygon_prompt(monkeypatch) -> None:
    """验证视觉提示节点支持 polygon prompt。"""

    captured = _prepare_visual_prompt_capture(monkeypatch)
    image_payload, prompt_image_payload, image_registry = _build_test_images()
    request = WorkflowNodeExecutionRequest(
        node_id="node-polygon",
        node_definition=SimpleNamespace(node_type_id=visual_prompt_detect.NODE_TYPE_ID),
        parameters={"model_family": "v8", "model_scale": "s"},
        input_values={
            "image": image_payload,
            "prompt_image": prompt_image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-polygon",
                        "prompt_kind": "polygon",
                        "polygon_xy": [[8, 8], [32, 10], [28, 30]],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = visual_prompt_detect.handle_node(request)

    prompt_item = captured["prompts"][0]
    assert prompt_item.prompt_kind == "polygon"
    assert isinstance(prompt_item.prompt_mask, np.ndarray)
    assert int(np.count_nonzero(prompt_item.prompt_mask)) > 0
    assert output["summary"]["prompt_items"][0]["has_prompt_mask"] is True


def test_visual_prompt_detect_accepts_mask_prompt(monkeypatch) -> None:
    """验证视觉提示节点支持 mask prompt。"""

    captured = _prepare_visual_prompt_capture(monkeypatch)
    image_payload, prompt_image_payload, image_registry = _build_test_images()
    mask_payload = _build_mask_image_payload(image_registry)
    request = WorkflowNodeExecutionRequest(
        node_id="node-mask",
        node_definition=SimpleNamespace(node_type_id=visual_prompt_detect.NODE_TYPE_ID),
        parameters={"model_family": "v8", "model_scale": "s"},
        input_values={
            "image": image_payload,
            "prompt_image": prompt_image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-mask",
                        "prompt_kind": "mask",
                        "mask_image": mask_payload,
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = visual_prompt_detect.handle_node(request)

    prompt_item = captured["prompts"][0]
    assert prompt_item.prompt_kind == "mask"
    assert isinstance(prompt_item.prompt_mask, np.ndarray)
    assert int(np.count_nonzero(prompt_item.prompt_mask)) > 0
    assert output["summary"]["prompt_items"][0]["has_prompt_mask"] is True


def test_visual_prompt_detect_merges_same_prompt_id_mixed_prompts(monkeypatch) -> None:
    """验证同一个 prompt_id 下的多种视觉提示会合并成一个 prompt 原型。"""

    captured = _prepare_visual_prompt_capture(monkeypatch)
    image_payload, prompt_image_payload, image_registry = _build_test_images()
    mask_payload = _build_mask_image_payload(image_registry)
    request = WorkflowNodeExecutionRequest(
        node_id="node-mixed",
        node_definition=SimpleNamespace(node_type_id=visual_prompt_detect.NODE_TYPE_ID),
        parameters={"model_family": "v8", "model_scale": "s"},
        input_values={
            "image": image_payload,
            "prompt_image": prompt_image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-mixed",
                        "display_name": "mixed-target",
                        "prompt_kind": "box",
                        "bbox_xyxy": [8, 8, 30, 30],
                    },
                    {
                        "prompt_id": "prompt-mixed",
                        "display_name": "mixed-target",
                        "prompt_kind": "point",
                        "point_xy": [20, 20],
                        "point_label": "positive",
                    },
                    {
                        "prompt_id": "prompt-mixed",
                        "display_name": "mixed-target",
                        "prompt_kind": "mask",
                        "mask_image": mask_payload,
                    },
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = visual_prompt_detect.handle_node(request)

    prompt_item = captured["prompts"][0]
    assert len(captured["prompts"]) == 1
    assert prompt_item.prompt_kind == "mixed"
    assert prompt_item.prompt_kinds == ("box", "mask", "point")
    assert isinstance(prompt_item.prompt_mask, np.ndarray)
    assert int(np.count_nonzero(prompt_item.prompt_mask)) > 0
    assert output["summary"]["prompt_count"] == 1
    assert output["summary"]["prompt_items"][0]["prompt_kind"] == "mixed"
    assert output["summary"]["prompt_items"][0]["prompt_kinds"] == ["box", "mask", "point"]
    assert output["summary"]["prompt_items"][0]["raw_item_count"] == 3
    assert output["summary"]["prompt_items"][0]["has_prompt_mask"] is True


def test_build_visual_prompt_tensor_supports_multiple_prompt_kinds() -> None:
    """验证视觉提示张量构造支持 point、polygon、mask。"""

    polygon_mask = np.zeros((64, 64), dtype=np.uint8)
    polygon_mask[8:24, 8:24] = 1
    explicit_mask = np.zeros((64, 64), dtype=np.uint8)
    explicit_mask[24:48, 24:48] = 1
    visual_tensor = _build_visual_prompt_tensor(
        torch_module=torch,
        np_module=np,
        prompts=(
            YoloeVisualPromptItem(
                prompt_id="box-1",
                prompt_kind="box",
                bbox_xyxy=(4.0, 4.0, 28.0, 28.0),
                point_xy=None,
                point_label=None,
                polygon_xy=None,
                prompt_mask=None,
                display_name="box",
            ),
            YoloeVisualPromptItem(
                prompt_id="point-1",
                prompt_kind="point",
                bbox_xyxy=None,
                point_xy=(20.0, 20.0),
                point_label="positive",
                polygon_xy=None,
                prompt_mask=None,
                display_name="point",
            ),
            YoloeVisualPromptItem(
                prompt_id="polygon-1",
                prompt_kind="polygon",
                bbox_xyxy=None,
                point_xy=None,
                point_label=None,
                polygon_xy=((8.0, 8.0), (32.0, 10.0), (28.0, 30.0)),
                prompt_mask=polygon_mask,
                display_name="polygon",
            ),
            YoloeVisualPromptItem(
                prompt_id="mask-1",
                prompt_kind="mask",
                bbox_xyxy=None,
                point_xy=None,
                point_label=None,
                polygon_xy=None,
                prompt_mask=explicit_mask,
                display_name="mask",
            ),
        ),
        input_size=(640, 640),
        resize_ratio=10.0,
        prompt_image_width=64,
        prompt_image_height=64,
        device_name="cpu",
        dtype=torch.float32,
    )

    assert tuple(visual_tensor.shape) == (1, 4, 80, 80)
    assert float(visual_tensor[0, 0].max().item()) > 0
    assert float(visual_tensor[0, 1].max().item()) > 0
    assert float(visual_tensor[0, 2].max().item()) > 0
    assert float(visual_tensor[0, 3].max().item()) > 0


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
    assert prediction.summary["prompt_item_count"] == 1
    assert prediction.summary["prompt_group_count"] == 1
    assert prediction.summary["visual_prompt_kind"] == "box"
    assert prediction.summary["visual_prompt_kinds"] == ["box"]
    assert prediction.summary["prompt_kind_counts"] == {"box": 1}
    assert prediction.summary["prompt_groups"][0]["prompt_id"] == "prompt-1"
    assert prediction.summary["prompt_groups"][0]["raw_item_count"] == 1
    assert isinstance(prediction.detections, tuple)
    assert isinstance(prediction.regions, tuple)


@pytest.mark.parametrize("prompt_kind", ["point", "polygon", "mask"])
def test_visual_prompt_runtime_session_runs_project_native_smoke_for_extended_prompt_kinds(
    prompt_kind: str,
) -> None:
    """验证 visual-prompt runtime 能用本地权重处理 point、polygon、mask。"""

    runtime_session = get_or_create_yoloe_visual_prompt_runtime_session(
        model_family="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    if prompt_kind == "point":
        prompt_item = YoloeVisualPromptItem(
            prompt_id="prompt-point",
            prompt_kind="point",
            bbox_xyxy=None,
            point_xy=(72.0, 72.0),
            point_label="positive",
            polygon_xy=None,
            prompt_mask=None,
            display_name="point-target",
        )
    elif prompt_kind == "polygon":
        prompt_item = YoloeVisualPromptItem(
            prompt_id="prompt-polygon",
            prompt_kind="polygon",
            bbox_xyxy=None,
            point_xy=None,
            point_label=None,
            polygon_xy=((36.0, 36.0), (112.0, 40.0), (108.0, 108.0), (40.0, 112.0)),
            prompt_mask=_build_polygon_prompt_mask(),
            display_name="polygon-target",
        )
    else:
        prompt_item = YoloeVisualPromptItem(
            prompt_id="prompt-mask",
            prompt_kind="mask",
            bbox_xyxy=None,
            point_xy=None,
            point_label=None,
            polygon_xy=None,
            prompt_mask=_build_dense_prompt_mask(),
            display_name="mask-target",
        )
    image_bytes = _build_visual_prompt_scene_png_bytes()
    prompt_image_bytes = _build_visual_prompt_scene_png_bytes()
    prediction = runtime_session.predict(
        image_bytes=image_bytes,
        prompt_image_bytes=prompt_image_bytes,
        prompts=(prompt_item,),
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=5,
    )

    assert prediction.summary["project_native"] is True
    assert prediction.summary["prompt_free"] is False
    assert prediction.summary["variant_name"] == "v8-default"
    assert prediction.summary["prompt_count"] == 1
    assert prediction.summary["prompt_item_count"] == 1
    assert prediction.summary["visual_prompt_kind"] == prompt_kind
    assert prediction.summary["visual_prompt_kinds"] == [prompt_kind]
    assert prediction.summary["prompt_kind_counts"] == {prompt_kind: 1}
    assert isinstance(prediction.detections, tuple)
    assert isinstance(prediction.regions, tuple)


def test_visual_prompt_runtime_session_runs_project_native_smoke_for_mixed_prompt_item() -> None:
    """验证聚合后的 mixed visual prompt 也能走本地权重链。"""

    runtime_session = get_or_create_yoloe_visual_prompt_runtime_session(
        model_family="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    prompt_item = YoloeVisualPromptItem(
        prompt_id="prompt-mixed",
        prompt_kind="mixed",
        bbox_xyxy=(36.0, 36.0, 116.0, 120.0),
        point_xy=None,
        point_label=None,
        polygon_xy=None,
        prompt_mask=np.maximum(_build_polygon_prompt_mask(), _build_dense_prompt_mask()),
        display_name="mixed-target",
        prompt_kinds=("mask", "point", "polygon"),
        raw_item_count=3,
    )
    image_bytes = _build_visual_prompt_scene_png_bytes()
    prompt_image_bytes = _build_visual_prompt_scene_png_bytes()
    prediction = runtime_session.predict(
        image_bytes=image_bytes,
        prompt_image_bytes=prompt_image_bytes,
        prompts=(prompt_item,),
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=5,
    )

    assert prediction.summary["project_native"] is True
    assert prediction.summary["visual_prompt_kind"] == "mixed"
    assert prediction.summary["visual_prompt_kinds"] == ["mask", "point", "polygon"]
    assert prediction.summary["prompt_item_count"] == 3
    assert prediction.summary["prompt_group_count"] == 1
    assert prediction.summary["prompt_kind_counts"] == {"mask": 1, "point": 1, "polygon": 1}
    assert prediction.summary["prompt_groups"][0]["raw_item_count"] == 3
    assert prediction.summary["prompt_groups"][0]["prompt_kinds"] == ["mask", "point", "polygon"]
    assert isinstance(prediction.detections, tuple)
    assert isinstance(prediction.regions, tuple)


def _prepare_visual_prompt_capture(monkeypatch):
    """构造统一的 visual-prompt monkeypatch 会话。"""

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
                detections=(),
                summary={
                    "model_family": "v8",
                    "model_scale": "s",
                    "variant_name": "v8-default",
                    "checkpoint_path": "fake.pt",
                    "task_type": "segmentation",
                    "prompt_count": len(prompts),
                    "detection_count": 0,
                    "region_count": 0,
                    "device": "cpu",
                    "precision": "fp32",
                    "confidence_threshold": confidence_threshold,
                    "iou_threshold": iou_threshold,
                    "max_detections": max_detections,
                    "prompt_free": False,
                    "inference_mode": "visual-prompt",
                    "project_native": True,
                },
                regions=(),
            )

    monkeypatch.setattr(
        visual_prompt_detect,
        "get_or_create_yoloe_visual_prompt_runtime_session",
        lambda **_kwargs: _FakeSession(),
    )
    return captured


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


def _build_mask_image_payload(image_registry: ExecutionImageRegistry) -> dict[str, object]:
    """构造 mask prompt 使用的 image-ref payload。"""

    mask_image = np.zeros((64, 64), dtype=np.uint8)
    mask_image[16:48, 20:44] = 255
    import cv2

    success, encoded = cv2.imencode(".png", mask_image)
    assert success is True
    entry = image_registry.register_image_bytes(
        content=encoded.tobytes(),
        media_type="image/png",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )
    return build_memory_image_payload(
        image_handle=entry.image_handle,
        media_type="image/png",
        width=64,
        height=64,
    )


def _build_polygon_prompt_mask() -> np.ndarray:
    """构造 polygon smoke 使用的 prompt mask。"""

    polygon_mask = np.zeros((160, 160), dtype=np.uint8)
    polygon_mask[36:112, 36:112] = 1
    return polygon_mask


def _build_dense_prompt_mask() -> np.ndarray:
    """构造 mask smoke 使用的 dense prompt mask。"""

    dense_prompt_mask = np.zeros((160, 160), dtype=np.uint8)
    dense_prompt_mask[40:120, 48:116] = 1
    return dense_prompt_mask


def _build_visual_prompt_scene_png_bytes() -> bytes:
    """构造 visual-prompt 真实 smoke 使用的彩色测试图。"""

    import cv2

    image = np.full((160, 160, 3), 240, dtype=np.uint8)
    cv2.rectangle(image, (36, 36), (116, 116), (0, 160, 255), -1)
    cv2.circle(image, (76, 76), 18, (0, 60, 220), -1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_test_png_bytes() -> bytes:
    """构造测试 PNG 图片。"""

    import cv2
    import numpy as np

    image = np.full((64, 64, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
