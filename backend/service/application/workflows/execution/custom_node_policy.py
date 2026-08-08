"""custom node 执行权限、超时和隔离策略。"""

from __future__ import annotations

from dataclasses import dataclass
import os
import sys
from threading import Event, Timer
from time import monotonic
from typing import TYPE_CHECKING, TypeVar

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.contracts.workflows.workflow_graph import NODE_IMPLEMENTATION_CUSTOM
from backend.service.application.errors import (
    PermissionDeniedError,
    ServiceConfigurationError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from backend.service.application.workflows.execution.contracts import (
        WorkflowNodeExecutionRequest,
    )


CUSTOM_NODE_PROCESS_ISOLATED_METADATA_KEY = "_amvision_custom_node_process_isolated"
CUSTOM_NODE_TIMEOUT_EXIT_CODE = 124
_CustomNodeResult = TypeVar("_CustomNodeResult")


@dataclass(frozen=True)
class WorkflowCustomNodeRuntimePolicy:
    """描述单个 node pack 在 workflow worker 中的强制执行策略。

    字段：
    - node_pack_id：节点包稳定 id。
    - node_pack_version：当前加载版本。
    - permission_scopes：节点包被授予的最小权限集合。
    - default_timeout_seconds：默认执行超时秒数。
    - max_timeout_seconds：允许的硬超时上限。
    - kill_grace_seconds：强制终止前的回收宽限秒数。
    - isolation：执行隔离边界。
    - timeout_action：超时后的强制处置。
    """

    node_pack_id: str
    node_pack_version: str
    permission_scopes: frozenset[str]
    default_timeout_seconds: int
    max_timeout_seconds: int
    kill_grace_seconds: int
    isolation: str
    timeout_action: str

    @classmethod
    def from_manifest(cls, manifest: NodePackManifest) -> WorkflowCustomNodeRuntimePolicy:
        """从已经校验的 manifest 构造运行时策略。"""

        return cls(
            node_pack_id=manifest.node_pack_id,
            node_pack_version=manifest.version,
            permission_scopes=frozenset(manifest.permission_scopes),
            default_timeout_seconds=manifest.timeout.default_seconds,
            max_timeout_seconds=manifest.timeout.max_seconds,
            kill_grace_seconds=manifest.timeout.kill_grace_seconds,
            isolation=manifest.execution.isolation,
            timeout_action=manifest.execution.timeout_action,
        )


def require_custom_node_permission(
    request: WorkflowNodeExecutionRequest,
    permission_scope: str,
) -> None:
    """校验 custom node 是否获得指定平台资源权限。

    core node 不受 node pack 权限模型约束。custom node 的身份和 scope 必须由
    ``WorkflowNodeRuntimeRegistry`` 从已经校验的 manifest 注入，节点传入的参数
    或 execution metadata 不能自行扩大权限。
    """

    if request.node_definition.implementation_kind != NODE_IMPLEMENTATION_CUSTOM:
        return
    normalized_scope = permission_scope.strip()
    if not normalized_scope:
        raise ServiceConfigurationError(
            "custom node 权限校验缺少 permission scope",
            details={"node_id": request.node_id},
        )
    if request.node_pack_id is None or request.node_pack_version is None:
        raise ServiceConfigurationError(
            "custom node 未经过 node pack 运行时策略装配",
            details={
                "node_id": request.node_id,
                "node_type_id": request.node_definition.node_type_id,
            },
        )
    if normalized_scope not in request.granted_permission_scopes:
        raise PermissionDeniedError(
            "custom node 未获得所需平台资源权限",
            details={
                "node_id": request.node_id,
                "node_type_id": request.node_definition.node_type_id,
                "node_pack_id": request.node_pack_id,
                "node_pack_version": request.node_pack_version,
                "required_permission_scope": normalized_scope,
                "granted_permission_scopes": sorted(
                    request.granted_permission_scopes
                ),
            },
        )


def validate_custom_node_required_permissions(
    *,
    node_type_id: str,
    policy: WorkflowCustomNodeRuntimePolicy,
    required_permission_scopes: tuple[str, ...],
) -> tuple[str, ...]:
    """校验 entrypoint 声明的资源入口权限并返回规范化结果。"""

    normalized_scopes = tuple(
        str(permission_scope).strip()
        for permission_scope in required_permission_scopes
    )
    if any(not permission_scope for permission_scope in normalized_scopes):
        raise ServiceConfigurationError(
            "custom node 资源入口声明包含空 permission scope",
            details={"node_type_id": node_type_id},
        )
    if len(set(normalized_scopes)) != len(normalized_scopes):
        raise ServiceConfigurationError(
            "custom node 资源入口声明包含重复 permission scope",
            details={"node_type_id": node_type_id},
        )
    missing_scopes = sorted(
        set(normalized_scopes) - policy.permission_scopes
    )
    if missing_scopes:
        raise ServiceConfigurationError(
            "custom node 资源入口所需权限未在 manifest 中声明",
            details={
                "node_type_id": node_type_id,
                "node_pack_id": policy.node_pack_id,
                "node_pack_version": policy.node_pack_version,
                "missing_permission_scopes": missing_scopes,
                "granted_permission_scopes": sorted(policy.permission_scopes),
            },
        )
    return normalized_scopes


class CustomNodeHardTimeoutGuard:
    """在 workflow 隔离进程中对单个 custom node 执行硬 timeout。"""

    def __init__(
        self,
        *,
        node_id: str,
        node_type_id: str,
        timeout_seconds: int,
        kill_grace_seconds: int,
    ) -> None:
        """初始化软取消事件和最终强制退出计时器。"""

        self.node_id = node_id
        self.node_type_id = node_type_id
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.kill_grace_seconds = max(0, int(kill_grace_seconds))
        self.cancellation_event = Event()
        self._cancel_timer: Timer | None = None
        self._kill_timer: Timer | None = None

    def run(self, handler: Callable[[], _CustomNodeResult]) -> _CustomNodeResult:
        """执行 handler；超时后先发取消事件，再硬退出整个 workflow 进程。"""

        self._cancel_timer = Timer(self.timeout_seconds, self.cancellation_event.set)
        self._cancel_timer.daemon = True
        self._kill_timer = Timer(
            self.timeout_seconds + self.kill_grace_seconds,
            self._terminate_process,
        )
        self._kill_timer.daemon = True
        self._cancel_timer.start()
        self._kill_timer.start()
        started_at = monotonic()
        try:
            result = handler()
            if (
                self.cancellation_event.is_set()
                or monotonic() - started_at >= self.timeout_seconds
            ):
                self._terminate_process()
            return result
        finally:
            self._cancel_timer.cancel()
            self._kill_timer.cancel()

    def _terminate_process(self) -> None:
        """记录最小诊断后使用 os._exit 终止隔离进程。"""

        try:
            sys.stderr.write(
                "custom node hard timeout: "
                f"node_id={self.node_id} node_type_id={self.node_type_id} "
                f"timeout_seconds={self.timeout_seconds} "
                f"kill_grace_seconds={self.kill_grace_seconds}\n"
            )
            sys.stderr.flush()
        finally:
            os._exit(CUSTOM_NODE_TIMEOUT_EXIT_CODE)
