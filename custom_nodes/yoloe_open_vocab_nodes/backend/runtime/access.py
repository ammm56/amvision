"""YOLOE runtime session 有界获取入口。"""

from __future__ import annotations

import atexit

from backend.service.application.runtime.resource_pool import (
    BoundedResourcePool,
    ResourceLease,
)
from backend.service.application.runtime.resource_scope import (
    ResourceScope,
    create_process_resource_scope,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.pretrained import (
    normalize_device,
    normalize_precision,
    resolve_yoloe_pretrained_variant,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.sessions import (
    close_runtime_session,
    create_prompt_free_runtime_session,
    create_text_prompt_runtime_session,
    create_visual_prompt_runtime_session,
)


_YOLOE_POOL_RESOURCE_KEY = "custom.yoloe.runtime-session-pool"
_DEFAULT_PROCESS_SCOPE = create_process_resource_scope()
atexit.register(_DEFAULT_PROCESS_SCOPE.close)


def get_or_create_yoloe_text_prompt_runtime_session(
    *,
    model_series: str,
    model_scale: str,
    device: str,
    precision: str,
    request: WorkflowNodeExecutionRequest | None = None,
) -> ResourceLease[object]:
    """返回 YOLOE 文本提示推理会话 lease。"""

    return _acquire_session(
        mode="text-prompt",
        model_series=model_series,
        model_scale=model_scale,
        device=device,
        precision=precision,
        request=request,
    )


def get_or_create_yoloe_prompt_free_runtime_session(
    *,
    model_series: str,
    model_scale: str,
    device: str,
    precision: str,
    request: WorkflowNodeExecutionRequest | None = None,
) -> ResourceLease[object]:
    """返回 YOLOE prompt-free 推理会话 lease。"""

    return _acquire_session(
        mode="prompt-free",
        model_series=model_series,
        model_scale=model_scale,
        device=device,
        precision=precision,
        request=request,
    )


def get_or_create_yoloe_visual_prompt_runtime_session(
    *,
    model_series: str,
    model_scale: str,
    device: str,
    precision: str,
    request: WorkflowNodeExecutionRequest | None = None,
) -> ResourceLease[object]:
    """返回 YOLOE 视觉提示推理会话 lease。"""

    return _acquire_session(
        mode="visual-prompt",
        model_series=model_series,
        model_scale=model_scale,
        device=device,
        precision=precision,
        request=request,
    )


def _acquire_session(
    *,
    mode: str,
    model_series: str,
    model_scale: str,
    device: str,
    precision: str,
    request: WorkflowNodeExecutionRequest | None,
) -> ResourceLease[object]:
    """规范化配置并从当前进程有界池获取 session。"""

    normalized_device = normalize_device(device)
    normalized_precision = normalize_precision(precision)
    variant = resolve_yoloe_pretrained_variant(
        model_series=model_series,
        model_scale=model_scale,
        prompt_free=mode == "prompt-free",
    )
    pool = _require_pool(_resolve_process_scope(request))
    key = (
        mode,
        str(variant.checkpoint_path),
        normalized_device,
        normalized_precision,
    )
    def factory() -> object:
        """按当前 mode 创建底层 YOLOE session。"""

        if mode == "text-prompt":
            return create_text_prompt_runtime_session(
                variant=variant,
                device_name=normalized_device,
                precision=normalized_precision,
            )
        if mode == "prompt-free":
            return create_prompt_free_runtime_session(
                variant=variant,
                device_name=normalized_device,
                precision=normalized_precision,
            )
        return create_visual_prompt_runtime_session(
            variant=variant,
            device_name=normalized_device,
            precision=normalized_precision,
        )
    return pool.acquire(key, factory, close_runtime_session)


def _resolve_process_scope(
    request: WorkflowNodeExecutionRequest | None,
) -> ResourceScope:
    """优先使用 worker runtime context 持有的进程作用域。"""

    runtime_context = request.runtime_context if request is not None else None
    if isinstance(runtime_context, WorkflowServiceNodeRuntimeContext):
        return runtime_context.process_resource_scope
    return _DEFAULT_PROCESS_SCOPE


def _require_pool(scope: ResourceScope) -> BoundedResourcePool[object]:
    """返回当前进程唯一的 YOLOE 有界 session pool。"""

    resource = scope.get_or_create(
        _YOLOE_POOL_RESOURCE_KEY,
        lambda: BoundedResourcePool(max_entries=8, max_idle_seconds=1800.0),
        lambda value: value.close(),
    )
    if not isinstance(resource, BoundedResourcePool):
        raise RuntimeError("YOLOE session pool 资源类型无效")
    return resource


__all__ = [
    "get_or_create_yoloe_prompt_free_runtime_session",
    "get_or_create_yoloe_text_prompt_runtime_session",
    "get_or_create_yoloe_visual_prompt_runtime_session",
]
