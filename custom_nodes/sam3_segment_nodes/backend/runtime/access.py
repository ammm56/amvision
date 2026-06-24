"""SAM3 custom node 的 project-native runtime 会话缓存。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from custom_nodes.sam3_segment_nodes.backend.core import (
    Sam3InteractiveRuntimeSession,
    Sam3SemanticRuntimeSession,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.pretrained import (
    normalize_device,
    normalize_model_scale,
    normalize_precision,
    resolve_sam3_pretrained_variant,
)


@dataclass(frozen=True)
class Sam3InteractiveRuntimeCacheKey:
    """标识一个可复用的 SAM3 interactive 会话。"""

    checkpoint_path: str
    model_scale: str
    variant_name: str
    device_name: str
    precision: str


_SAM3_INTERACTIVE_RUNTIME_CACHE: dict[Sam3InteractiveRuntimeCacheKey, Sam3InteractiveRuntimeSession] = {}
_SAM3_INTERACTIVE_RUNTIME_CACHE_LOCK = Lock()


@dataclass(frozen=True)
class Sam3SemanticRuntimeCacheKey:
    """标识一个可复用的 SAM3 semantic 会话。"""

    checkpoint_path: str
    model_scale: str
    variant_name: str
    device_name: str
    precision: str


_SAM3_SEMANTIC_RUNTIME_CACHE: dict[Sam3SemanticRuntimeCacheKey, Sam3SemanticRuntimeSession] = {}
_SAM3_SEMANTIC_RUNTIME_CACHE_LOCK = Lock()


def get_or_create_interactive_runtime_session(
    *,
    checkpoint_path: Path,
    model_scale: str,
    variant_name: str,
    device_name: str,
    precision: str,
) -> Sam3InteractiveRuntimeSession:
    """按 checkpoint/device/precision 返回可复用 interactive 会话。"""

    cache_key = Sam3InteractiveRuntimeCacheKey(
        checkpoint_path=str(checkpoint_path),
        model_scale=model_scale,
        variant_name=variant_name,
        device_name=device_name,
        precision=precision,
    )
    with _SAM3_INTERACTIVE_RUNTIME_CACHE_LOCK:
        cached_session = _SAM3_INTERACTIVE_RUNTIME_CACHE.get(cache_key)
        if cached_session is not None:
            return cached_session
        runtime_session = Sam3InteractiveRuntimeSession(
            checkpoint_path=checkpoint_path,
            model_scale=model_scale,
            variant_name=variant_name,
            requested_device_name=device_name,
            precision=precision,
        )
        _SAM3_INTERACTIVE_RUNTIME_CACHE[cache_key] = runtime_session
        return runtime_session


def get_or_create_semantic_runtime_session(
    *,
    checkpoint_path: Path,
    model_scale: str,
    variant_name: str,
    device_name: str,
    precision: str,
) -> Sam3SemanticRuntimeSession:
    """按 checkpoint/device/precision 返回可复用 semantic 会话。"""

    cache_key = Sam3SemanticRuntimeCacheKey(
        checkpoint_path=str(checkpoint_path),
        model_scale=model_scale,
        variant_name=variant_name,
        device_name=device_name,
        precision=precision,
    )
    with _SAM3_SEMANTIC_RUNTIME_CACHE_LOCK:
        cached_session = _SAM3_SEMANTIC_RUNTIME_CACHE.get(cache_key)
        if cached_session is not None:
            return cached_session
        runtime_session = Sam3SemanticRuntimeSession(
            checkpoint_path=checkpoint_path,
            model_scale=model_scale,
            variant_name=variant_name,
            requested_device_name=device_name,
            precision=precision,
        )
        _SAM3_SEMANTIC_RUNTIME_CACHE[cache_key] = runtime_session
        return runtime_session


def get_or_create_sam3_interactive_runtime_session(
    *,
    model_scale: str,
    device: str,
    precision: str,
) -> Sam3InteractiveRuntimeSession:
    """按节点参数返回可复用的 SAM3 interactive 会话。"""

    normalized_scale = normalize_model_scale(model_scale)
    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_sam3_pretrained_variant(model_scale=normalized_scale)
    return get_or_create_interactive_runtime_session(
        checkpoint_path=variant.checkpoint_path,
        model_scale=variant.model_scale,
        variant_name=variant.variant_name,
        device_name=normalized_device,
        precision=normalized_precision,
    )


def get_or_create_sam3_semantic_runtime_session(
    *,
    model_scale: str,
    device: str,
    precision: str,
) -> Sam3SemanticRuntimeSession:
    """按节点参数返回可复用的 SAM3 semantic 会话。"""

    normalized_scale = normalize_model_scale(model_scale)
    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_sam3_pretrained_variant(model_scale=normalized_scale)
    return get_or_create_semantic_runtime_session(
        checkpoint_path=variant.checkpoint_path,
        model_scale=variant.model_scale,
        variant_name=variant.variant_name,
        device_name=normalized_device,
        precision=normalized_precision,
    )


__all__ = [
    "get_or_create_interactive_runtime_session",
    "get_or_create_sam3_interactive_runtime_session",
    "get_or_create_sam3_semantic_runtime_session",
    "get_or_create_semantic_runtime_session",
]
