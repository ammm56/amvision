"""classification 预览图渲染测试。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from backend.service.application.models.inference.classification_inference_payloads import (
    CLASSIFICATION_INFERENCE_INPUT_SOURCE_MULTIPART,
    CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_MEMORY,
    ClassificationNormalizedInferenceInput,
    build_classification_prediction_request,
)
from backend.service.application.runtime.predictors.classification_preview import (
    render_classification_preview_image_if_requested,
)


@dataclass(frozen=True)
class _Category:
    class_id: int
    class_name: str | None
    probability: float


class _FakeCv2:
    FONT_HERSHEY_SIMPLEX = 0
    LINE_AA = 16
    BORDER_CONSTANT = 0

    def __init__(self) -> None:
        self.drawn_lines: list[str] = []
        self.encoded_image: object | None = None

    def getTextSize(
        self, text: str, font_face: int, font_scale: float, thickness: int,
    ) -> tuple[tuple[int, int], int]:
        del font_face, font_scale, thickness
        return ((len(text) * 10, 12), 2)

    def copyMakeBorder(
        self,
        image: np.ndarray,
        top: int,
        bottom: int,
        left: int,
        right: int,
        border_type: int,
        *,
        value: tuple[int, int, int],
    ) -> np.ndarray:
        del border_type, value
        return np.pad(image, ((top, bottom), (left, right), (0, 0)))

    def putText(
        self,
        image: np.ndarray,
        text: str,
        origin: tuple[int, int],
        font_face: int,
        font_scale: float,
        color: tuple[int, int, int],
        thickness: int,
        line_type: int,
    ) -> np.ndarray:
        del origin, font_face, font_scale, color, thickness, line_type
        self.drawn_lines.append(text)
        return image

    def imencode(self, extension: str, image: object) -> tuple[bool, np.ndarray]:
        assert extension == ".jpg"
        self.encoded_image = image
        return True, np.frombuffer(b"encoded", dtype=np.uint8)


@pytest.mark.parametrize(
    ("save_result_image", "return_preview_image_base64"),
    ((True, False), (False, True), (True, True)),
)
def test_any_preview_output_enables_runtime_result_drawing(
    save_result_image: bool,
    return_preview_image_base64: bool,
) -> None:
    """验证保存图片或返回 base64 都会开启 runtime 结果绘制。"""

    request = build_classification_prediction_request(
        normalized_input=ClassificationNormalizedInferenceInput(
            input_uri="memory://classification-preview",
            input_source_kind=CLASSIFICATION_INFERENCE_INPUT_SOURCE_MULTIPART,
            input_image_bytes=b"image",
            input_transport_mode=CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_MEMORY,
        ),
        top_k=5,
        save_result_image=save_result_image,
        return_preview_image_base64=return_preview_image_base64,
        extra_options={},
    )

    assert request.save_result_image is True


def test_no_preview_output_disables_runtime_result_drawing() -> None:
    """验证不生成任何预览输出时关闭 runtime 图片处理。"""

    request = build_classification_prediction_request(
        normalized_input=ClassificationNormalizedInferenceInput(
            input_uri="memory://classification-preview",
            input_source_kind=CLASSIFICATION_INFERENCE_INPUT_SOURCE_MULTIPART,
            input_image_bytes=b"image",
            input_transport_mode=CLASSIFICATION_INFERENCE_INPUT_TRANSPORT_MEMORY,
        ),
        top_k=5,
        save_result_image=False,
        return_preview_image_base64=False,
        extra_options={},
    )

    assert request.save_result_image is False


def test_classification_preview_skips_all_image_work_when_not_requested() -> None:
    """验证生产默认路径不复制、不测量、不编码图片。"""

    cv2_module = _FakeCv2()

    result = render_classification_preview_image_if_requested(
        cv2_module=cv2_module,
        image=object(),
        categories=(),
        save_result_image=False,
    )

    assert result is None
    assert cv2_module.drawn_lines == []
    assert cv2_module.encoded_image is None


def test_classification_saved_preview_also_draws_result() -> None:
    """验证任一种预览图请求都会绘制分类结果。"""

    cv2_module = _FakeCv2()
    image = np.zeros((20, 20, 3), dtype=np.uint8)

    result = render_classification_preview_image_if_requested(
        cv2_module=cv2_module,
        image=image,
        categories=(_Category(0, "class-a", 0.9),),
        save_result_image=True,
    )

    assert result == b"encoded"
    assert "".join(cv2_module.drawn_lines) == "top1 class-a: 0.900"
    assert cv2_module.encoded_image is not image


def test_classification_preview_draws_only_complete_wrapped_top1() -> None:
    """验证低分辨率图片只绘制完整且自动换行的 top1。"""

    cv2_module = _FakeCv2()
    image = np.zeros((30, 50, 3), dtype=np.uint8)
    top1_name = "slot_pcb_surface_complete_name"

    result = render_classification_preview_image_if_requested(
        cv2_module=cv2_module,
        image=image,
        categories=(
            _Category(0, top1_name, 0.9874),
            _Category(1, "must-not-be-drawn", 0.01),
        ),
        save_result_image=True,
    )

    assert result == b"encoded"
    assert len(cv2_module.drawn_lines) > 1
    assert "".join(cv2_module.drawn_lines) == f"top1 {top1_name}: 0.987"
    assert "must-not-be-drawn" not in "".join(cv2_module.drawn_lines)
    assert isinstance(cv2_module.encoded_image, np.ndarray)
    assert cv2_module.encoded_image.shape[0] > image.shape[0]
