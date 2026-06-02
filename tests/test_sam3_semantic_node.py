"""SAM3 semantic-segment 节点测试。"""

from __future__ import annotations

from types import SimpleNamespace

from PIL import Image

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.nodes import semantic_segment


def test_semantic_segment_returns_regions_and_summary(monkeypatch) -> None:
    """验证 semantic 节点会返回 regions 与 summary。"""

    captured: dict[str, object] = {}

    class _FakeSession:
        def predict(self, *, image_bytes: bytes, prompt_items):
            captured["image_bytes_length"] = len(image_bytes)
            captured["prompt_items"] = prompt_items
            return SimpleNamespace(
                regions=(
                    SimpleNamespace(
                        region_id="region-1",
                        score=0.88,
                        class_id=0,
                        class_name="缺陷区域",
                        bbox_xyxy=(10.0, 16.0, 50.0, 54.0),
                        polygon_xy=((10.0, 16.0), (50.0, 16.0), (50.0, 54.0), (10.0, 54.0)),
                        area=1520,
                        prompt_id="prompt-1",
                        source_prompt_text="defect region",
                        source_prompt_positive_texts=("defect region",),
                        source_prompt_negative_texts=(),
                        mask_png_bytes=_build_test_png_bytes(width=64, height=64),
                        mask_width=64,
                        mask_height=64,
                    ),
                ),
                summary={
                    "project_native": True,
                    "model_scale": "l",
                    "variant_name": "default",
                    "checkpoint_path": "fake-sam3.pt",
                    "device": "cpu",
                    "precision": "fp32",
                    "prompt_count": 1,
                    "prompt_item_count": 1,
                    "prompt_group_count": 1,
                    "positive_prompt_count": 1,
                    "negative_prompt_count": 0,
                    "negative_prompt_weight": 0.5,
                    "prompt_texts": ["defect region"],
                    "prompt_groups": [
                        {
                            "prompt_id": "prompt-1",
                            "display_name": "缺陷区域",
                            "positive_texts": ["defect region"],
                            "negative_texts": [],
                            "languages": [],
                        }
                    ],
                    "region_count": 1,
                    "inference_mode": "semantic-segment",
                    "text_encoder": "checkpoint-language-backbone",
                },
            )

    def _fake_get_or_create_session(*, model_scale: str, device: str, precision: str):
        captured["session_kwargs"] = {
            "model_scale": model_scale,
            "device": device,
            "precision": precision,
        }
        return _FakeSession()

    monkeypatch.setattr(
        semantic_segment,
        "get_or_create_sam3_semantic_runtime_session",
        _fake_get_or_create_session,
    )

    image_payload, image_registry = _build_test_image_payload(width=96, height=72)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-semantic",
        node_definition=SimpleNamespace(node_type_id=semantic_segment.NODE_TYPE_ID),
        parameters={
            "model_scale": "l",
            "device": "cpu",
            "precision": "fp32",
        },
        input_values={
            "image": image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-1",
                        "text": "defect region",
                        "display_name": "缺陷区域",
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = semantic_segment.handle_node(request)

    assert captured["session_kwargs"] == {
        "model_scale": "l",
        "device": "cpu",
        "precision": "fp32",
    }
    assert output["regions"]["count"] == 1
    assert output["regions"]["items"][0]["class_name"] == "缺陷区域"
    assert output["regions"]["items"][0]["source_prompt_positive_texts"] == ["defect region"]
    assert output["summary"]["project_native"] is True
    assert output["summary"]["inference_mode"] == "semantic-segment"
    assert output["summary"]["prompt_ids"] == ["prompt-1"]
    assert output["summary"]["prompt_items"][0]["negative"] is False


def test_semantic_segment_runs_project_native_smoke() -> None:
    """验证 semantic 节点会加载本地 project-native runtime。"""

    image_payload, image_registry = _build_test_image_payload(width=128, height=96)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-semantic-real-smoke",
        node_definition=SimpleNamespace(node_type_id=semantic_segment.NODE_TYPE_ID),
        parameters={
            "model_scale": "l",
            "device": "cpu",
            "precision": "fp32",
        },
        input_values={
            "image": image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-1",
                        "text": "object",
                        "display_name": "object",
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = semantic_segment.handle_node(request)

    assert output["summary"]["project_native"] is True
    assert output["summary"]["inference_mode"] == "semantic-segment"
    assert output["summary"]["prompt_count"] == 1
    assert output["summary"]["region_count"] == output["regions"]["count"]
    assert output["summary"]["postprocess_profile"] == "sam3-default-v2"


def test_semantic_segment_runs_project_native_smoke_with_negative_prompt_group() -> None:
    """验证 SAM3 semantic runtime 支持同一 prompt_id 下的正负文本组合。"""

    image_payload, image_registry = _build_test_image_payload(width=128, height=96)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-semantic-negative-smoke",
        node_definition=SimpleNamespace(node_type_id=semantic_segment.NODE_TYPE_ID),
        parameters={
            "model_scale": "l",
            "device": "cpu",
            "precision": "fp32",
        },
        input_values={
            "image": image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-1",
                        "text": "object",
                        "display_name": "object",
                    },
                    {
                        "prompt_id": "prompt-1",
                        "text": "background",
                        "display_name": "object",
                        "negative": True,
                    },
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = semantic_segment.handle_node(request)

    assert output["summary"]["project_native"] is True
    assert output["summary"]["prompt_count"] == 1
    assert output["summary"]["prompt_item_count"] == 2
    assert output["summary"]["prompt_group_count"] == 1
    assert output["summary"]["positive_prompt_count"] == 1
    assert output["summary"]["negative_prompt_count"] == 1
    assert output["summary"]["negative_prompt_weight"] == 0.5
    assert output["summary"]["prompt_groups"][0]["positive_texts"] == ["object"]
    assert output["summary"]["prompt_groups"][0]["negative_texts"] == ["background"]


def _build_test_image_payload(*, width: int, height: int) -> tuple[dict[str, object], ExecutionImageRegistry]:
    """构造测试图片 payload。"""

    image_bytes = _build_test_png_bytes(width=width, height=height)
    image_registry = ExecutionImageRegistry()
    registered_image = image_registry.register_image_bytes(
        content=image_bytes,
        media_type="image/png",
        width=width,
        height=height,
        created_by_node_id="fixture",
    )
    return (
        build_memory_image_payload(
            image_handle=registered_image.image_handle,
            media_type="image/png",
            width=width,
            height=height,
        ),
        image_registry,
    )


def _build_test_png_bytes(*, width: int = 96, height: int = 72) -> bytes:
    """构造测试 PNG 图片。"""

    import io

    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
