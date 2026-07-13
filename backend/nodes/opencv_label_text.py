"""OpenCV overlay 文本支撑函数。"""

from __future__ import annotations

import re


_ASCII_SAFE_PATTERN = re.compile(r"^[\x20-\x7E]+$")
_ASCII_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.:-]+")


def build_ascii_overlay_label(
    *parts: object,
    fallback: str = "",
) -> str:
    """构建适合 cv2.putText / 前端 overlay 的 ASCII 标签。

    OpenCV Hershey 字体不能可靠绘制中文，直接传入中文会在图像上显示为一串问号。
    图像调试层优先显示稳定的 ROI ID、index、region ID 等 ASCII 标识；中文 display_name
    继续保留在 payload 数据中给属性面板和值预览使用。
    """

    label_parts: list[str] = []
    for raw_part in parts:
        if raw_part is None:
            continue
        text = str(raw_part).strip()
        if not text:
            continue
        safe_text = _to_ascii_label_token(text)
        if safe_text:
            label_parts.append(safe_text)
    if label_parts:
        return " ".join(label_parts)
    return _to_ascii_label_token(fallback)


def choose_ascii_overlay_name(
    *,
    stable_id: object | None,
    display_name: object | None = None,
    fallback: str = "item",
) -> str:
    """优先选择稳定 ASCII ID，必要时再尝试 display_name。"""

    stable_label = build_ascii_overlay_label(stable_id)
    if stable_label:
        return stable_label
    display_label = build_ascii_overlay_label(display_name)
    if display_label:
        return display_label
    return build_ascii_overlay_label(fallback, fallback=fallback)


def _to_ascii_label_token(text: str) -> str:
    """把文本收敛为 OpenCV 可绘制的 ASCII token。"""

    if _ASCII_SAFE_PATTERN.fullmatch(text):
        return text
    tokens = _ASCII_TOKEN_PATTERN.findall(text)
    return "-".join(token for token in tokens if token)
