"""workflow service runtime 输出负载。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowEvaluationTaskPackage:
    """描述 workflow service node 侧的评估结果包输出。"""

    task_id: str
    package_object_key: str
    package_file_name: str
    package_size: int
    packaged_at: str
