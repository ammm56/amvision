"""YOLOE text-prompt-detect 节点测试。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.nodes.text_encoder_runtime_support import (
    get_or_create_mobileclip_blt_text_encoder,
    resolve_clip_tokenizer_bpe_path,
    resolve_mobileclip_blt_ts_path,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes import text_prompt_detect
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._common import (
    YoloeTextPromptPrediction,
    get_or_create_yoloe_text_prompt_runtime_session,
    merge_text_prompt_items,
    resolve_yoloe_pretrained_variant,
)


def test_resolve_yoloe_pretrained_variant_reads_local_manifest() -> None:
    """验证本地 YOLOE 预训练 manifest 可以被正确解析。"""

    variant = resolve_yoloe_pretrained_variant(
        model_family="v8",
        model_scale="s",
        prompt_free=False,
    )

    assert variant.task_type == "segmentation"
    assert variant.variant_name == "v8-default"
    assert variant.checkpoint_path.name == "yoloe-v8s-seg.pt"
    assert variant.metadata["node_primary_output"] == "detections.v1"


def test_text_prompt_detect_returns_detection_payload_and_summary(monkeypatch) -> None:
    """验证文本提示节点会返回 detections 与 summary。"""

    captured: dict[str, object] = {}

    class _FakeSession:
        def predict(
            self,
            *,
            image_bytes: bytes,
            prompts,
            confidence_threshold: float,
            iou_threshold: float,
            max_detections: int,
        ) -> YoloeTextPromptPrediction:
            captured["image_bytes_length"] = len(image_bytes)
            captured["prompts"] = prompts
            captured["confidence_threshold"] = confidence_threshold
            captured["iou_threshold"] = iou_threshold
            captured["max_detections"] = max_detections
            return YoloeTextPromptPrediction(
                detections=(
                    {
                        "bbox_xyxy": [10.0, 20.0, 30.0, 40.0],
                        "score": 0.95,
                        "class_id": 0,
                        "class_name": "缺陷A",
                        "prompt_id": "prompt-1",
                        "source_prompt_text": "defect-a",
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
                },
                regions=(
                    {
                        "region_id": "region-1",
                        "bbox_xyxy": [10.0, 20.0, 30.0, 40.0],
                        "score": 0.95,
                        "class_id": 0,
                        "class_name": "缺陷A",
                        "polygon_xy": [[10.0, 20.0], [30.0, 20.0], [30.0, 40.0], [10.0, 40.0]],
                        "area": 400,
                        "prompt_id": "prompt-1",
                        "source_prompt_text": "defect-a",
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
        text_prompt_detect,
        "get_or_create_yoloe_text_prompt_runtime_session",
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
        node_id="node-1",
        node_definition=SimpleNamespace(node_type_id=text_prompt_detect.NODE_TYPE_ID),
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
            "image": build_memory_image_payload(
                image_handle=registered_image.image_handle,
                media_type="image/png",
                width=64,
                height=64,
            ),
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-1",
                        "text": "defect-a",
                        "display_name": "缺陷A",
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = text_prompt_detect.handle_node(request)

    assert captured["session_kwargs"] == {
        "model_family": "v8",
        "model_scale": "s",
        "device": "cpu",
        "precision": "fp32",
    }
    assert captured["confidence_threshold"] == 0.3
    assert captured["iou_threshold"] == 0.6
    assert captured["max_detections"] == 5
    assert output["detections"]["count"] == 1
    assert output["detections"]["items"][0]["class_name"] == "缺陷A"
    assert output["regions"]["count"] == 1
    assert output["regions"]["items"][0]["class_name"] == "缺陷A"
    assert output["summary"]["prompt_count"] == 1
    assert output["summary"]["prompt_items"][0]["negative"] is False
    assert output["summary"]["source_image"]["transport_kind"] == "memory"


def test_merge_text_prompt_items_supports_positive_and_negative_groups() -> None:
    """验证文本提示支持按 prompt_id 聚合正负文本。"""

    prompt_groups = merge_text_prompt_items(
        (
            SimpleNamespace(prompt_id="prompt-1", text="person", display_name="person", negative=False, language=None),
            SimpleNamespace(prompt_id="prompt-1", text="human", display_name="person", negative=False, language="en"),
            SimpleNamespace(prompt_id="prompt-1", text="background", display_name="person", negative=True, language="en"),
            SimpleNamespace(prompt_id="prompt-2", text="car", display_name="car", negative=False, language=None),
        )
    )

    assert len(prompt_groups) == 2
    assert prompt_groups[0].prompt_id == "prompt-1"
    assert prompt_groups[0].positive_texts == ("person", "human")
    assert prompt_groups[0].negative_texts == ("background",)
    assert prompt_groups[1].prompt_id == "prompt-2"
    assert prompt_groups[1].positive_texts == ("car",)
    assert prompt_groups[1].negative_texts == ()


def test_local_text_encoder_assets_can_be_loaded() -> None:
    """验证本地 text-encoders 资产可被加载。"""

    assert resolve_clip_tokenizer_bpe_path().name == "bpe_simple_vocab_16e6.txt.gz"
    assert resolve_mobileclip_blt_ts_path().name == "mobileclip_blt.ts"

    text_encoder = get_or_create_mobileclip_blt_text_encoder(device="cpu")
    tokens = text_encoder.tokenize(["person"])
    features = text_encoder.encode_text(tokens)

    assert list(tokens.shape) == [1, 77]
    assert features.ndim == 2
    assert features.shape[0] == 1


def test_text_prompt_runtime_session_runs_project_native_smoke() -> None:
    """验证 text-prompt 节点会加载本地 project-native runtime。"""

    runtime_session = get_or_create_yoloe_text_prompt_runtime_session(
        model_family="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    prediction = runtime_session.predict(
        image_bytes=_build_test_png_bytes(),
        prompts=(
            SimpleNamespace(prompt_id="prompt-1", text="person", display_name="person"),
            SimpleNamespace(prompt_id="prompt-2", text="car", display_name="car"),
        ),
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=5,
    )

    assert prediction.summary["project_native"] is True
    assert prediction.summary["prompt_free"] is False
    assert prediction.summary["variant_name"] == "v8-default"
    assert prediction.summary["prompt_count"] == 2
    assert prediction.summary["prompt_item_count"] == 2
    assert prediction.summary["text_encoder"] == "mobileclip/blt"
    assert isinstance(prediction.detections, tuple)
    assert isinstance(prediction.regions, tuple)


def test_text_prompt_runtime_session_runs_project_native_smoke_with_grouped_negative_prompts() -> None:
    """验证 text-prompt runtime 支持同一 prompt_id 下的正负文本组合。"""

    runtime_session = get_or_create_yoloe_text_prompt_runtime_session(
        model_family="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    prediction = runtime_session.predict(
        image_bytes=_build_test_png_bytes(),
        prompts=(
            SimpleNamespace(prompt_id="prompt-1", text="person", display_name="person", negative=False, language=None),
            SimpleNamespace(prompt_id="prompt-1", text="human", display_name="person", negative=False, language="en"),
            SimpleNamespace(prompt_id="prompt-1", text="background", display_name="person", negative=True, language="en"),
            SimpleNamespace(prompt_id="prompt-2", text="car", display_name="car", negative=False, language=None),
        ),
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=5,
    )

    assert prediction.summary["project_native"] is True
    assert prediction.summary["prompt_count"] == 2
    assert prediction.summary["prompt_item_count"] == 4
    assert prediction.summary["prompt_group_count"] == 2
    assert prediction.summary["positive_prompt_count"] == 3
    assert prediction.summary["negative_prompt_count"] == 1
    assert prediction.summary["negative_prompt_weight"] == 0.5
    assert prediction.summary["prompt_groups"][0]["prompt_id"] == "prompt-1"
    assert prediction.summary["prompt_groups"][0]["positive_texts"] == ["person", "human"]
    assert prediction.summary["prompt_groups"][0]["negative_texts"] == ["background"]
    assert isinstance(prediction.detections, tuple)
    assert isinstance(prediction.regions, tuple)


def _build_test_png_bytes() -> bytes:
    """构造测试 PNG 图片。"""

    import cv2
    import numpy as np

    image = np.full((64, 64, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
