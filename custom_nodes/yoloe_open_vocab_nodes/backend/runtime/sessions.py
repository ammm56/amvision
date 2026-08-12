"""YOLOE runtime session 创建与释放入口。"""

from __future__ import annotations

from typing import Any

from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.prompt_free import (
    YoloePromptFreeRuntimeSession,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.text_prompt import (
    YoloeTextPromptRuntimeSession,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.visual_prompt import (
    YoloeVisualPromptRuntimeSession,
)


def create_text_prompt_runtime_session(
    *, variant: Any, device_name: str, precision: str
) -> object:
    """创建一个 YOLOE text-prompt runtime session。"""

    return YoloeTextPromptRuntimeSession.load(
        variant=variant,
        device_name=device_name,
        precision=precision,
    )


def create_prompt_free_runtime_session(
    *, variant: Any, device_name: str, precision: str
) -> object:
    """创建一个 YOLOE prompt-free runtime session。"""

    return YoloePromptFreeRuntimeSession.load(
        variant=variant,
        device_name=device_name,
        precision=precision,
    )


def create_visual_prompt_runtime_session(
    *, variant: Any, device_name: str, precision: str
) -> object:
    """创建一个 YOLOE visual-prompt runtime session。"""

    return YoloeVisualPromptRuntimeSession.load(
        variant=variant,
        device_name=device_name,
        precision=precision,
    )


def close_runtime_session(session: object) -> None:
    """释放一个 YOLOE session 持有的模型设备资源。"""

    model = getattr(session, "model", None)
    if model is not None:
        move_to_cpu = getattr(model, "cpu", None)
        if callable(move_to_cpu):
            move_to_cpu()


__all__ = [
    "close_runtime_session",
    "create_prompt_free_runtime_session",
    "create_text_prompt_runtime_session",
    "create_visual_prompt_runtime_session",
]
