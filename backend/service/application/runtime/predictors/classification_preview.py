"""classification runtime 共用预览图渲染。"""

from __future__ import annotations

from typing import Any, Protocol


class ClassificationPreviewCategory(Protocol):
    """描述预览渲染需要的最小分类结果接口。"""

    class_id: int
    class_name: str | None
    probability: float


_FONT_SCALE = 0.6
_FONT_THICKNESS = 2
_TEXT_LEFT = 12
_TEXT_RIGHT = 12
_LINE_HEIGHT = 24
_TEXT_BOTTOM = 6
_TEXT_COLOR = (40, 180, 120)


def render_classification_preview_image_if_requested(
    *,
    cv2_module: Any,
    image: Any,
    categories: tuple[ClassificationPreviewCategory, ...],
    save_result_image: bool,
) -> bytes | None:
    """仅在请求预览图时生成图片并绘制 top1。"""

    if not save_result_image:
        return None

    top_category = categories[0] if categories else None
    if top_category is None:
        text = "top1 no-result: 0.000"
    else:
        label = top_category.class_name or str(top_category.class_id)
        text = f"top1 {label}: {top_category.probability:.3f}"
    output_image = _draw_wrapped_top1(
        cv2_module=cv2_module,
        image=image,
        text=text,
    )

    ok, encoded = cv2_module.imencode(".jpg", output_image)
    if not ok:
        return None
    return bytes(encoded.tobytes())


def _draw_wrapped_top1(*, cv2_module: Any, image: Any, text: str) -> Any:
    """保持固定字号完整绘制 top1，空间不足时扩展画布并换行。"""

    font_face = cv2_module.FONT_HERSHEY_SIMPLEX
    original_height = int(image.shape[0])
    original_width = int(image.shape[1])
    minimum_text_width = max(
        (
            cv2_module.getTextSize(
                character,
                font_face,
                _FONT_SCALE,
                _FONT_THICKNESS,
            )[0][0]
            for character in set(text)
        ),
        default=1,
    )
    canvas_width = max(
        original_width,
        _TEXT_LEFT + _TEXT_RIGHT + int(minimum_text_width),
    )
    available_text_width = max(1, canvas_width - _TEXT_LEFT - _TEXT_RIGHT)
    lines = _wrap_text_by_pixel_width(
        cv2_module=cv2_module,
        text=text,
        font_face=font_face,
        available_width=available_text_width,
    )
    required_height = _LINE_HEIGHT * len(lines) + _TEXT_BOTTOM
    bottom_padding = max(0, required_height - original_height)
    right_padding = max(0, canvas_width - original_width)
    if bottom_padding or right_padding:
        preview = cv2_module.copyMakeBorder(
            image,
            0,
            bottom_padding,
            0,
            right_padding,
            cv2_module.BORDER_CONSTANT,
            value=(0, 0, 0),
        )
    else:
        preview = image.copy()

    for line_index, line in enumerate(lines, start=1):
        cv2_module.putText(
            preview,
            line,
            (_TEXT_LEFT, _LINE_HEIGHT * line_index),
            font_face,
            _FONT_SCALE,
            _TEXT_COLOR,
            _FONT_THICKNESS,
            cv2_module.LINE_AA,
        )
    return preview


def _wrap_text_by_pixel_width(
    *,
    cv2_module: Any,
    text: str,
    font_face: int,
    available_width: int,
) -> tuple[str, ...]:
    """用二分测量按像素宽度拆行，不删除或缩写任何字符。"""

    if not text:
        return ("",)
    lines: list[str] = []
    offset = 0
    while offset < len(text):
        low = offset + 1
        high = len(text)
        best_end = low
        while low <= high:
            middle = (low + high) // 2
            candidate = text[offset:middle]
            text_width = cv2_module.getTextSize(
                candidate,
                font_face,
                _FONT_SCALE,
                _FONT_THICKNESS,
            )[0][0]
            if text_width <= available_width:
                best_end = middle
                low = middle + 1
            else:
                high = middle - 1
        lines.append(text[offset:best_end])
        offset = best_end
    return tuple(lines)


__all__ = ["render_classification_preview_image_if_requested"]
