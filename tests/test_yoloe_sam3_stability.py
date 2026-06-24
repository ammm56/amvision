"""YOLOE / SAM3 custom node 稳定性回归测试。"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
import pytest

from backend.service.application.errors import InvalidRequestError
import custom_nodes.sam3_segment_nodes.backend.nodes._common as sam3_common
import custom_nodes.yoloe_open_vocab_nodes.backend.payloads.pretrained as yoloe_pretrained
from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.inputs import (
    read_text_prompt_items as read_yoloe_text_prompt_items,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.access import (
    get_or_create_yoloe_text_prompt_runtime_session,
)


def test_yoloe_resolve_pretrained_variant_rejects_missing_manifest(monkeypatch) -> None:
    """验证 YOLOE 缺失 manifest 时会返回明确错误。"""

    monkeypatch.setattr(
        yoloe_pretrained,
        "YOLOE_PRETRAINED_ROOT",
        Path(__file__).resolve().parents[1] / "data" / "files" / "models" / "pretrained" / "_missing-yoloe",
    )

    with pytest.raises(InvalidRequestError, match="manifest"):
        yoloe_pretrained.resolve_yoloe_pretrained_variant(
            model_series="v8",
            model_scale="s",
            prompt_free=False,
        )


def test_sam3_resolve_pretrained_variant_rejects_missing_manifest(monkeypatch) -> None:
    """验证 SAM3 缺失 manifest 时会返回明确错误。"""

    monkeypatch.setattr(
        sam3_common,
        "SAM3_PRETRAINED_ROOT",
        Path(__file__).resolve().parents[1] / "data" / "files" / "models" / "pretrained" / "_missing-sam3",
    )

    with pytest.raises(InvalidRequestError, match="manifest"):
        sam3_common.resolve_sam3_pretrained_variant(model_scale="l")


def test_yoloe_text_prompt_items_reject_empty_items() -> None:
    """验证 YOLOE 文本提示会拒绝空 items。"""

    with pytest.raises(InvalidRequestError, match="prompts.items"):
        read_yoloe_text_prompt_items({"items": []})


def test_sam3_text_prompt_groups_reject_negative_only_group() -> None:
    """验证 SAM3 semantic 会拒绝只有 negative 文本的 prompt 组。"""

    prompt_items = sam3_common.read_text_prompt_items(
        {
            "items": [
                {
                    "prompt_id": "prompt-1",
                    "text": "background",
                    "display_name": "object",
                    "negative": True,
                }
            ]
        }
    )

    with pytest.raises(InvalidRequestError, match="positive 文本提示"):
        sam3_common.merge_text_prompt_items(prompt_items)


def test_yoloe_text_runtime_session_reuses_cpu_cache() -> None:
    """验证 YOLOE text runtime 在 CPU 上会复用同一会话。"""

    session_a = get_or_create_yoloe_text_prompt_runtime_session(
        model_series="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )
    session_b = get_or_create_yoloe_text_prompt_runtime_session(
        model_series="v8",
        model_scale="s",
        device="cpu",
        precision="fp32",
    )

    assert session_a is session_b

    prediction_a = session_a.predict(
        image_bytes=_build_test_png_bytes(width=80, height=60),
        prompts=(
            _build_namespace(prompt_id="prompt-1", text="person", display_name="person", negative=False, language=None),
            _build_namespace(prompt_id="prompt-1", text="background", display_name="person", negative=True, language=None),
            _build_namespace(prompt_id="prompt-2", text="car", display_name="car", negative=False, language=None),
        ),
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=5,
    )
    prediction_b = session_b.predict(
        image_bytes=_build_test_png_bytes(width=80, height=60),
        prompts=(
            _build_namespace(prompt_id="prompt-1", text="person", display_name="person", negative=False, language=None),
            _build_namespace(prompt_id="prompt-1", text="background", display_name="person", negative=True, language=None),
            _build_namespace(prompt_id="prompt-2", text="car", display_name="car", negative=False, language=None),
        ),
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=5,
    )

    assert prediction_a.summary["prompt_count"] == 2
    assert prediction_a.summary["prompt_item_count"] == 3
    assert prediction_b.summary["prompt_group_count"] == 2


def test_sam3_semantic_runtime_session_reuses_cpu_cache() -> None:
    """验证 SAM3 semantic runtime 在 CPU 上会复用同一会话。"""

    session_a = sam3_common.get_or_create_sam3_semantic_runtime_session(
        model_scale="l",
        device="cpu",
        precision="fp32",
    )
    session_b = sam3_common.get_or_create_sam3_semantic_runtime_session(
        model_scale="l",
        device="cpu",
        precision="fp32",
    )

    assert session_a is session_b

    prompt_groups = sam3_common.merge_text_prompt_items(
        sam3_common.read_text_prompt_items(
            {
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
            }
        )
    )
    prediction_a = session_a.predict(
        image_bytes=_build_test_png_bytes(width=128, height=96),
        prompt_items=prompt_groups,
    )
    prediction_b = session_b.predict(
        image_bytes=_build_test_png_bytes(width=128, height=96),
        prompt_items=prompt_groups,
    )

    assert prediction_a.summary["prompt_count"] == 1
    assert prediction_a.summary["prompt_item_count"] == 2
    assert prediction_b.summary["negative_prompt_count"] == 1
    assert prediction_b.summary["prompt_groups"][0]["negative_texts"] == ["background"]


def _build_namespace(**kwargs):
    """构造带属性访问的简单对象。"""

    from types import SimpleNamespace

    return SimpleNamespace(**kwargs)


def _build_test_png_bytes(*, width: int, height: int) -> bytes:
    """构造测试 PNG 图片。"""

    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
