"""Workflow Node Pack 执行 timeout 协议。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from backend.contracts.nodes.node_pack_manifest import NodePackManifest


NodePackIdentity: TypeAlias = tuple[str, str]
"""Node Pack id 与版本组成的不可变运行时身份。"""


@dataclass(frozen=True)
class NodePackExecutionTimeoutPolicy:
    """描述一次 worker generation 固化的 Node Pack timeout 策略。"""

    default_seconds: float
    kill_grace_seconds: float


def build_node_pack_timeout_policy_index(
    manifests: tuple[NodePackManifest, ...],
) -> dict[NodePackIdentity, NodePackExecutionTimeoutPolicy]:
    """把当前 Registry 的 manifest 转换为精确版本索引。"""

    return {
        (manifest.node_pack_id, manifest.version): NodePackExecutionTimeoutPolicy(
            default_seconds=float(manifest.timeout.default_seconds),
            kill_grace_seconds=float(manifest.timeout.kill_grace_seconds),
        )
        for manifest in manifests
    }


__all__ = [
    "NodePackExecutionTimeoutPolicy",
    "NodePackIdentity",
    "build_node_pack_timeout_policy_index",
]
