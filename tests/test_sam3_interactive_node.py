"""SAM3 interactive-segment 节点测试。"""

from __future__ import annotations

from types import SimpleNamespace

from PIL import Image

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.sam3_segment_nodes.backend.nodes import interactive_segment
from tests.sam3_workflow_session_test_support import (
    patch_interactive_session,
    patch_real_interactive_session,
)


def test_interactive_segment_returns_regions_and_summary(monkeypatch) -> None:
    """验证 interactive 节点会返回 regions 与 summary。"""

    captured: dict[str, object] = {}

    class _FakeSession:
        def predict(
            self,
            *,
            image_bytes: bytes,
            image_payload,
            prompt_items,
            refine_iterations: int,
            **_,
        ):
            captured["image_bytes_length"] = len(image_bytes)
            captured["prompt_items"] = prompt_items
            captured["refine_iterations"] = refine_iterations
            return SimpleNamespace(
                regions=(
                    SimpleNamespace(
                        region_id="region-1",
                        score=0.93,
                        class_id=0,
                        class_name="interactive-region",
                        bbox_xyxy=(8.0, 12.0, 44.0, 52.0),
                        polygon_xy=(
                            (8.0, 12.0),
                            (44.0, 12.0),
                            (44.0, 52.0),
                            (8.0, 52.0),
                        ),
                        area=1440,
                        prompt_id="prompt-1",
                        source_prompt_text=None,
                        mask_png_bytes=_build_test_png_bytes(width=64, height=64),
                        mask_width=64,
                        mask_height=64,
                    ),
                ),
                summary={
                    "project_native": True,
                    "model_asset_id": "sam3/default",
                    "architecture_id": "sam3.1-multiplex.vision-1008.v1",
                    "checkpoint_path": "fake-sam3.1_multiplex.pt",
                    "device": "cpu",
                    "precision": "fp32",
                    "prompt_count": 1,
                    "prompt_kinds": ["box"],
                    "region_count": 1,
                    "inference_mode": "interactive-segment",
                },
            )

    def _fake_get_or_create_session(
        *, model_asset_id: str, device: str, precision: str
    ):
        captured["session_kwargs"] = {
            "model_asset_id": model_asset_id,
            "device": device,
            "precision": precision,
        }
        return _FakeSession()

    patch_interactive_session(
        monkeypatch,
        interactive_segment,
        _fake_get_or_create_session(
            model_asset_id="sam3/default", device="cpu", precision="fp32"
        ),
    )

    image_payload, image_registry = _build_test_image_payload(width=96, height=72)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-interactive",
        node_definition=SimpleNamespace(node_type_id=interactive_segment.NODE_TYPE_ID),
        parameters={
            "model_asset_id": "sam3/default",
            "device": "cpu",
            "precision": "fp32",
        },
        input_values={
            "image": image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-1",
                        "prompt_kind": "box",
                        "display_name": "ROI",
                        "bbox_xyxy": [8, 12, 44, 52],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = interactive_segment.handle_node(request)

    assert captured["session_kwargs"] == {
        "model_asset_id": "sam3/default",
        "device": "cpu",
        "precision": "fp32",
    }
    assert output["regions"]["count"] == 1
    assert output["regions"]["items"][0]["class_name"] == "interactive-region"
    assert output["regions"]["items"][0]["prompt_id"] == "prompt-1"
    assert output["summary"]["project_native"] is True
    assert output["summary"]["inference_mode"] == "interactive-segment"
    assert output["summary"]["prompt_ids"] == ["prompt-1"]
    assert output["summary"]["source_image"]["transport_kind"] == "memory"
    assert captured["refine_iterations"] == 2


def test_interactive_segment_accepts_polygon_prompt(monkeypatch) -> None:
    """验证 interactive 节点会把 polygon prompt 规整后传给 runtime。"""

    captured: dict[str, object] = {}

    class _FakeSession:
        def predict(self, *, image_bytes: bytes, image_payload, prompt_items, **_):
            captured["prompt_items"] = prompt_items
            return SimpleNamespace(
                regions=(),
                summary={
                    "project_native": True,
                    "model_asset_id": "sam3/default",
                    "architecture_id": "sam3.1-multiplex.vision-1008.v1",
                    "checkpoint_path": "fake-sam3.1_multiplex.pt",
                    "device": "cpu",
                    "precision": "fp32",
                    "prompt_count": 1,
                    "prompt_kinds": ["polygon"],
                    "region_count": 0,
                    "inference_mode": "interactive-segment",
                },
            )

    patch_interactive_session(monkeypatch, interactive_segment, _FakeSession())

    image_payload, image_registry = _build_test_image_payload(width=96, height=72)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-interactive-polygon",
        node_definition=SimpleNamespace(node_type_id=interactive_segment.NODE_TYPE_ID),
        parameters={
            "model_asset_id": "sam3/default",
            "device": "cpu",
            "precision": "fp32",
        },
        input_values={
            "image": image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "poly-1",
                        "prompt_kind": "polygon",
                        "display_name": "测试多边形",
                        "polygon_xy": [[12, 8], [64, 10], [68, 42], [14, 48]],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = interactive_segment.handle_node(request)

    prompt_items = captured["prompt_items"]
    assert len(prompt_items) == 1
    assert prompt_items[0].prompt_kind == "polygon"
    assert prompt_items[0].polygon_xy is not None
    assert prompt_items[0].prompt_mask is not None
    assert int(prompt_items[0].prompt_mask.sum()) > 0
    assert output["summary"]["prompt_kinds"] == ["polygon"]


def test_interactive_segment_accepts_mask_prompt(monkeypatch) -> None:
    """验证 interactive 节点会把 mask prompt 规整后传给 runtime。"""

    captured: dict[str, object] = {}

    class _FakeSession:
        def predict(self, *, image_bytes: bytes, image_payload, prompt_items, **_):
            captured["prompt_items"] = prompt_items
            return SimpleNamespace(
                regions=(),
                summary={
                    "project_native": True,
                    "model_asset_id": "sam3/default",
                    "architecture_id": "sam3.1-multiplex.vision-1008.v1",
                    "checkpoint_path": "fake-sam3.1_multiplex.pt",
                    "device": "cpu",
                    "precision": "fp32",
                    "prompt_count": 1,
                    "prompt_kinds": ["mask"],
                    "region_count": 0,
                    "inference_mode": "interactive-segment",
                },
            )

    patch_interactive_session(monkeypatch, interactive_segment, _FakeSession())

    image_payload, image_registry = _build_test_image_payload(width=96, height=72)
    mask_payload = _build_test_mask_payload(
        image_registry=image_registry, width=24, height=18
    )
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-interactive-mask",
        node_definition=SimpleNamespace(node_type_id=interactive_segment.NODE_TYPE_ID),
        parameters={
            "model_asset_id": "sam3/default",
            "device": "cpu",
            "precision": "fp32",
        },
        input_values={
            "image": image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "mask-1",
                        "prompt_kind": "mask",
                        "display_name": "测试遮罩",
                        "mask_image": mask_payload,
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = interactive_segment.handle_node(request)

    prompt_items = captured["prompt_items"]
    assert len(prompt_items) == 1
    assert prompt_items[0].prompt_kind == "mask"
    assert prompt_items[0].prompt_mask is not None
    assert int(prompt_items[0].prompt_mask.sum()) > 0
    assert output["summary"]["prompt_kinds"] == ["mask"]


def test_interactive_segment_runs_project_native_smoke(monkeypatch) -> None:
    """验证 interactive 节点会加载本地 project-native runtime。"""

    image_payload, image_registry = _build_test_image_payload(width=128, height=96)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-real-smoke",
        node_definition=SimpleNamespace(node_type_id=interactive_segment.NODE_TYPE_ID),
        parameters={
            "model_asset_id": "sam3/default",
            "device": "cpu",
            "precision": "fp32",
        },
        input_values={
            "image": image_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "box-1",
                        "prompt_kind": "box",
                        "display_name": "测试框",
                        "bbox_xyxy": [24, 20, 96, 76],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    patch_real_interactive_session(monkeypatch, interactive_segment)
    output = interactive_segment.handle_node(request)

    assert output["summary"]["project_native"] is True
    assert output["summary"]["inference_mode"] == "interactive-segment"
    assert output["summary"]["prompt_kinds"] == ["box"]
    assert output["summary"]["postprocess_profile"] == "sam3-default"
    # 本测试使用本地 smoke checkpoint，权重不保证会把白图判定为存在对象。
    # 真实 SAM3 路径现在会按 object_score_logits 抑制无对象 Mask，因此这里
    # 只验证 project-native 推理闭环和摘要一致性，不伪造必须命中目标的语义。
    assert output["regions"]["count"] == output["summary"]["region_count"]


def _build_test_image_payload(
    *, width: int, height: int
) -> tuple[dict[str, object], ExecutionImageRegistry]:
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


def _build_test_mask_payload(
    *, image_registry: ExecutionImageRegistry, width: int, height: int
) -> dict[str, object]:
    """构造测试 mask image payload。"""

    import io

    from PIL import ImageDraw

    image = Image.new("L", (width, height), color=0)
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, width - 3, height - 3), fill=255)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    registered_image = image_registry.register_image_bytes(
        content=buffer.getvalue(),
        media_type="image/png",
        width=width,
        height=height,
        created_by_node_id="fixture-mask",
    )
    return build_memory_image_payload(
        image_handle=registered_image.image_handle,
        media_type="image/png",
        width=width,
        height=height,
    )
