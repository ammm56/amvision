"""WebSocket v1 路由定义。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.settings import BackendServiceSettings
from backend.service.api.deps.auth import AuthenticatedPrincipal, resolve_socket_principal
from backend.service.application.deployments.yolox_deployment_service import SqlAlchemyYoloXDeploymentService
from backend.service.application.events import InMemoryServiceEventBus, ServiceEvent
from backend.service.application.project_summary import (
    PROJECT_SUMMARY_SNAPSHOT_EVENT_TYPE,
    ProjectSummaryService,
    ProjectSummarySnapshot,
    build_project_summary_payload,
    get_supported_project_summary_topics,
    normalize_project_summary_topic,
)
from backend.service.application.runtime.deployment_event_source import YoloXDeploymentEventSource
from backend.service.application.runtime.deployment_events import (
    YoloXDeploymentProcessEvent,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskEventQueryFilters
from backend.service.application.workflows.preview_run_manager import WorkflowPreviewRunManager
from backend.service.application.workflows.runtime_service import WorkflowRuntimeService
from backend.service.application.workflows.runtime_worker import WorkflowRuntimeWorkerManager
from backend.service.domain.tasks.task_records import TaskEvent
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntimeEvent,
    WorkflowPreviewRunEvent,
    WorkflowRunEvent,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


ws_v1_router = APIRouter(prefix="/ws/v1")


@ws_v1_router.websocket("/system/events")
async def subscribe_system_events(socket: WebSocket) -> None:
    """建立 system 事件订阅会话。

    参数：
    - socket：当前 WebSocket 连接。
    """

    occurred_at = _now_iso()
    await socket.accept()
    await socket.send_json(
        {
            "stream": "system.events",
            "event_type": "system.connected",
            "event_version": "v1",
            "occurred_at": occurred_at,
            "resource_kind": "system",
            "resource_id": "system",
            "cursor": f"{occurred_at}|system.connected",
            "payload": {},
        }
    )
    await socket.close(code=1000)


@ws_v1_router.websocket("/tasks/events")
async def subscribe_task_events(socket: WebSocket) -> None:
    """按任务维度建立 v1 任务事件订阅会话。

    参数：
    - socket：当前 WebSocket 连接。
    """

    principal = _get_socket_principal(socket)
    if principal is None:
        await socket.close(code=4401, reason="authentication_required")
        return
    if not _scope_granted(principal.scopes, "tasks:read"):
        await socket.close(code=4403, reason="permission_denied")
        return

    task_id = socket.query_params.get("task_id")
    if task_id is None or not task_id.strip():
        await socket.close(code=4400, reason="task_id_required")
        return

    session_factory = _get_socket_session_factory(socket)
    if session_factory is None:
        await socket.close(code=1011, reason="session_factory_not_ready")
        return

    service = SqlAlchemyTaskService(session_factory)
    event_bus = _get_socket_event_bus(socket)
    if event_bus is None:
        await socket.close(code=1011, reason="service_event_bus_not_ready")
        return
    try:
        task_detail = service.get_task(task_id)
    except Exception:
        await socket.close(code=4404, reason="task_not_found")
        return
    if principal.project_ids and task_detail.task.project_id not in principal.project_ids:
        await socket.close(code=4404, reason="task_not_found")
        return

    event_type = socket.query_params.get("event_type")
    after_cursor = socket.query_params.get("after_cursor")
    limit = _parse_limit(socket.query_params.get("limit"))
    sent_event_ids: set[str] = set()
    subscription = event_bus.subscribe(stream="tasks.events", resource_id=task_id)

    await socket.accept()
    await socket.send_json(
        {
            "stream": "tasks.events",
            "event_type": "tasks.connected",
            "event_version": "v1",
            "occurred_at": _now_iso(),
            "resource_kind": "task",
            "resource_id": task_id,
            "cursor": after_cursor,
            "payload": {
                "filters": {
                    "event_type": event_type,
                    "after_cursor": after_cursor,
                    "limit": limit,
                }
            },
        }
    )

    try:
        events = service.list_task_events(
            TaskEventQueryFilters(
                task_id=task_id,
                event_type=event_type,
                limit=limit,
            )
        )
        for event in events:
            if event.event_id in sent_event_ids:
                continue
            if not _event_after_cursor(event, after_cursor):
                continue
            sent_event_ids.add(event.event_id)
            await socket.send_json(_build_task_event_message(event))

        while True:
            if subscription.consume_overflowed():
                await socket.send_json(_build_lagging_message(task_id))
                await socket.close(code=1013, reason="subscriber_queue_overflowed")
                return

            service_event = await subscription.receive(timeout_seconds=15.0)
            if service_event is None:
                await socket.send_json(_build_heartbeat_message(task_id))
                continue

            event_id = str(service_event.payload.get("event_id", "")).strip()
            if event_id and event_id in sent_event_ids:
                continue
            if not _service_event_after_cursor(service_event, after_cursor):
                continue
            if event_id:
                sent_event_ids.add(event_id)
            await socket.send_json(_build_service_event_message(service_event))
    except WebSocketDisconnect:
        return
    finally:
        subscription.close()


@ws_v1_router.websocket("/workflows/preview-runs/events")
async def subscribe_preview_run_events(socket: WebSocket) -> None:
    """按 preview run 维度建立 v1 事件订阅会话。

    参数：
    - socket：当前 WebSocket 连接。
    """

    principal = _get_socket_principal(socket)
    if principal is None:
        await socket.close(code=4401, reason="authentication_required")
        return
    if not _scope_granted(principal.scopes, "workflows:read"):
        await socket.close(code=4403, reason="permission_denied")
        return

    preview_run_id = socket.query_params.get("preview_run_id")
    if preview_run_id is None or not preview_run_id.strip():
        await socket.close(code=4400, reason="preview_run_id_required")
        return

    preview_run_manager = _get_socket_preview_run_manager(socket)
    if preview_run_manager is None:
        await socket.close(code=1011, reason="workflow_preview_run_manager_not_ready")
        return

    event_bus = _get_socket_event_bus(socket)
    if event_bus is None:
        await socket.close(code=1011, reason="service_event_bus_not_ready")
        return

    try:
        preview_run = preview_run_manager.get_preview_run(preview_run_id)
    except Exception:
        await socket.close(code=4404, reason="preview_run_not_found")
        return
    if principal.project_ids and preview_run.project_id not in principal.project_ids:
        await socket.close(code=4404, reason="preview_run_not_found")
        return

    after_cursor = socket.query_params.get("after_cursor")
    try:
        after_sequence = _parse_preview_run_after_cursor(after_cursor)
    except ValueError:
        await socket.close(code=4400, reason="after_cursor_invalid")
        return

    limit = _parse_limit(socket.query_params.get("limit"))
    sent_sequences: set[int] = set()
    subscription = event_bus.subscribe(
        stream="workflows.preview-runs.events",
        resource_id=preview_run_id,
    )

    await socket.accept()
    await socket.send_json(
        {
            "stream": "workflows.preview-runs.events",
            "event_type": "workflows.preview-runs.connected",
            "event_version": "v1",
            "occurred_at": _now_iso(),
            "resource_kind": "workflow_preview_run",
            "resource_id": preview_run_id,
            "cursor": after_cursor,
            "payload": {
                "filters": {
                    "after_cursor": after_cursor,
                    "limit": limit,
                }
            },
        }
    )

    try:
        replay_events = preview_run_manager.list_events(
            preview_run_id,
            after_sequence=after_sequence,
            limit=limit,
        )
        for event in replay_events:
            if event.sequence in sent_sequences:
                continue
            sent_sequences.add(event.sequence)
            await socket.send_json(_build_preview_run_event_message(event))

        while True:
            if subscription.consume_overflowed():
                await socket.send_json(_build_preview_run_lagging_message(preview_run_id))
                await socket.close(code=1013, reason="subscriber_queue_overflowed")
                return

            service_event = await subscription.receive(timeout_seconds=15.0)
            if service_event is None:
                await socket.send_json(_build_preview_run_heartbeat_message(preview_run_id))
                continue

            sequence = _parse_service_event_sequence(service_event)
            if sequence is not None and sequence in sent_sequences:
                continue
            if not _preview_service_event_after_cursor(service_event, after_sequence):
                continue
            if sequence is not None:
                sent_sequences.add(sequence)
            await socket.send_json(_build_service_event_message(service_event))
    except WebSocketDisconnect:
        return
    finally:
        subscription.close()


@ws_v1_router.websocket("/workflows/runs/events")
async def subscribe_workflow_run_events(socket: WebSocket) -> None:
    """按 WorkflowRun 维度建立 v1 事件订阅会话。"""

    principal = _get_socket_principal(socket)
    if principal is None:
        await socket.close(code=4401, reason="authentication_required")
        return
    if not _scope_granted(principal.scopes, "workflows:read"):
        await socket.close(code=4403, reason="permission_denied")
        return

    workflow_run_id = socket.query_params.get("workflow_run_id")
    if workflow_run_id is None or not workflow_run_id.strip():
        await socket.close(code=4400, reason="workflow_run_id_required")
        return

    runtime_service = _build_socket_workflow_runtime_service(socket)
    if runtime_service is None:
        await socket.close(code=1011, reason="workflow_runtime_service_not_ready")
        return

    event_bus = _get_socket_event_bus(socket)
    if event_bus is None:
        await socket.close(code=1011, reason="service_event_bus_not_ready")
        return

    try:
        workflow_run = runtime_service.get_workflow_run(workflow_run_id)
    except Exception:
        await socket.close(code=4404, reason="workflow_run_not_found")
        return
    if principal.project_ids and workflow_run.project_id not in principal.project_ids:
        await socket.close(code=4404, reason="workflow_run_not_found")
        return

    after_cursor = socket.query_params.get("after_cursor")
    try:
        after_sequence = _parse_sequence_after_cursor(after_cursor)
    except ValueError:
        await socket.close(code=4400, reason="after_cursor_invalid")
        return

    limit = _parse_limit(socket.query_params.get("limit"))
    sent_sequences: set[int] = set()
    subscription = event_bus.subscribe(
        stream="workflows.runs.events",
        resource_id=workflow_run_id,
    )

    await socket.accept()
    await socket.send_json(
        {
            "stream": "workflows.runs.events",
            "event_type": "workflows.runs.connected",
            "event_version": "v1",
            "occurred_at": _now_iso(),
            "resource_kind": "workflow_run",
            "resource_id": workflow_run_id,
            "cursor": after_cursor,
            "payload": {
                "filters": {
                    "after_cursor": after_cursor,
                    "limit": limit,
                }
            },
        }
    )

    try:
        replay_events = runtime_service.get_workflow_run_events(
            workflow_run_id,
            after_sequence=after_sequence,
            limit=limit,
        )
        for event in replay_events:
            if event.sequence in sent_sequences:
                continue
            sent_sequences.add(event.sequence)
            await socket.send_json(_build_workflow_run_event_message(event))

        while True:
            if subscription.consume_overflowed():
                await socket.send_json(_build_workflow_run_lagging_message(workflow_run_id))
                await socket.close(code=1013, reason="subscriber_queue_overflowed")
                return

            service_event = await subscription.receive(timeout_seconds=15.0)
            if service_event is None:
                await socket.send_json(_build_workflow_run_heartbeat_message(workflow_run_id))
                continue

            sequence = _parse_service_event_sequence(service_event)
            if sequence is not None and sequence in sent_sequences:
                continue
            if not _preview_service_event_after_cursor(service_event, after_sequence):
                continue
            if sequence is not None:
                sent_sequences.add(sequence)
            await socket.send_json(_build_service_event_message(service_event))
    except WebSocketDisconnect:
        return
    finally:
        subscription.close()


@ws_v1_router.websocket("/workflows/app-runtimes/events")
async def subscribe_workflow_app_runtime_events(socket: WebSocket) -> None:
    """按 WorkflowAppRuntime 维度建立 v1 事件订阅会话。"""

    principal = _get_socket_principal(socket)
    if principal is None:
        await socket.close(code=4401, reason="authentication_required")
        return
    if not _scope_granted(principal.scopes, "workflows:read"):
        await socket.close(code=4403, reason="permission_denied")
        return

    workflow_runtime_id = socket.query_params.get("workflow_runtime_id")
    if workflow_runtime_id is None or not workflow_runtime_id.strip():
        await socket.close(code=4400, reason="workflow_runtime_id_required")
        return

    runtime_service = _build_socket_workflow_runtime_service(socket)
    if runtime_service is None:
        await socket.close(code=1011, reason="workflow_runtime_service_not_ready")
        return

    event_bus = _get_socket_event_bus(socket)
    if event_bus is None:
        await socket.close(code=1011, reason="service_event_bus_not_ready")
        return

    try:
        workflow_app_runtime = runtime_service.get_workflow_app_runtime(workflow_runtime_id)
    except Exception:
        await socket.close(code=4404, reason="workflow_app_runtime_not_found")
        return
    if principal.project_ids and workflow_app_runtime.project_id not in principal.project_ids:
        await socket.close(code=4404, reason="workflow_app_runtime_not_found")
        return

    after_cursor = socket.query_params.get("after_cursor")
    try:
        after_sequence = _parse_sequence_after_cursor(after_cursor)
    except ValueError:
        await socket.close(code=4400, reason="after_cursor_invalid")
        return

    limit = _parse_limit(socket.query_params.get("limit"))
    sent_sequences: set[int] = set()
    subscription = event_bus.subscribe(
        stream="workflows.app-runtimes.events",
        resource_id=workflow_runtime_id,
    )

    await socket.accept()
    await socket.send_json(
        {
            "stream": "workflows.app-runtimes.events",
            "event_type": "workflows.app-runtimes.connected",
            "event_version": "v1",
            "occurred_at": _now_iso(),
            "resource_kind": "workflow_app_runtime",
            "resource_id": workflow_runtime_id,
            "cursor": after_cursor,
            "payload": {
                "filters": {
                    "after_cursor": after_cursor,
                    "limit": limit,
                }
            },
        }
    )

    try:
        replay_events = runtime_service.get_workflow_app_runtime_events(
            workflow_runtime_id,
            after_sequence=after_sequence,
            limit=limit,
        )
        for event in replay_events:
            if event.sequence in sent_sequences:
                continue
            sent_sequences.add(event.sequence)
            await socket.send_json(_build_workflow_app_runtime_event_message(event))

        while True:
            if subscription.consume_overflowed():
                await socket.send_json(_build_workflow_app_runtime_lagging_message(workflow_runtime_id))
                await socket.close(code=1013, reason="subscriber_queue_overflowed")
                return

            service_event = await subscription.receive(timeout_seconds=15.0)
            if service_event is None:
                await socket.send_json(_build_workflow_app_runtime_heartbeat_message(workflow_runtime_id))
                continue

            sequence = _parse_service_event_sequence(service_event)
            if sequence is not None and sequence in sent_sequences:
                continue
            if not _preview_service_event_after_cursor(service_event, after_sequence):
                continue
            if sequence is not None:
                sent_sequences.add(sequence)
            await socket.send_json(_build_service_event_message(service_event))
    except WebSocketDisconnect:
        return
    finally:
        subscription.close()


@ws_v1_router.websocket("/deployments/events")
async def subscribe_deployment_events(socket: WebSocket) -> None:
    """按 DeploymentInstance 维度建立 v1 事件订阅会话。"""

    principal = _get_socket_principal(socket)
    if principal is None:
        await socket.close(code=4401, reason="authentication_required")
        return
    if not _scope_granted(principal.scopes, "models:read"):
        await socket.close(code=4403, reason="permission_denied")
        return

    deployment_instance_id = socket.query_params.get("deployment_instance_id")
    if deployment_instance_id is None or not deployment_instance_id.strip():
        await socket.close(code=4400, reason="deployment_instance_id_required")
        return

    runtime_mode = socket.query_params.get("runtime_mode")
    if runtime_mode is not None and runtime_mode not in {"sync", "async"}:
        await socket.close(code=4400, reason="runtime_mode_invalid")
        return

    deployment_service = _build_socket_deployment_service(socket)
    if deployment_service is None:
        await socket.close(code=1011, reason="deployment_service_not_ready")
        return

    deployment_event_source = _build_socket_deployment_event_source(socket)
    if deployment_event_source is None:
        await socket.close(code=1011, reason="deployment_event_source_not_ready")
        return

    event_bus = _get_socket_event_bus(socket)
    if event_bus is None:
        await socket.close(code=1011, reason="service_event_bus_not_ready")
        return

    try:
        deployment_view = deployment_service.get_deployment_instance(deployment_instance_id)
    except Exception:
        await socket.close(code=4404, reason="deployment_instance_not_found")
        return
    if principal.project_ids and deployment_view.project_id not in principal.project_ids:
        await socket.close(code=4404, reason="deployment_instance_not_found")
        return

    after_cursor = socket.query_params.get("after_cursor")
    try:
        after_sequence = _parse_sequence_after_cursor(after_cursor)
    except ValueError:
        await socket.close(code=4400, reason="after_cursor_invalid")
        return

    limit = _parse_limit(socket.query_params.get("limit"))
    sent_sequences: set[int] = set()
    subscription = event_bus.subscribe(
        stream="deployments.events",
        resource_id=deployment_instance_id,
    )

    await socket.accept()
    await socket.send_json(
        {
            "stream": "deployments.events",
            "event_type": "deployments.connected",
            "event_version": "v1",
            "occurred_at": _now_iso(),
            "resource_kind": "deployment_instance",
            "resource_id": deployment_instance_id,
            "cursor": after_cursor,
            "payload": {
                "filters": {
                    "runtime_mode": runtime_mode,
                    "after_cursor": after_cursor,
                    "limit": limit,
                }
            },
        }
    )

    try:
        replay_events = deployment_event_source.list_events(
            deployment_instance_id,
            after_sequence=after_sequence,
            runtime_mode=runtime_mode,
            limit=limit,
        )
        for event in replay_events:
            if event.sequence in sent_sequences:
                continue
            sent_sequences.add(event.sequence)
            await socket.send_json(_build_deployment_process_event_message(event))

        while True:
            if subscription.consume_overflowed():
                await socket.send_json(_build_deployment_lagging_message(deployment_instance_id))
                await socket.close(code=1013, reason="subscriber_queue_overflowed")
                return

            service_event = await subscription.receive(timeout_seconds=15.0)
            if service_event is None:
                await socket.send_json(_build_deployment_heartbeat_message(deployment_instance_id))
                continue
            if runtime_mode is not None and service_event.payload.get("runtime_mode") != runtime_mode:
                continue

            sequence = _parse_service_event_sequence(service_event)
            if sequence is not None and sequence in sent_sequences:
                continue
            if not _preview_service_event_after_cursor(service_event, after_sequence):
                continue
            if sequence is not None:
                sent_sequences.add(sequence)
            await socket.send_json(_build_service_event_message(service_event))
    except WebSocketDisconnect:
        return
    finally:
        subscription.close()


@ws_v1_router.websocket("/projects/events")
async def subscribe_project_events(socket: WebSocket) -> None:
    """按 Project 维度建立聚合 summary 事件订阅会话。"""

    principal = _get_socket_principal(socket)
    if principal is None:
        await socket.close(code=4401, reason="authentication_required")
        return
    if not _scope_granted(principal.scopes, "workflows:read") or not _scope_granted(principal.scopes, "models:read"):
        await socket.close(code=4403, reason="permission_denied")
        return

    project_id = socket.query_params.get("project_id")
    if project_id is None or not project_id.strip():
        await socket.close(code=4400, reason="project_id_required")
        return
    if principal.project_ids and project_id not in principal.project_ids:
        await socket.close(code=4404, reason="project_not_found")
        return

    try:
        topic = normalize_project_summary_topic(socket.query_params.get("topic"))
    except ValueError:
        await socket.close(code=4400, reason="topic_invalid")
        return

    project_summary_service = _build_socket_project_summary_service(socket)
    if project_summary_service is None:
        await socket.close(code=1011, reason="project_summary_service_not_ready")
        return

    event_bus = _get_socket_event_bus(socket)
    if event_bus is None:
        await socket.close(code=1011, reason="service_event_bus_not_ready")
        return

    subscription = event_bus.subscribe(
        stream="projects.events",
        resource_id=project_id,
    )

    await socket.accept()
    await socket.send_json(
        {
            "stream": "projects.events",
            "event_type": "projects.connected",
            "event_version": "v1",
            "occurred_at": _now_iso(),
            "resource_kind": "project",
            "resource_id": project_id,
            "cursor": None,
            "payload": {
                "filters": {
                    "topic": topic,
                },
                "supported_topics": list(get_supported_project_summary_topics()),
            },
        }
    )

    try:
        summary = project_summary_service.get_project_summary(project_id)
        await socket.send_json(
            _build_project_summary_message(
                summary,
                event_type=PROJECT_SUMMARY_SNAPSHOT_EVENT_TYPE,
                topic=topic,
            )
        )

        while True:
            if subscription.consume_overflowed():
                await socket.send_json(_build_project_lagging_message(project_id))
                await socket.close(code=1013, reason="subscriber_queue_overflowed")
                return

            service_event = await subscription.receive(timeout_seconds=15.0)
            if service_event is None:
                await socket.send_json(_build_project_heartbeat_message(project_id))
                continue
            if topic is not None and service_event.payload.get("topic") != topic:
                continue
            await socket.send_json(_build_service_event_message(service_event))
    except WebSocketDisconnect:
        return
    finally:
        subscription.close()


def _build_task_event_message(event: TaskEvent) -> dict[str, object]:
    """把 TaskEvent 构造成 WebSocket v1 消息。

    参数：
    - event：要发送的任务事件。

    返回：
    - 统一结构的 WebSocket v1 消息字典。
    """

    return {
        "stream": "tasks.events",
        "event_type": event.event_type,
        "event_version": "v1",
        "occurred_at": event.created_at,
        "resource_kind": "task",
        "resource_id": event.task_id,
        "cursor": _build_event_cursor(event),
        "payload": {
            "event_id": event.event_id,
            "task_id": event.task_id,
            "attempt_id": event.attempt_id,
            "message": event.message,
            "data": dict(event.payload),
        },
    }


def _build_service_event_message(event: ServiceEvent) -> dict[str, object]:
    """把服务内事件转换成 WebSocket v1 消息。

    参数：
    - event：要发送的服务内事件。

    返回：
    - 统一结构的 WebSocket v1 消息字典。
    """

    return {
        "stream": event.stream,
        "event_type": event.event_type,
        "event_version": event.event_version,
        "occurred_at": event.occurred_at,
        "resource_kind": event.resource_kind,
        "resource_id": event.resource_id,
        "cursor": event.cursor,
        "payload": dict(event.payload),
    }


def _build_preview_run_event_message(event: WorkflowPreviewRunEvent) -> dict[str, object]:
    """把 WorkflowPreviewRunEvent 构造成 WebSocket v1 消息。

    参数：
    - event：要发送的 preview run 事件。

    返回：
    - 统一结构的 WebSocket v1 消息字典。
    """

    return {
        "stream": "workflows.preview-runs.events",
        "event_type": event.event_type,
        "event_version": "v1",
        "occurred_at": event.created_at,
        "resource_kind": "workflow_preview_run",
        "resource_id": event.preview_run_id,
        "cursor": str(event.sequence),
        "payload": {
            "preview_run_id": event.preview_run_id,
            "sequence": event.sequence,
            "message": event.message,
            **dict(event.payload),
        },
    }


def _build_workflow_run_event_message(event: WorkflowRunEvent) -> dict[str, object]:
    """把 WorkflowRunEvent 构造成 WebSocket v1 消息。"""

    return {
        "stream": "workflows.runs.events",
        "event_type": event.event_type,
        "event_version": "v1",
        "occurred_at": event.created_at,
        "resource_kind": "workflow_run",
        "resource_id": event.workflow_run_id,
        "cursor": str(event.sequence),
        "payload": {
            "workflow_run_id": event.workflow_run_id,
            "workflow_runtime_id": event.workflow_runtime_id,
            "sequence": event.sequence,
            "message": event.message,
            **dict(event.payload),
        },
    }


def _build_workflow_app_runtime_event_message(event: WorkflowAppRuntimeEvent) -> dict[str, object]:
    """把 WorkflowAppRuntimeEvent 构造成 WebSocket v1 消息。"""

    return {
        "stream": "workflows.app-runtimes.events",
        "event_type": event.event_type,
        "event_version": "v1",
        "occurred_at": event.created_at,
        "resource_kind": "workflow_app_runtime",
        "resource_id": event.workflow_runtime_id,
        "cursor": str(event.sequence),
        "payload": {
            "workflow_runtime_id": event.workflow_runtime_id,
            "sequence": event.sequence,
            "message": event.message,
            **dict(event.payload),
        },
    }


def _build_deployment_process_event_message(event: YoloXDeploymentProcessEvent) -> dict[str, object]:
    """把 deployment 事件构造成 WebSocket v1 消息。"""

    return {
        "stream": "deployments.events",
        "event_type": event.event_type,
        "event_version": "v1",
        "occurred_at": event.created_at,
        "resource_kind": "deployment_instance",
        "resource_id": event.deployment_instance_id,
        "cursor": str(event.sequence),
        "payload": {
            "deployment_instance_id": event.deployment_instance_id,
            "runtime_mode": event.runtime_mode,
            "sequence": event.sequence,
            "message": event.message,
            **dict(event.payload),
        },
    }


def _build_project_summary_message(
    summary: ProjectSummarySnapshot,
    *,
    event_type: str,
    topic: str | None,
) -> dict[str, object]:
    """把项目级聚合快照构造成 WebSocket v1 消息。"""

    return {
        "stream": "projects.events",
        "event_type": event_type,
        "event_version": "v1",
        "occurred_at": summary.generated_at,
        "resource_kind": "project",
        "resource_id": summary.project_id,
        "cursor": summary.generated_at,
        "payload": build_project_summary_payload(summary, topic=topic),
    }


def _build_project_heartbeat_message(project_id: str) -> dict[str, object]:
    """构造项目级聚合流心跳消息。"""

    occurred_at = _now_iso()
    return {
        "stream": "projects.events",
        "event_type": "projects.heartbeat",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "project",
        "resource_id": project_id,
        "cursor": f"heartbeat|{occurred_at}",
        "payload": {},
    }


def _build_project_lagging_message(project_id: str) -> dict[str, object]:
    """构造项目级聚合流订阅端跟不上时的提示消息。"""

    occurred_at = _now_iso()
    return {
        "stream": "projects.events",
        "event_type": "projects.lagging",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "project",
        "resource_id": project_id,
        "cursor": f"lagging|{occurred_at}",
        "payload": {"message": "subscriber queue overflowed"},
    }


def _build_heartbeat_message(task_id: str) -> dict[str, object]:
    """构造任务事件流心跳消息。

    参数：
    - task_id：所属任务 id。

    返回：
    - WebSocket v1 心跳消息字典。
    """

    occurred_at = _now_iso()
    return {
        "stream": "tasks.events",
        "event_type": "tasks.heartbeat",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "task",
        "resource_id": task_id,
        "cursor": f"{occurred_at}|heartbeat",
        "payload": {},
    }


def _build_lagging_message(task_id: str) -> dict[str, object]:
    """构造订阅端跟不上时的提示消息。

    参数：
    - task_id：所属任务 id。

    返回：
    - WebSocket v1 跟不上提示消息字典。
    """

    occurred_at = _now_iso()
    return {
        "stream": "tasks.events",
        "event_type": "tasks.lagging",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "task",
        "resource_id": task_id,
        "cursor": f"{occurred_at}|lagging",
        "payload": {"message": "subscriber queue overflowed"},
    }


def _build_preview_run_heartbeat_message(preview_run_id: str) -> dict[str, object]:
    """构造 preview run 事件流心跳消息。

    参数：
    - preview_run_id：所属 preview run id。

    返回：
    - WebSocket v1 心跳消息字典。
    """

    occurred_at = _now_iso()
    return {
        "stream": "workflows.preview-runs.events",
        "event_type": "workflows.preview-runs.heartbeat",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "workflow_preview_run",
        "resource_id": preview_run_id,
        "cursor": f"heartbeat|{occurred_at}",
        "payload": {},
    }


def _build_preview_run_lagging_message(preview_run_id: str) -> dict[str, object]:
    """构造 preview run 订阅端跟不上时的提示消息。

    参数：
    - preview_run_id：所属 preview run id。

    返回：
    - WebSocket v1 跟不上提示消息字典。
    """

    occurred_at = _now_iso()
    return {
        "stream": "workflows.preview-runs.events",
        "event_type": "workflows.preview-runs.lagging",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "workflow_preview_run",
        "resource_id": preview_run_id,
        "cursor": f"lagging|{occurred_at}",
        "payload": {"message": "subscriber queue overflowed"},
    }


def _build_workflow_run_heartbeat_message(workflow_run_id: str) -> dict[str, object]:
    """构造 WorkflowRun 事件流心跳消息。"""

    occurred_at = _now_iso()
    return {
        "stream": "workflows.runs.events",
        "event_type": "workflows.runs.heartbeat",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "workflow_run",
        "resource_id": workflow_run_id,
        "cursor": f"heartbeat|{occurred_at}",
        "payload": {},
    }


def _build_workflow_run_lagging_message(workflow_run_id: str) -> dict[str, object]:
    """构造 WorkflowRun 订阅端跟不上时的提示消息。"""

    occurred_at = _now_iso()
    return {
        "stream": "workflows.runs.events",
        "event_type": "workflows.runs.lagging",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "workflow_run",
        "resource_id": workflow_run_id,
        "cursor": f"lagging|{occurred_at}",
        "payload": {"message": "subscriber queue overflowed"},
    }


def _build_workflow_app_runtime_heartbeat_message(workflow_runtime_id: str) -> dict[str, object]:
    """构造 WorkflowAppRuntime 事件流心跳消息。"""

    occurred_at = _now_iso()
    return {
        "stream": "workflows.app-runtimes.events",
        "event_type": "workflows.app-runtimes.heartbeat",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "workflow_app_runtime",
        "resource_id": workflow_runtime_id,
        "cursor": f"heartbeat|{occurred_at}",
        "payload": {},
    }


def _build_workflow_app_runtime_lagging_message(workflow_runtime_id: str) -> dict[str, object]:
    """构造 WorkflowAppRuntime 订阅端跟不上时的提示消息。"""

    occurred_at = _now_iso()
    return {
        "stream": "workflows.app-runtimes.events",
        "event_type": "workflows.app-runtimes.lagging",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "workflow_app_runtime",
        "resource_id": workflow_runtime_id,
        "cursor": f"lagging|{occurred_at}",
        "payload": {"message": "subscriber queue overflowed"},
    }


def _build_deployment_heartbeat_message(deployment_instance_id: str) -> dict[str, object]:
    """构造 deployment 事件流心跳消息。"""

    occurred_at = _now_iso()
    return {
        "stream": "deployments.events",
        "event_type": "deployments.heartbeat",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "deployment_instance",
        "resource_id": deployment_instance_id,
        "cursor": f"heartbeat|{occurred_at}",
        "payload": {},
    }


def _build_deployment_lagging_message(deployment_instance_id: str) -> dict[str, object]:
    """构造 deployment 订阅端跟不上时的提示消息。"""

    occurred_at = _now_iso()
    return {
        "stream": "deployments.events",
        "event_type": "deployments.lagging",
        "event_version": "v1",
        "occurred_at": occurred_at,
        "resource_kind": "deployment_instance",
        "resource_id": deployment_instance_id,
        "cursor": f"lagging|{occurred_at}",
        "payload": {"message": "subscriber queue overflowed"},
    }


def _build_event_cursor(event: TaskEvent) -> str:
    """为任务事件构造稳定游标。

    参数：
    - event：要生成游标的任务事件。

    返回：
    - 由发生时间和事件 id 组成的游标字符串。
    """

    return f"{event.created_at}|{event.event_id}"


def _event_after_cursor(event: TaskEvent, after_cursor: str | None) -> bool:
    """判断任务事件是否晚于指定游标。

    参数：
    - event：当前任务事件。
    - after_cursor：订阅方传入的最近处理游标。

    返回：
    - 当事件应继续发送时返回 True。
    """

    if after_cursor is None or not after_cursor.strip():
        return True

    after_created_at, _, after_event_id = after_cursor.partition("|")
    event_identity = (event.created_at, event.event_id)
    cursor_identity = (after_created_at, after_event_id)
    return event_identity > cursor_identity


def _service_event_after_cursor(event: ServiceEvent, after_cursor: str | None) -> bool:
    """判断服务内事件是否晚于指定游标。

    参数：
    - event：当前服务内事件。
    - after_cursor：订阅方传入的最近处理游标。

    返回：
    - 当事件应继续发送时返回 True。
    """

    if after_cursor is None or not after_cursor.strip():
        return True
    if event.cursor is None or not event.cursor.strip():
        return True
    return event.cursor > after_cursor


def _preview_service_event_after_cursor(
    event: ServiceEvent,
    after_sequence: int | None,
) -> bool:
    """判断 preview run 服务内事件是否晚于指定序号。

    参数：
    - event：当前服务内事件。
    - after_sequence：订阅方传入的最近处理序号。

    返回：
    - 当事件应继续发送时返回 True。
    """

    if after_sequence is None:
        return True
    event_sequence = _parse_service_event_sequence(event)
    if event_sequence is None:
        return True
    return event_sequence > after_sequence


def _get_socket_principal(socket: WebSocket) -> AuthenticatedPrincipal | None:
    """从 WebSocket 请求头解析当前主体。

    参数：
    - socket：当前 WebSocket 连接。

    返回：
    - 解析得到的主体；未携带主体时返回 None。
    """

    return resolve_socket_principal(socket)


def _get_socket_session_factory(socket: WebSocket) -> SessionFactory | None:
    """从 application.state 读取 SessionFactory。

    参数：
    - socket：当前 WebSocket 连接。

    返回：
    - 当前应用绑定的 SessionFactory；不存在时返回 None。
    """

    session_factory = getattr(socket.app.state, "session_factory", None)
    if isinstance(session_factory, SessionFactory):
        return session_factory

    return None


def _get_socket_event_bus(socket: WebSocket) -> InMemoryServiceEventBus | None:
    """从 application.state 读取服务内事件总线。

    参数：
    - socket：当前 WebSocket 连接。

    返回：
    - 当前应用绑定的事件总线；不存在时返回 None。
    """

    event_bus = getattr(socket.app.state, "service_event_bus", None)
    if isinstance(event_bus, InMemoryServiceEventBus):
        return event_bus

    return None


def _get_socket_preview_run_manager(socket: WebSocket) -> WorkflowPreviewRunManager | None:
    """从 application.state 读取 WorkflowPreviewRunManager。

    参数：
    - socket：当前 WebSocket 连接。

    返回：
    - 当前应用绑定的 preview run 管理器；不存在时返回 None。
    """

    preview_run_manager = getattr(socket.app.state, "workflow_preview_run_manager", None)
    if isinstance(preview_run_manager, WorkflowPreviewRunManager):
        return preview_run_manager

    return None


def _get_socket_backend_service_settings(socket: WebSocket) -> BackendServiceSettings | None:
    """从 application.state 读取 BackendServiceSettings。"""

    settings = getattr(socket.app.state, "backend_service_settings", None)
    if isinstance(settings, BackendServiceSettings):
        return settings
    return None


def _get_socket_dataset_storage(socket: WebSocket) -> LocalDatasetStorage | None:
    """从 application.state 读取 LocalDatasetStorage。"""

    dataset_storage = getattr(socket.app.state, "dataset_storage", None)
    if isinstance(dataset_storage, LocalDatasetStorage):
        return dataset_storage
    return None


def _get_socket_node_catalog_registry(socket: WebSocket) -> NodeCatalogRegistry | None:
    """从 application.state 读取 NodeCatalogRegistry。"""

    node_catalog_registry = getattr(socket.app.state, "node_catalog_registry", None)
    if isinstance(node_catalog_registry, NodeCatalogRegistry):
        return node_catalog_registry
    return None


def _get_socket_workflow_runtime_worker_manager(socket: WebSocket) -> WorkflowRuntimeWorkerManager | None:
    """从 application.state 读取 WorkflowRuntimeWorkerManager。"""

    worker_manager = getattr(socket.app.state, "workflow_runtime_worker_manager", None)
    if isinstance(worker_manager, WorkflowRuntimeWorkerManager):
        return worker_manager
    return None


def _build_socket_workflow_runtime_service(socket: WebSocket) -> WorkflowRuntimeService | None:
    """基于 WebSocket application.state 构建 WorkflowRuntimeService。"""

    settings = _get_socket_backend_service_settings(socket)
    session_factory = _get_socket_session_factory(socket)
    dataset_storage = _get_socket_dataset_storage(socket)
    node_catalog_registry = _get_socket_node_catalog_registry(socket)
    worker_manager = _get_socket_workflow_runtime_worker_manager(socket)
    if (
        settings is None
        or session_factory is None
        or dataset_storage is None
        or node_catalog_registry is None
        or worker_manager is None
    ):
        return None
    return WorkflowRuntimeService(
        settings=settings,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
        worker_manager=worker_manager,
        preview_run_manager=_get_socket_preview_run_manager(socket),
    )


def _build_socket_deployment_service(socket: WebSocket) -> SqlAlchemyYoloXDeploymentService | None:
    """基于 WebSocket application.state 构建 deployment 服务。"""

    session_factory = _get_socket_session_factory(socket)
    dataset_storage = _get_socket_dataset_storage(socket)
    if session_factory is None or dataset_storage is None:
        return None
    return SqlAlchemyYoloXDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


def _build_socket_deployment_event_source(socket: WebSocket) -> YoloXDeploymentEventSource | None:
    """基于 WebSocket application.state 构建 deployment 历史事件读取 helper。"""

    dataset_storage = _get_socket_dataset_storage(socket)
    if dataset_storage is None:
        return None
    return YoloXDeploymentEventSource(
        dataset_storage_root_dir=str(dataset_storage.root_dir),
    )


def _build_socket_project_summary_service(socket: WebSocket) -> ProjectSummaryService | None:
    """基于 WebSocket application.state 构建项目级聚合服务。"""

    session_factory = _get_socket_session_factory(socket)
    dataset_storage = _get_socket_dataset_storage(socket)
    if session_factory is None or dataset_storage is None:
        return None
    return ProjectSummaryService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


def _parse_csv_header(header_value: str | None) -> tuple[str, ...]:
    """把逗号分隔的 header 解析为元组。

    参数：
    - header_value：原始 header 字符串。

    返回：
    - 去空白后的字符串元组。
    """

    if header_value is None or not header_value.strip():
        return ()

    return tuple(item.strip() for item in header_value.split(",") if item.strip())


def _scope_granted(granted_scopes: tuple[str, ...], required_scope: str) -> bool:
    """判断 scope 是否已被授权。

    参数：
    - granted_scopes：当前主体已授权的 scope 集合。
    - required_scope：当前连接要求的 scope。

    返回：
    - 已授权时返回 True。
    """

    for granted_scope in granted_scopes:
        if granted_scope == "*" or granted_scope == required_scope:
            return True
        if granted_scope.endswith(":*") and required_scope.startswith(granted_scope[:-1]):
            return True

    return False


def _parse_limit(raw_limit: str | None) -> int:
    """解析订阅端请求中的 limit 参数。

    参数：
    - raw_limit：原始 limit 字符串。

    返回：
    - 规范化后的 limit 值。
    """

    if raw_limit is None:
        return 100
    try:
        limit = int(raw_limit)
    except ValueError:
        return 100

    if limit <= 0:
        return 100

    return min(limit, 500)


def _parse_preview_run_after_cursor(raw_cursor: str | None) -> int | None:
    """解析 preview run 资源流的 after_cursor 参数。

    参数：
    - raw_cursor：原始 after_cursor 字符串。

    返回：
    - 解析得到的 sequence；未提供时返回 None。

    异常：
    - ValueError：当 cursor 不是非负整数时抛出。
    """

    if raw_cursor is None or not raw_cursor.strip():
        return None
    sequence = int(raw_cursor)
    if sequence < 0:
        raise ValueError("after_cursor 不能小于 0")
    return sequence


def _parse_sequence_after_cursor(raw_cursor: str | None) -> int | None:
    """解析按 sequence 递增资源流的 after_cursor 参数。"""

    if raw_cursor is None or not raw_cursor.strip():
        return None
    sequence = int(raw_cursor)
    if sequence < 0:
        raise ValueError("after_cursor 不能小于 0")
    return sequence


def _parse_service_event_sequence(event: ServiceEvent) -> int | None:
    """从服务内事件里解析 preview run sequence。

    参数：
    - event：当前服务内事件。

    返回：
    - 成功解析时返回 sequence；否则返回 None。
    """

    payload_sequence = event.payload.get("sequence")
    if isinstance(payload_sequence, int) and not isinstance(payload_sequence, bool):
        return payload_sequence
    if event.cursor is None or not event.cursor.strip():
        return None
    try:
        return int(event.cursor)
    except ValueError:
        return None


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 字符串。

    返回：
    - 去微秒的 UTC ISO 时间字符串。
    """

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
