"""YOLOE project-native runtime session 缓存。"""

from __future__ import annotations

from threading import Lock
from typing import Any


_PROMPT_FREE_RUNTIME_CACHE: dict[tuple[str, str, str], Any] = {}
_PROMPT_FREE_RUNTIME_CACHE_LOCK = Lock()
_TEXT_PROMPT_RUNTIME_CACHE: dict[tuple[str, str, str], Any] = {}
_TEXT_PROMPT_RUNTIME_CACHE_LOCK = Lock()
_VISUAL_PROMPT_RUNTIME_CACHE: dict[tuple[str, str, str], Any] = {}
_VISUAL_PROMPT_RUNTIME_CACHE_LOCK = Lock()


def get_or_create_prompt_free_runtime_session(
    *,
    variant: Any,
    device_name: str,
    precision: str,
) -> Any:
    """返回可复用的 YOLOE prompt-free project-native 会话。"""

    from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.prompt_free import (
        YoloePromptFreeRuntimeSession,
    )

    cache_key = _build_runtime_cache_key(variant=variant, device_name=device_name, precision=precision)
    with _PROMPT_FREE_RUNTIME_CACHE_LOCK:
        cached_session = _PROMPT_FREE_RUNTIME_CACHE.get(cache_key)
        if cached_session is not None:
            return cached_session
        runtime_session = YoloePromptFreeRuntimeSession.load(
            variant=variant,
            device_name=device_name,
            precision=precision,
        )
        _PROMPT_FREE_RUNTIME_CACHE[cache_key] = runtime_session
        return runtime_session


def get_or_create_text_prompt_runtime_session(
    *,
    variant: Any,
    device_name: str,
    precision: str,
) -> Any:
    """返回可复用的 YOLOE text-prompt project-native 会话。"""

    from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.text_prompt import (
        YoloeTextPromptRuntimeSession,
    )

    cache_key = _build_runtime_cache_key(variant=variant, device_name=device_name, precision=precision)
    with _TEXT_PROMPT_RUNTIME_CACHE_LOCK:
        cached_session = _TEXT_PROMPT_RUNTIME_CACHE.get(cache_key)
        if cached_session is not None:
            return cached_session
        runtime_session = YoloeTextPromptRuntimeSession.load(
            variant=variant,
            device_name=device_name,
            precision=precision,
        )
        _TEXT_PROMPT_RUNTIME_CACHE[cache_key] = runtime_session
        return runtime_session


def get_or_create_visual_prompt_runtime_session(
    *,
    variant: Any,
    device_name: str,
    precision: str,
) -> Any:
    """返回可复用的 YOLOE visual-prompt project-native 会话。"""

    from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.visual_prompt import (
        YoloeVisualPromptRuntimeSession,
    )

    cache_key = _build_runtime_cache_key(variant=variant, device_name=device_name, precision=precision)
    with _VISUAL_PROMPT_RUNTIME_CACHE_LOCK:
        cached_session = _VISUAL_PROMPT_RUNTIME_CACHE.get(cache_key)
        if cached_session is not None:
            return cached_session
        runtime_session = YoloeVisualPromptRuntimeSession.load(
            variant=variant,
            device_name=device_name,
            precision=precision,
        )
        _VISUAL_PROMPT_RUNTIME_CACHE[cache_key] = runtime_session
        return runtime_session


def _build_runtime_cache_key(*, variant: Any, device_name: str, precision: str) -> tuple[str, str, str]:
    """构建 runtime session 缓存键。"""

    return (
        str(variant.checkpoint_path),
        str(device_name).strip().lower(),
        str(precision).strip().lower(),
    )


__all__ = [
    "get_or_create_prompt_free_runtime_session",
    "get_or_create_text_prompt_runtime_session",
    "get_or_create_visual_prompt_runtime_session",
]
