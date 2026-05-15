"""workflow 资源共享语义定义。"""

from __future__ import annotations

from typing import Literal


WorkflowPreviewRunState = Literal["created", "running", "succeeded", "failed", "cancelled", "timed_out"]
WorkflowManagedRuntimeState = Literal["stopped", "starting", "running", "stopping", "failed"]
WorkflowAppRuntimeState = WorkflowManagedRuntimeState
WorkflowTriggerRuntimeState = WorkflowManagedRuntimeState
WorkflowRunState = Literal[
    "created",
    "queued",
    "dispatching",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
]
WorkflowExecutionPolicyKind = Literal["preview-default", "runtime-default"]
WorkflowTriggerKind = Literal[
    "plc-register",
    "mqtt-topic",
    "zeromq-topic",
    "grpc-method",
    "io-change",
    "sensor-read",
    "schedule",
    "webhook",
    "http-api",
]
WorkflowTriggerSubmitMode = Literal["sync", "async"]
WorkflowTriggerResultMode = Literal["sync-reply", "accepted-then-query", "async-report", "event-only"]
WorkflowTriggerAckPolicy = Literal[
    "ack-after-received",
    "ack-after-run-created",
    "ack-after-run-finished",
]
WorkflowTriggerResultState = Literal["accepted", "succeeded", "failed", "timed_out"]

WORKFLOW_PREVIEW_RUN_STATES: tuple[WorkflowPreviewRunState, ...] = (
    "created",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
)
WORKFLOW_PREVIEW_RUN_TERMINAL_STATES = frozenset(("succeeded", "failed", "cancelled", "timed_out"))
WORKFLOW_PREVIEW_RUN_DEFAULT_RETENTION_HOURS = 24
WORKFLOW_PREVIEW_RUN_STORAGE_ROOT = "workflows/runtime/preview-runs"
WORKFLOW_PREVIEW_RUN_CLEANUP_COMMAND = "cleanup-preview-runs"
WORKFLOW_RUNTIME_STORAGE_DEFAULT_RETENTION_HOURS = 24
WORKFLOW_RUNTIME_STORAGE_CLEANUP_COMMAND = "cleanup-runtime-storage"

WORKFLOW_MANAGED_RUNTIME_STATES: tuple[WorkflowManagedRuntimeState, ...] = (
    "stopped",
    "starting",
    "running",
    "stopping",
    "failed",
)
WORKFLOW_APP_RUNTIME_STATES = WORKFLOW_MANAGED_RUNTIME_STATES
WORKFLOW_TRIGGER_RUNTIME_STATES = WORKFLOW_MANAGED_RUNTIME_STATES

WORKFLOW_RUN_STATES: tuple[WorkflowRunState, ...] = (
    "created",
    "queued",
    "dispatching",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
)
WORKFLOW_RUN_TERMINAL_STATES = frozenset(("succeeded", "failed", "cancelled", "timed_out"))

WORKFLOW_EXECUTION_POLICY_KINDS: tuple[WorkflowExecutionPolicyKind, ...] = (
    "preview-default",
    "runtime-default",
)

WORKFLOW_TRIGGER_KINDS: tuple[WorkflowTriggerKind, ...] = (
    "plc-register",
    "mqtt-topic",
    "zeromq-topic",
    "grpc-method",
    "io-change",
    "sensor-read",
    "schedule",
    "webhook",
    "http-api",
)
WORKFLOW_TRIGGER_SUBMIT_MODES: tuple[WorkflowTriggerSubmitMode, ...] = ("sync", "async")
WORKFLOW_TRIGGER_RESULT_MODES: tuple[WorkflowTriggerResultMode, ...] = (
    "sync-reply",
    "accepted-then-query",
    "async-report",
    "event-only",
)
WORKFLOW_TRIGGER_ACK_POLICIES: tuple[WorkflowTriggerAckPolicy, ...] = (
    "ack-after-received",
    "ack-after-run-created",
    "ack-after-run-finished",
)
WORKFLOW_TRIGGER_RESULT_STATES: tuple[WorkflowTriggerResultState, ...] = (
    "accepted",
    "succeeded",
    "failed",
    "timed_out",
)

WORKFLOW_RUN_STORAGE_ROOT = "workflows/runtime"
WORKFLOW_RUNTIME_STORAGE_ROOT = "workflows/runtime/app-runtimes"


def build_workflow_preview_run_storage_dir(preview_run_id: str) -> str:
    """返回单个 preview run 的 snapshot 根目录。

    参数：
    - preview_run_id：preview run id。

    返回：
    - str：preview run 在对象存储中的根目录。
    """

    return f"{WORKFLOW_PREVIEW_RUN_STORAGE_ROOT}/{preview_run_id}"


def build_workflow_preview_run_snapshot_object_key(preview_run_id: str, snapshot_name: str) -> str:
    """返回单个 preview run snapshot 文件的 object key。

    参数：
    - preview_run_id：preview run id。
    - snapshot_name：snapshot 文件名，不含目录前缀。

    返回：
    - str：preview run snapshot 的 object key。
    """

    return f"{build_workflow_preview_run_storage_dir(preview_run_id)}/{snapshot_name}"


def build_workflow_preview_run_events_object_key(preview_run_id: str) -> str:
    """返回单个 preview run 事件文件的 object key。"""

    return build_workflow_preview_run_snapshot_object_key(preview_run_id, "events.json")


def build_workflow_app_runtime_storage_dir(workflow_runtime_id: str) -> str:
    """返回单个 app runtime 的 snapshot 根目录。

    参数：
    - workflow_runtime_id：WorkflowAppRuntime id。

    返回：
    - str：app runtime 在对象存储中的根目录。
    """

    return f"{WORKFLOW_RUNTIME_STORAGE_ROOT}/{workflow_runtime_id}"


def build_workflow_app_runtime_snapshot_object_key(workflow_runtime_id: str, snapshot_name: str) -> str:
    """返回单个 app runtime snapshot 文件的 object key。

    参数：
    - workflow_runtime_id：WorkflowAppRuntime id。
    - snapshot_name：snapshot 文件名，不含目录前缀。

    返回：
    - str：app runtime snapshot 的 object key。
    """

    return f"{build_workflow_app_runtime_storage_dir(workflow_runtime_id)}/{snapshot_name}"


def build_workflow_app_runtime_events_object_key(workflow_runtime_id: str) -> str:
    """返回单个 app runtime 事件文件的 object key。"""

    return build_workflow_app_runtime_snapshot_object_key(workflow_runtime_id, "events.json")


def build_workflow_run_storage_dir(workflow_run_id: str) -> str:
    """返回单个 WorkflowRun 的运行目录。

    参数：
    - workflow_run_id：WorkflowRun id。

    返回：
    - str：WorkflowRun 在对象存储中的根目录。
    """

    return f"{WORKFLOW_RUN_STORAGE_ROOT}/{workflow_run_id}"


def build_workflow_run_events_object_key(workflow_run_id: str) -> str:
    """返回单个 WorkflowRun 事件文件的 object key。"""

    return f"{build_workflow_run_storage_dir(workflow_run_id)}/events.json"