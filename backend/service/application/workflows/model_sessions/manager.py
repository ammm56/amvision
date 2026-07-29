"""每个 Workflow AppRuntime 独立持有的模型 session 管理器。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
import json
from threading import Lock, RLock
from time import monotonic
from typing import Iterator

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.application.errors import (
    ResourceInUseError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.execution.registry import (
    WorkflowNodeRuntimeRegistry,
)

from .contracts import (
    WorkflowModelSessionLoadResult,
    WorkflowModelSessionProvider,
    WorkflowModelSessionReference,
)


WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY = "workflow_model_session_scope_id"
WORKFLOW_MODEL_SESSION_SCOPE_WAIT_ENABLED_METADATA_KEY = (
    "workflow_model_session_scope_wait_enabled"
)


@dataclass
class WorkflowModelSessionLease:
    """描述一个 loader 节点独占的模型 session 和串行执行锁。"""

    reference: WorkflowModelSessionReference
    provider: WorkflowModelSessionProvider
    load_result: WorkflowModelSessionLoadResult
    configuration_fingerprint: str
    validation_summary: dict[str, object]
    _execution_lock: RLock = field(default_factory=RLock, repr=False)

    @contextmanager
    def locked_session(self, *, capability: str) -> Iterator[object]:
        """按单 session 串行策略返回进程内模型对象。"""

        if capability not in self.reference.capabilities:
            raise ServiceConfigurationError(
                "模型 session 不支持当前节点所需能力",
                details={
                    "loader_node_id": self.reference.loader_node_id,
                    "model_family": self.reference.model_family,
                    "capability": capability,
                    "capabilities": list(self.reference.capabilities),
                },
            )
        with self._execution_lock:
            yield self.load_result.session


class WorkflowModelSessionManager:
    """管理一个进程内、按 scope 隔离的模型 session。"""

    def __init__(self, *, runtime_registry: WorkflowNodeRuntimeRegistry) -> None:
        """初始化空管理器；provider 从当前 runtime registry 动态读取。"""

        self.runtime_registry = runtime_registry
        self._leases: dict[tuple[str, str], WorkflowModelSessionLease] = {}
        self._generation_by_key: dict[tuple[str, str], int] = {}
        self._scope_locks: dict[str, RLock] = {}
        self._scope_last_used_monotonic: dict[str, float] = {}
        self._lock = Lock()

    @contextmanager
    def locked_scope(
        self,
        scope_id: str,
        *,
        wait: bool = True,
    ) -> Iterator[None]:
        """锁定一次完整 graph execution，避免同 scope 运行与重载交错。"""

        normalized_scope_id = _normalize_scope_id(scope_id)
        scope_lock = self._get_scope_lock(normalized_scope_id)
        acquired = scope_lock.acquire(blocking=wait)
        if not acquired:
            raise ResourceInUseError(
                "当前 Workflow App 的 Preview Run 正在执行，请等待完成后重试",
                details={"scope_id": normalized_scope_id},
            )
        try:
            self._touch_scope(normalized_scope_id)
            yield
        finally:
            self._touch_scope(normalized_scope_id)
            scope_lock.release()

    def prepare_template(
        self,
        *,
        scope_id: str,
        template: WorkflowGraphTemplate,
        runtime_context: object,
    ) -> tuple[WorkflowModelSessionReference, ...]:
        """按图中 loader 顺序串行完成加载、warmup 和输出验证。"""

        normalized_scope_id = _normalize_scope_id(scope_id)
        with self.locked_scope(normalized_scope_id):
            return self._prepare_template_in_locked_scope(
                scope_id=normalized_scope_id,
                template=template,
                runtime_context=runtime_context,
            )

    def _prepare_template_in_locked_scope(
        self,
        *,
        scope_id: str,
        template: WorkflowGraphTemplate,
        runtime_context: object,
    ) -> tuple[WorkflowModelSessionReference, ...]:
        """在 scope execution lock 内对齐 loader 集合并准备 session。"""

        nodes_by_id = {node.node_id: node for node in template.nodes if node.enabled}
        outgoing_types: dict[str, list[str]] = {}
        for edge in template.edges:
            source_node = nodes_by_id.get(edge.source_node_id)
            target_node = nodes_by_id.get(edge.target_node_id)
            if source_node is None or target_node is None:
                continue
            outgoing_types.setdefault(source_node.node_id, []).append(
                target_node.node_type_id
            )

        loader_nodes = tuple(
            node
            for node in template.nodes
            if node.enabled
            and self.runtime_registry.get_model_session_provider(node.node_type_id)
            is not None
        )
        expected_loader_node_ids = {node.node_id for node in loader_nodes}
        stale_leases = self._remove_stale_scope_leases(
            scope_id=scope_id,
            expected_loader_node_ids=expected_loader_node_ids,
        )
        for stale_lease in stale_leases:
            self._close_lease(stale_lease)

        prepared: list[WorkflowModelSessionReference] = []
        for loader_node in loader_nodes:
            provider = self.runtime_registry.get_model_session_provider(
                loader_node.node_type_id
            )
            if provider is None:
                continue
            consumer_node_type_ids = tuple(
                sorted(set(outgoing_types.get(loader_node.node_id, ())))
            )
            if not consumer_node_type_ids:
                raise ServiceConfigurationError(
                    "Load Checkpoint 节点没有连接到模型消费节点",
                    details={
                        "loader_node_id": loader_node.node_id,
                        "loader_node_type_id": loader_node.node_type_id,
                    },
                )
            key = (scope_id, loader_node.node_id)
            fingerprint = _build_configuration_fingerprint(
                loader_node=loader_node,
                consumer_node_type_ids=consumer_node_type_ids,
            )
            with self._lock:
                current = self._leases.get(key)
                if (
                    current is not None
                    and current.configuration_fingerprint == fingerprint
                ):
                    prepared.append(current.reference)
                    continue
                if current is not None:
                    self._leases.pop(key, None)
            if current is not None:
                self._close_lease(current)
            load_result: WorkflowModelSessionLoadResult | None = None
            try:
                load_result = provider.load(
                    loader_node=loader_node,
                    consumer_node_type_ids=consumer_node_type_ids,
                    runtime_context=runtime_context,
                )
                warmup_result = provider.warmup(
                    load_result=load_result,
                    consumer_node_type_ids=consumer_node_type_ids,
                    runtime_context=runtime_context,
                )
                validation_summary = provider.validate(
                    load_result=load_result,
                    warmup_result=warmup_result,
                    consumer_node_type_ids=consumer_node_type_ids,
                    runtime_context=runtime_context,
                )
            except Exception:
                if load_result is not None:
                    provider.close(load_result.session)
                self._close_scope_in_locked_scope(scope_id)
                raise
            with self._lock:
                generation = self._generation_by_key.get(key, 0) + 1
                self._generation_by_key[key] = generation
                reference = WorkflowModelSessionReference(
                    scope_id=scope_id,
                    loader_node_id=loader_node.node_id,
                    loader_node_type_id=loader_node.node_type_id,
                    generation=generation,
                    model_family=load_result.model_family,
                    model_asset_id=load_result.model_asset_id,
                    checkpoint_sha256=load_result.checkpoint_sha256,
                    resolved_device=load_result.resolved_device,
                    resolved_precision=load_result.resolved_precision,
                    capabilities=load_result.capabilities,
                )
                lease = WorkflowModelSessionLease(
                    reference=reference,
                    provider=provider,
                    load_result=load_result,
                    configuration_fingerprint=fingerprint,
                    validation_summary=dict(validation_summary),
                )
                self._leases[key] = lease
                prepared.append(reference)
        self._touch_scope(scope_id)
        return tuple(prepared)

    def enforce_scope_limit(
        self,
        *,
        scope_prefix: str,
        current_scope_id: str,
        max_scope_count: int,
    ) -> tuple[str, ...]:
        """在加载当前 scope 前按最近使用顺序回收其他闲置 scope。"""

        normalized_prefix = str(scope_prefix).strip()
        normalized_scope_id = _normalize_scope_id(current_scope_id)
        normalized_limit = int(max_scope_count)
        if not normalized_prefix:
            raise ServiceConfigurationError("Workflow model session scope_prefix 不能为空")
        if normalized_limit <= 0:
            raise ServiceConfigurationError(
                "Workflow model session scope 数量上限必须为正整数"
            )
        with self._lock:
            existing_scope_ids = {
                lease_scope_id
                for lease_scope_id, _loader_node_id in self._leases
                if lease_scope_id.startswith(normalized_prefix)
            }
            candidate_scope_ids = sorted(
                existing_scope_ids - {normalized_scope_id},
                key=lambda item: self._scope_last_used_monotonic.get(item, 0.0),
            )
        retained_other_count = max(0, normalized_limit - 1)
        evict_count = max(0, len(candidate_scope_ids) - retained_other_count)
        evicted: list[str] = []
        for candidate_scope_id in candidate_scope_ids[:evict_count]:
            self.close_scope(candidate_scope_id, wait=False)
            evicted.append(candidate_scope_id)
        self._touch_scope(normalized_scope_id)
        return tuple(evicted)

    def build_reference_payload(
        self, *, scope_id: str, loader_node_id: str
    ) -> dict[str, object]:
        """返回 loader handler 输出的稳定 session 引用。"""

        lease = self._require_lease(
            scope_id=scope_id, loader_node_id=loader_node_id
        )
        return lease.reference.to_payload()

    def resolve_reference(
        self,
        payload: object,
        *,
        expected_model_family: str,
        capability: str,
    ) -> WorkflowModelSessionLease:
        """校验端口引用并解析成当前作用域内的 lease。"""

        if not isinstance(payload, dict):
            raise ServiceConfigurationError("模型节点缺少有效的 model session 引用")
        if payload.get("format_id") != "amvision.workflow-model-session-ref.v1":
            raise ServiceConfigurationError("模型节点收到不支持的 model session 引用")
        scope_id = str(payload.get("scope_id") or "").strip()
        loader_node_id = str(payload.get("loader_node_id") or "").strip()
        lease = self._require_lease(
            scope_id=scope_id, loader_node_id=loader_node_id
        )
        if lease.reference.model_family != expected_model_family:
            raise ServiceConfigurationError(
                "模型 session family 与消费节点不匹配",
                details={
                    "expected": expected_model_family,
                    "actual": lease.reference.model_family,
                },
            )
        if int(payload.get("generation") or -1) != lease.reference.generation:
            raise ServiceConfigurationError("模型 session 引用已失效")
        if capability not in lease.reference.capabilities:
            raise ServiceConfigurationError(
                "模型 session 不支持当前消费节点",
                details={
                    "capability": capability,
                    "capabilities": list(lease.reference.capabilities),
                },
            )
        return lease

    def close_scope(self, scope_id: str, *, wait: bool = True) -> None:
        """关闭一个 scope；非等待模式用于防止删除或切换撞上正在执行的图。"""

        normalized_scope_id = _normalize_scope_id(scope_id)
        scope_lock = self._get_scope_lock(normalized_scope_id)
        acquired = scope_lock.acquire(blocking=wait)
        if not acquired:
            raise ResourceInUseError(
                "当前 Workflow App 的 Preview Run 正在执行，暂不能释放模型",
                details={"scope_id": normalized_scope_id},
            )
        try:
            self._close_scope_in_locked_scope(normalized_scope_id)
        finally:
            scope_lock.release()

    def close_all(self) -> None:
        """关闭管理器中的全部模型 session。"""

        with self._lock:
            scope_ids = tuple(sorted({scope_id for scope_id, _node_id in self._leases}))
        for scope_id in scope_ids:
            self.close_scope(scope_id)

    def build_health_summary(self, *, scope_id: str | None = None) -> dict[str, object]:
        """返回不包含模型对象和路径的健康摘要。"""

        with self._lock:
            leases = tuple(
                lease
                for (lease_scope_id, _node_id), lease in self._leases.items()
                if scope_id is None or lease_scope_id == scope_id
            )
            return {
                "isolation": (
                    "workflow-preview"
                    if scope_id is not None and scope_id.startswith("preview:")
                    else "workflow-runtime"
                ),
                "execution_policy": "single-session-serial",
                "scope_id": scope_id,
                "managed_scope_count": len(
                    {lease_scope_id for lease_scope_id, _node_id in self._leases}
                ),
                "ready_session_count": len(leases),
                "sessions": [
                    {
                        "loader_node_id": lease.reference.loader_node_id,
                        "generation": lease.reference.generation,
                        "model_family": lease.reference.model_family,
                        "model_asset_id": lease.reference.model_asset_id,
                        "device": lease.reference.resolved_device,
                        "precision": lease.reference.resolved_precision,
                        "capabilities": list(lease.reference.capabilities),
                        "state": "ready",
                        "validation": dict(lease.validation_summary),
                    }
                    for lease in leases
                ],
            }

    def _require_lease(
        self, *, scope_id: str, loader_node_id: str
    ) -> WorkflowModelSessionLease:
        with self._lock:
            lease = self._leases.get((scope_id, loader_node_id))
        if lease is None:
            raise ServiceConfigurationError(
                "当前 Workflow runtime 没有就绪的模型 session",
                details={
                    "scope_id": scope_id,
                    "loader_node_id": loader_node_id,
                },
            )
        return lease

    def _get_scope_lock(self, scope_id: str) -> RLock:
        """返回 scope 的长期稳定 RLock，避免替换锁对象造成竞态。"""

        with self._lock:
            return self._scope_locks.setdefault(scope_id, RLock())

    def _touch_scope(self, scope_id: str) -> None:
        """更新 scope 最近使用时间，供 Preview 容量回收使用。"""

        with self._lock:
            self._scope_last_used_monotonic[scope_id] = monotonic()

    def _remove_stale_scope_leases(
        self,
        *,
        scope_id: str,
        expected_loader_node_ids: set[str],
    ) -> tuple[WorkflowModelSessionLease, ...]:
        """移除图中已经删除或禁用的 loader lease。"""

        with self._lock:
            stale_keys = tuple(
                key
                for key in self._leases
                if key[0] == scope_id and key[1] not in expected_loader_node_ids
            )
            return tuple(self._leases.pop(key) for key in stale_keys)

    def _close_scope_in_locked_scope(self, scope_id: str) -> None:
        """调用方持有 scope lock 时移除并关闭全部 lease。"""

        with self._lock:
            keys = tuple(key for key in self._leases if key[0] == scope_id)
            leases = tuple(self._leases.pop(key) for key in keys)
            self._scope_last_used_monotonic.pop(scope_id, None)
        for lease in leases:
            self._close_lease(lease)

    @staticmethod
    def _close_lease(lease: WorkflowModelSessionLease) -> None:
        with lease._execution_lock:
            lease.provider.close(lease.load_result.session)


def _normalize_scope_id(scope_id: object) -> str:
    """规范化并校验 scope id。"""

    normalized_scope_id = str(scope_id or "").strip()
    if not normalized_scope_id:
        raise ServiceConfigurationError("Workflow model session scope_id 不能为空")
    return normalized_scope_id


def _build_configuration_fingerprint(
    *,
    loader_node: object,
    consumer_node_type_ids: tuple[str, ...],
) -> str:
    """构造 loader 参数和直接消费者共同决定的稳定摘要。"""

    payload = {
        "loader_node_type_id": getattr(loader_node, "node_type_id"),
        "parameters": getattr(loader_node, "parameters"),
        "consumer_node_type_ids": list(consumer_node_type_ids),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
