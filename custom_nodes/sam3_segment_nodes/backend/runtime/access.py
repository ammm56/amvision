"""SAM3 custom node 的受限 project-native runtime pool。"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from custom_nodes.sam3_segment_nodes.backend.core import (
    Sam3InteractiveRuntimeSession,
    Sam3SemanticRuntimeSession,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.pretrained import (
    normalize_device,
    normalize_model_asset_id,
    normalize_precision,
    resolve_sam3_pretrained_variant,
)


_MAX_RUNTIME_SESSIONS_PER_MODE = 1


@dataclass(frozen=True)
class Sam3RuntimeCacheKey:
    """标识一个可复用的 SAM3 runtime session。"""

    checkpoint_path: str
    model_asset_id: str
    architecture_id: str
    device_name: str
    precision: str


_SAM3_INTERACTIVE_RUNTIME_CACHE: OrderedDict[
    Sam3RuntimeCacheKey, Sam3InteractiveRuntimeSession
] = OrderedDict()
_SAM3_INTERACTIVE_RUNTIME_CACHE_LOCK = Lock()
_SAM3_SEMANTIC_RUNTIME_CACHE: OrderedDict[
    Sam3RuntimeCacheKey, Sam3SemanticRuntimeSession
] = OrderedDict()
_SAM3_SEMANTIC_RUNTIME_CACHE_LOCK = Lock()


def get_or_create_interactive_runtime_session(
    *,
    checkpoint_path: Path,
    model_asset_id: str,
    architecture_id: str,
    device_name: str,
    precision: str,
) -> Sam3InteractiveRuntimeSession:
    """按模型资产、设备和精度返回可复用 interactive session。"""

    cache_key = Sam3RuntimeCacheKey(
        checkpoint_path=str(checkpoint_path),
        model_asset_id=model_asset_id,
        architecture_id=architecture_id,
        device_name=device_name,
        precision=precision,
    )
    with _SAM3_INTERACTIVE_RUNTIME_CACHE_LOCK:
        cached_session = _SAM3_INTERACTIVE_RUNTIME_CACHE.pop(cache_key, None)
        if cached_session is not None:
            _SAM3_INTERACTIVE_RUNTIME_CACHE[cache_key] = cached_session
            return cached_session
        runtime_session = Sam3InteractiveRuntimeSession(
            checkpoint_path=checkpoint_path,
            model_asset_id=model_asset_id,
            architecture_id=architecture_id,
            requested_device_name=device_name,
            precision=precision,
        )
        _SAM3_INTERACTIVE_RUNTIME_CACHE[cache_key] = runtime_session
        _evict_runtime_sessions(_SAM3_INTERACTIVE_RUNTIME_CACHE)
        return runtime_session


def get_or_create_semantic_runtime_session(
    *,
    checkpoint_path: Path,
    model_asset_id: str,
    architecture_id: str,
    device_name: str,
    precision: str,
) -> Sam3SemanticRuntimeSession:
    """按模型资产、设备和精度返回可复用 semantic session。"""

    cache_key = Sam3RuntimeCacheKey(
        checkpoint_path=str(checkpoint_path),
        model_asset_id=model_asset_id,
        architecture_id=architecture_id,
        device_name=device_name,
        precision=precision,
    )
    with _SAM3_SEMANTIC_RUNTIME_CACHE_LOCK:
        cached_session = _SAM3_SEMANTIC_RUNTIME_CACHE.pop(cache_key, None)
        if cached_session is not None:
            _SAM3_SEMANTIC_RUNTIME_CACHE[cache_key] = cached_session
            return cached_session
        runtime_session = Sam3SemanticRuntimeSession(
            checkpoint_path=checkpoint_path,
            model_asset_id=model_asset_id,
            architecture_id=architecture_id,
            requested_device_name=device_name,
            precision=precision,
        )
        _SAM3_SEMANTIC_RUNTIME_CACHE[cache_key] = runtime_session
        _evict_runtime_sessions(_SAM3_SEMANTIC_RUNTIME_CACHE)
        return runtime_session


def get_or_create_sam3_interactive_runtime_session(
    *,
    model_asset_id: str,
    device: str,
    precision: str,
) -> Sam3InteractiveRuntimeSession:
    """按节点参数返回可复用的 SAM3 interactive session。"""

    normalized_asset_id = normalize_model_asset_id(model_asset_id)
    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_sam3_pretrained_variant(model_asset_id=normalized_asset_id)
    return get_or_create_interactive_runtime_session(
        checkpoint_path=variant.checkpoint_path,
        model_asset_id=variant.model_asset_id,
        architecture_id=variant.architecture_id,
        device_name=normalized_device,
        precision=normalized_precision,
    )


def get_or_create_sam3_semantic_runtime_session(
    *,
    model_asset_id: str,
    device: str,
    precision: str,
) -> Sam3SemanticRuntimeSession:
    """按节点参数返回可复用的 SAM3 semantic session。"""

    normalized_asset_id = normalize_model_asset_id(model_asset_id)
    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_sam3_pretrained_variant(model_asset_id=normalized_asset_id)
    return get_or_create_semantic_runtime_session(
        checkpoint_path=variant.checkpoint_path,
        model_asset_id=variant.model_asset_id,
        architecture_id=variant.architecture_id,
        device_name=normalized_device,
        precision=normalized_precision,
    )


def clear_sam3_runtime_caches() -> None:
    """关闭并清空全部 SAM3 runtime session。"""

    with _SAM3_INTERACTIVE_RUNTIME_CACHE_LOCK:
        _close_all_sessions(_SAM3_INTERACTIVE_RUNTIME_CACHE)
    with _SAM3_SEMANTIC_RUNTIME_CACHE_LOCK:
        _close_all_sessions(_SAM3_SEMANTIC_RUNTIME_CACHE)


def _evict_runtime_sessions(cache: OrderedDict[Sam3RuntimeCacheKey, object]) -> None:
    """按 LRU 规则把 runtime pool 控制在固定容量。"""

    while len(cache) > _MAX_RUNTIME_SESSIONS_PER_MODE:
        _cache_key, session = cache.popitem(last=False)
        close = getattr(session, "close", None)
        if callable(close):
            close()


def _close_all_sessions(cache: OrderedDict[Sam3RuntimeCacheKey, object]) -> None:
    """关闭并清空一类 runtime session。"""

    sessions = tuple(cache.values())
    cache.clear()
    for session in sessions:
        close = getattr(session, "close", None)
        if callable(close):
            close()


__all__ = [
    "clear_sam3_runtime_caches",
    "get_or_create_interactive_runtime_session",
    "get_or_create_sam3_interactive_runtime_session",
    "get_or_create_sam3_semantic_runtime_session",
    "get_or_create_semantic_runtime_session",
]
