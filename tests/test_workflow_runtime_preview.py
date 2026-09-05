"""Runtime 预览副本、独立数据通道及无积压边界测试。"""

from __future__ import annotations

import asyncio
import json
import socket
import pytest
from threading import Event
from types import SimpleNamespace

from backend.contracts.workflows.workflow_graph import NodeDefinition, NodePortDefinition, WorkflowGraphTemplate, WorkflowGraphNode, WorkflowGraphEdge
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor, WorkflowNodeRuntimeRegistry
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.app_version_service import (
    build_node_definition_sha256,
)
from backend.service.application.workflows.runtime_service import WorkflowRuntimeService

from backend.service.application.workflows.runtime_preview import (
    MAX_PREVIEW_BYTES, RuntimePreviewCapture, RuntimePreviewChannel,
    RuntimePreviewSender, RuntimePreviewSubscription,
    RuntimePreviewCapacityError, RuntimePreviewUnavailableError,
    PREVIEW_CAPTURE_KEY,
)


def _capture(capture: RuntimePreviewCapture, value: object, invocation: str = "preview") -> None:
    """模拟明确声明的预览端口。"""
    capture.capture(node_id="preview", definition=SimpleNamespace(
        capability_tags=("ui.preview",), node_type_id="core.io.value-preview",
        output_ports=(SimpleNamespace(name="body"),),
    ), outputs={"body": {"type": "value-preview", "value": value}},
        invocation_id=invocation, duration_ms=1.2)


def test_capture_isolated_bounded_and_iteration_identity() -> None:
    """下游修改业务容器不污染显示；循环身份明确；超限只影响显示。"""
    capture = RuntimePreviewCapture()
    value = {"rows": [1, 2]}
    _capture(capture, value, "loop[1].preview")
    value["rows"].append(3)
    assert capture.records[("preview", "body")]["payload"]["value"]["rows"] == [1, 2]
    _capture(capture, value, "loop[2].preview")
    assert len(capture.records) == 1
    assert capture.records[("preview", "body")]["invocation_id"] == "loop[2].preview"
    capture.budget[0] = 3
    _capture(capture, "too large")
    assert capture.error == "preview_size_limit"
    assert capture.records == {}


def test_capture_never_reads_runtime_image_objects() -> None:
    """不读取 mmap/矩阵或调用对象的自定义序列化方法。"""
    capture = RuntimePreviewCapture()
    _capture(capture, object())
    assert capture.error == "preview_not_json"
    assert capture.records == {}


def test_subscription_limit_and_disconnect_release() -> None:
    """连接上限显式拒绝，第一个到最后一个页面的观察信号必须正确。"""
    async def check():
        parent, child = socket.socketpair()
        observed = Event()
        channel = RuntimePreviewChannel(parent, observed)
        try:
            subscriptions = [channel.subscribe() for _ in range(16)]
            with pytest.raises(RuntimePreviewCapacityError, match="capacity"):
                channel.subscribe()
            for subscription in subscriptions[:-1]:
                channel.unsubscribe(subscription)
            assert observed.is_set()
            channel.unsubscribe(subscriptions[-1])
            assert not channel.subscriptions and not observed.is_set()
            channel.close()
            with pytest.raises(RuntimePreviewUnavailableError, match="unavailable"):
                channel.subscribe()
        finally:
            channel.close()
            child.close()
    asyncio.run(check())


def test_readonly_node_definitions_require_published_definition_identity() -> None:
    """监视画布只使用与发布依赖摘要一致的当前节点定义。"""
    definition = NodeDefinition(
        node_type_id="core.test.preview-definition",
        display_name="Preview",
        category="core.test.preview",
        implementation_kind="core-node",
        runtime_kind="python-callable",
    )
    service = object.__new__(WorkflowRuntimeService)
    service.node_catalog_registry = SimpleNamespace(
        get_workflow_node_definitions=lambda: (definition,)
    )
    template = {"nodes": [{"node_type_id": definition.node_type_id}]}
    dependencies = {
        "nodes": [
            {
                "node_type_id": definition.node_type_id,
                "definition_sha256": build_node_definition_sha256(definition),
            }
        ]
    }

    matched, warnings = service._build_runtime_preview_node_definitions(
        template=template,
        dependencies=dependencies,
    )
    assert [item["node_type_id"] for item in matched] == [definition.node_type_id]
    assert warnings == []

    dependencies["nodes"][0]["definition_sha256"] = "changed"
    matched, warnings = service._build_runtime_preview_node_definitions(
        template=template,
        dependencies=dependencies,
    )
    assert matched == []
    assert warnings == [
        {"node_type_id": definition.node_type_id, "reason": "definition_changed"}
    ]


