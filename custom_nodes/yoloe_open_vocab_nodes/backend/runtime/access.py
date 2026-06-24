"""YOLOE runtime session 获取入口。"""

from __future__ import annotations

from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.pretrained import (
    normalize_device,
    normalize_precision,
    resolve_yoloe_pretrained_variant,
)


def get_or_create_yoloe_text_prompt_runtime_session(
    *,
    model_series: str,
    model_scale: str,
    device: str,
    precision: str,
) -> object:
    """返回可复用的 YOLOE 文本提示推理会话。"""

    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_yoloe_pretrained_variant(
        model_series=model_series,
        model_scale=model_scale,
        prompt_free=False,
    )
    from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.sessions import (
        get_or_create_text_prompt_runtime_session,
    )

    return get_or_create_text_prompt_runtime_session(
        variant=variant,
        device_name=normalized_device,
        precision=normalized_precision,
    )


def get_or_create_yoloe_prompt_free_runtime_session(
    *,
    model_series: str,
    model_scale: str,
    device: str,
    precision: str,
) -> object:
    """返回可复用的 YOLOE prompt-free 推理会话。"""

    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_yoloe_pretrained_variant(
        model_series=model_series,
        model_scale=model_scale,
        prompt_free=True,
    )
    from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.sessions import (
        get_or_create_prompt_free_runtime_session,
    )

    return get_or_create_prompt_free_runtime_session(
        variant=variant,
        device_name=normalized_device,
        precision=normalized_precision,
    )


def get_or_create_yoloe_visual_prompt_runtime_session(
    *,
    model_series: str,
    model_scale: str,
    device: str,
    precision: str,
) -> object:
    """返回可复用的 YOLOE 视觉提示推理会话。"""

    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_yoloe_pretrained_variant(
        model_series=model_series,
        model_scale=model_scale,
        prompt_free=False,
    )
    from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.sessions import (
        get_or_create_visual_prompt_runtime_session,
    )

    return get_or_create_visual_prompt_runtime_session(
        variant=variant,
        device_name=normalized_device,
        precision=normalized_precision,
    )




__all__ = [
    "get_or_create_yoloe_prompt_free_runtime_session",
    "get_or_create_yoloe_text_prompt_runtime_session",
    "get_or_create_yoloe_visual_prompt_runtime_session",
]
