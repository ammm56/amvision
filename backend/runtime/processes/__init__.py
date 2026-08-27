"""进程生命周期、deadline 与有界日志基础设施。"""

from backend.runtime.processes.attempt_deadline import AttemptDeadline
from backend.runtime.processes.managed_child_signals import (
    configure_managed_child_signals,
)
from backend.runtime.processes.process_tree_supervisor import (
    ProcessTreeResult,
    ProcessTreeSupervisor,
)

__all__ = [
    "AttemptDeadline",
    "ProcessTreeResult",
    "ProcessTreeSupervisor",
    "configure_managed_child_signals",
]
