"""完整三维证据不得通过节点摘要再复制进入控制消息。"""

import json
import pytest

from backend.service.application.workflows.preview.events import PreviewNodeEvents


def test_large_port_summary_does_not_overflow_control_event():
    """保留节点身份/终态；完整值沿 value.updated 通道，摘要明确标注。"""
    events = []
    observer = PreviewNodeEvents(lambda kind, payload: events.append((kind, payload)), ["preview"])
    body = {"items": [{"text": "x" * 8000} for _ in range(600)]}
    observer({"event_type": "node.started", "payload": {"node_id": "preview", "inputs": {"evidence": body}}})
    observer({"event_type": "node.completed", "payload": {"node_id": "preview", "outputs": {"body": body}, "duration_ms": 1.2}})
    assert all(len(json.dumps(payload).encode()) < 4 * 1024**2 for _, payload in events)
    assert events[1][1]["status"] == "succeeded"
    assert events[0][1]["invocation_id"] == events[1][1]["invocation_id"]
    assert events[1][1]["outputs"]["summary"] is True
    assert len(body["items"]) == 600


def test_escaped_strings_do_not_bypass_control_byte_limit():
    """已脱敏的短字符串仍可能经 JSON 转义放大，按真实编码计费。"""
    events = []
    observer = PreviewNodeEvents(lambda kind, payload: events.append(payload), ["n"])
    body = {"items": ["\u0001" * 8000 for _ in range(128)]}
    observer({"event_type": "node.completed", "payload": {"node_id": "n", "outputs": body}})
    assert len(json.dumps(events[0], ensure_ascii=False).encode()) < 4 * 1024**2
    assert events[0]["outputs"]["summary"] is True
    assert len(body["items"]) == 128


@pytest.mark.parametrize("code,status", [("operation_timeout", "timed_out"), ("operation_cancelled", "cancelled")])
def test_bounded_error_keeps_control_terminal_state(code, status):
    """大错误详情不能把取消/超时改成普通失败，也不能残留活动调用。"""
    events = []
    observer = PreviewNodeEvents(lambda kind, payload: events.append((kind, payload)), ["n"])
    observer({"event_type": "node.started", "payload": {"node_id": "n"}})
    observer({"event_type": "node.failed", "payload": {"node_id": "n", "error_details": {
        "code": code, "details": "x" * (5 * 1024**2),
    }}})
    result = events[-1][1]
    assert result["status"] == status
    assert result["error_details"]["code"] == code
    assert result["error_details"]["summary"] is True
    assert observer.current() == {}
