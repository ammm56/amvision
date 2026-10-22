"""进程与 Workflow 执行期资源的统一生命周期边界。"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from threading import RLock
from typing import Any


WORKFLOW_RESOURCE_SCOPE_METADATA_KEY = "_workflow_resource_scope"


@dataclass(frozen=True)
class ResourceCloseError:
    """描述一个资源关闭失败。"""

    scope_kind: str
    resource_key: str
    error_type: str
    error_message: str

    def to_dict(self) -> dict[str, str]:
        """返回可记录的错误字典。"""

        return {
            "scope_kind": self.scope_kind,
            "resource_key": self.resource_key,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass
class _ResourceRegistration:
    """保存资源对象和对应关闭函数。"""

    key: Hashable
    resource: object
    closer: Callable[[object], Any]
    before_external_cleanup: bool = False


class ResourceScope:
    """以线程安全、逆序和幂等方式管理一组资源。"""

    def __init__(self, *, kind: str) -> None:
        """创建指定类型的空资源作用域。"""

        normalized_kind = kind.strip()
        if not normalized_kind:
            raise ValueError("ResourceScope kind 不能为空")
        self.kind = normalized_kind
        self._lock = RLock()
        self._registrations: dict[Hashable, _ResourceRegistration] = {}
        self._order: list[Hashable] = []
        self._closed = False
        self._close_lock = RLock()
        self._failed: dict[
            Hashable, tuple[_ResourceRegistration, ResourceCloseError]
        ] = {}

    @property
    def closed(self) -> bool:
        """返回当前作用域是否已经关闭。"""

        with self._lock:
            return self._closed

    @property
    def resource_count(self) -> int:
        """返回当前登记资源数量。"""

        with self._lock:
            return len(self._registrations) + len(self._failed)

    def owns(self, resource: object) -> bool:
        """核对真实对象是否由本作用域持有，不按调用方提供的 key 认领。"""
        with self._lock:
            return any(
                item.resource is resource for item in self._registrations.values()
            ) or any(item.resource is resource for item, _ in self._failed.values())

    @property
    def close_errors(self) -> tuple[ResourceCloseError, ...]:
        """返回仍持有的关闭失败；重复 close 不把失败改报为成功。"""
        with self._lock:
            return tuple(error for _, error in self._failed.values())

    def get_or_create(
        self,
        key: Hashable,
        factory: Callable[[], object],
        closer: Callable[[object], Any],
        *,
        before_external_cleanup: bool = False,
    ) -> object:
        """返回已有资源，或在锁内创建并登记新资源。"""

        with self._lock:
            self._require_open()
            existing = self._registrations.get(key)
            if existing is not None:
                return existing.resource
            resource = factory()
            self._registrations[key] = _ResourceRegistration(
                key=key,
                resource=resource,
                closer=closer,
                before_external_cleanup=before_external_cleanup,
            )
            self._order.append(key)
            return resource

    def register(
        self,
        key: Hashable,
        resource: object,
        closer: Callable[[object], Any],
        *,
        before_external_cleanup: bool = False,
    ) -> None:
        """登记一个新资源并拒绝相同 key 的冲突对象。"""

        with self._lock:
            self._require_open()
            existing = self._registrations.get(key)
            if existing is not None:
                if existing.resource is resource:
                    return
                raise RuntimeError(f"ResourceScope 资源 key 冲突: {key!r}")
            self._registrations[key] = _ResourceRegistration(
                key=key,
                resource=resource,
                closer=closer,
                before_external_cleanup=before_external_cleanup,
            )
            self._order.append(key)

    def unregister(self, key: Hashable) -> object | None:
        """解除资源登记但不关闭资源。"""

        with self._lock:
            registration = self._registrations.pop(key, None)
            if registration is None:
                return None
            self._order = [item for item in self._order if item != key]
            return registration.resource

    def close_resource(self, key: Hashable) -> tuple[ResourceCloseError, ...]:
        """关闭单个资源；失败保留对象及原错误，不自动重试 closer。"""
        with self._close_lock:
            with self._lock:
                if key in self._failed:
                    return (self._failed[key][1],)
                registration = self._registrations.pop(key, None)
                if registration is None:
                    return ()
                self._order = [item for item in self._order if item != key]
            error = self._close_and_retain_failure(registration)
            return () if error is None else (error,)

    def close_before_external_cleanup(self) -> tuple[ResourceCloseError, ...]:
        """冻结新登记，先解除声明依赖外部文件/租约的借用。"""
        with self._close_lock:
            with self._lock:
                self._closed = True
                keys = [
                    key
                    for key in reversed(self._order)
                    if self._registrations[key].before_external_cleanup
                ]
            for key in keys:
                self.close_resource(key)
            return self.close_errors

    def close(self) -> tuple[ResourceCloseError, ...]:
        """按登记逆序关闭全部资源；重复调用安全。"""

        with self._close_lock:
            self.close_before_external_cleanup()
            with self._lock:
                keys = list(reversed(self._order))
            for key in keys:
                self.close_resource(key)
            return self.close_errors

    def _require_open(self) -> None:
        """拒绝向已关闭作用域登记资源。"""

        if self._closed or self._failed:
            raise RuntimeError(f"{self.kind} ResourceScope 已关闭")

    def _close_and_retain_failure(
        self, registration: _ResourceRegistration
    ) -> ResourceCloseError | None:
        """失败对象保持强引用，直到所属进程退出；不以 GC 代替释放确认。"""
        error = self._close_registration(registration)
        if error is not None:
            with self._lock:
                self._failed[registration.key] = (registration, error)
        return error

    def retain_failed_scope(self, key: Hashable, scope: ResourceScope) -> None:
        """保留已失败子作用域；并发失败或父作用域关闭时仍不能丢失归属。"""
        if scope is self or not scope.close_errors:
            raise ValueError("只能保留另一个已关闭失败的资源作用域")
        with self._lock:
            if key in self._registrations or key in self._failed:
                raise RuntimeError("失败作用域登记 key 冲突")
            registration = _ResourceRegistration(
                key, scope, lambda value: value.close()
            )
            error = ResourceCloseError(
                self.kind,
                repr(key),
                "ResourceScopeCloseError",
                "子作用域仍有未释放资源",
            )
            self._failed[key] = (registration, error)

    def _close_registration(
        self,
        registration: _ResourceRegistration,
    ) -> ResourceCloseError | None:
        """关闭单个登记项并把异常转换为结构化错误。"""

        try:
            registration.closer(registration.resource)
        except Exception as exc:  # pragma: no cover - 具体失败由调用方故障注入覆盖
            return ResourceCloseError(
                scope_kind=self.kind,
                resource_key=repr(registration.key),
                error_type=type(exc).__name__,
                error_message=str(exc) or type(exc).__name__,
            )
        return None


def create_process_resource_scope() -> ResourceScope:
    """创建 worker 或服务进程级资源作用域。"""

    return ResourceScope(kind="process")


def get_or_create_workflow_resource_scope(
    execution_metadata: dict[str, object],
) -> ResourceScope:
    """从执行元数据读取或创建当前 Workflow 资源作用域。"""

    existing = execution_metadata.get(WORKFLOW_RESOURCE_SCOPE_METADATA_KEY)
    if isinstance(existing, ResourceScope):
        return existing
    scope = ResourceScope(kind="workflow")
    execution_metadata[WORKFLOW_RESOURCE_SCOPE_METADATA_KEY] = scope
    return scope


__all__ = [
    "ResourceCloseError",
    "ResourceScope",
    "WORKFLOW_RESOURCE_SCOPE_METADATA_KEY",
    "create_process_resource_scope",
    "get_or_create_workflow_resource_scope",
]