def test_graph_failure_preserves_only_finished_preview_without_node_records() -> None:
    """节点产生预览后后续业务失败，副本仍可交接，不依赖 full records。"""
    registry = WorkflowNodeRuntimeRegistry()
    definition = NodeDefinition(node_type_id="core.test.preview", display_name="Preview", category="test",
        implementation_kind="core-node", runtime_kind="python-callable", capability_tags=("ui.preview",),
        output_ports=(NodePortDefinition(name="body", display_name="Body", payload_type_id="value.v1"),))
    registry.register_python_callable(definition, lambda request: {"body": {"type": "value-preview", "value": {"zero": 0, "flag": False}}})
    fail = NodeDefinition(node_type_id="core.test.fail", display_name="Fail", category="test",
        implementation_kind="core-node", runtime_kind="python-callable",
        input_ports=(NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),))
    def fail_handler(request):
        raise InvalidRequestError("after preview")
    registry.register_python_callable(fail, fail_handler)
    template = WorkflowGraphTemplate(template_id="preview-test", template_version="1.0.0", display_name="Preview Test",
        nodes=(WorkflowGraphNode(node_id="preview", node_type_id=definition.node_type_id), WorkflowGraphNode(node_id="fail", node_type_id=fail.node_type_id)),
        edges=(WorkflowGraphEdge(edge_id="dependency", source_node_id="preview", source_port="body", target_node_id="fail", target_port="value"),))
    capture = RuntimePreviewCapture()
    with pytest.raises(InvalidRequestError, match="after preview"):
        WorkflowGraphExecutor(registry=registry).execute(template=template, input_values={},
            execution_metadata={PREVIEW_CAPTURE_KEY: capture, "retain_node_records_enabled": False, "workflow_run_record_mode": "none"})
    assert capture.records[("preview", "body")]["payload"]["value"] == {"zero": 0, "flag": False}


def test_subscription_drops_when_sending_and_has_no_replay() -> None:
    """未就绪和正在发送时直接略过，不追加下一条结果。"""
    async def check() -> None:
        subscription = RuntimePreviewSubscription()
        subscription.offer("before subscribe")
        first = asyncio.create_task(subscription.receive())
        await asyncio.sleep(0)
        subscription.offer("one")
        subscription.offer("two")
        assert await first == "one"
        subscription.offer("three")
        second = asyncio.create_task(subscription.receive())
        await asyncio.sleep(0)
        assert not second.done()
        subscription.offer("four")
        assert await second == "four"
        third = asyncio.create_task(subscription.receive())
        await asyncio.sleep(0)
        subscription.close()
        assert await third is None
    asyncio.run(check())


def test_separate_channel_no_subscriber_no_capture_and_cleanup() -> None:
    """线程/socket 成对回收；无页面不捕获，发送槽忙时不创建新副本。"""
    async def check() -> None:
        parent, child = socket.socketpair()
        observed = Event()
        channel = RuntimePreviewChannel(parent, observed)
        sender = RuntimePreviewSender(child, observed)
        try:
            assert sender.begin() is None
            assert sender.thread is None
            subscription = channel.subscribe()
            receive = asyncio.create_task(subscription.receive())
            await asyncio.sleep(0)
            capture = sender.begin()
            assert capture is not None
            assert sender.begin() is None
            _capture(capture, {"ok": True})
            sender.finish(capture, {"workflow_run_id": "run-1", "state": "succeeded"})
            text = await asyncio.wait_for(receive, timeout=3)
            assert len(text) < MAX_PREVIEW_BYTES
            assert json.loads(text)["displays"][0]["payload"]["value"] == {"ok": True}
            channel.unsubscribe(subscription)
            assert not observed.is_set()
            assert sender.begin() is None
        finally:
            sender.close()
            channel.close()
        assert not channel.thread.is_alive()
        assert sender.thread is None or not sender.thread.is_alive()
        assert parent.fileno() == child.fileno() == -1
    asyncio.run(check())


def test_worker_epoch_channel_close_wakes_waiter() -> None:
    """Runtime 停止/换代必须断开旧观察，不能将旧帧带入新代。"""
    async def check() -> None:
        parent, child = socket.socketpair()
        channel = RuntimePreviewChannel(parent, Event())
        subscription = channel.subscribe()
        waiter = asyncio.create_task(subscription.receive())
        await asyncio.sleep(0)
        channel.close()
        child.close()
        assert await asyncio.wait_for(waiter, 1) is None
        assert not channel.subscriptions
    asyncio.run(check())


def test_observation_thread_failure_closes_socket_without_failing_runtime(monkeypatch) -> None:
    """显示基础资源不可用时只拒绝订阅；关闭未启动线程也必须幂等。"""
    from threading import Thread

    def fail_start(self):
        raise RuntimeError("thread unavailable")

    parent, child = socket.socketpair()
    monkeypatch.setattr(Thread, "start", fail_start)
    channel = RuntimePreviewChannel(parent, Event())
    assert channel.closed and parent.fileno() == -1
    channel.close()
    child.close()
