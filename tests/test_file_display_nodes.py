"""文件节点和显示节点的实际 handler 契约。"""

from dataclasses import replace

import pytest

from backend.nodes.core_nodes.io.preview.value_display import CORE_NODE_SPEC as DISPLAY
from backend.nodes.core_nodes.io.output.storage.jsonl_append_local import (
    CORE_NODE_SPEC as APPEND,
)
from backend.nodes.core_nodes.io.local.jsonl_load_local import CORE_NODE_SPEC as READ
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.io.jsonl import append_record, read_records
from backend.service.application.workflows.runtime_preview import RuntimePreviewCapture


def request(spec, parameters=None, inputs=None, metadata=None):
    """构造节点请求，不需要运行部署服务。"""
    return WorkflowNodeExecutionRequest(
        node_id="node",
        node_definition=spec.node_definition,
        parameters=parameters or {},
        input_values=inputs or {},
        execution_metadata=metadata or {},
    )


def test_value_display_capture_and_errors():
    """新类型可被 Runtime 捕获，缺失字段仍是 null。"""
    req = request(
        DISPLAY,
        {
            "fields": [
                {
                    "path": "state",
                    "label": "本次",
                    "format": "status",
                    "states": {"OK": "success"},
                },
                {"path": "absent", "label": "缺失"},
            ]
        },
        {
            "value": {"value": {"state": "OK"}},
            "context": {
                "value": {"generation": "a", "sequence": 1, "snapshot_revision": "r"}
            },
        },
    )
    output = DISPLAY.handler(req)
    assert output["body"]["fields"][1]["value"] is None
    capture = RuntimePreviewCapture()
    capture.capture(
        node_id="node",
        definition=DISPLAY.node_definition,
        outputs=output,
        invocation_id="call",
        duration_ms=1,
    )
    assert len(capture.records) == 1
    with pytest.raises(InvalidRequestError):
        DISPLAY.handler(
            replace(req, parameters={"fields": [{"path": "state", "precision": 99}]})
        )


@pytest.mark.parametrize(
    "metadata",
    [{}, {"_preview_execution": True}, {"_editor_preview_observer": object()}],
)
def test_append_writes_in_preview_and_runtime(tmp_path, metadata):
    """两种预览标记及正式执行都提交记录，不需要额外开关。"""
    path = tmp_path / "records.jsonl"
    req = request(
        APPEND,
        {"save_location": str(path)},
        {"value": {"value": {"total": 24}}},
        metadata,
    )
    receipt = APPEND.handler(req)["receipt"]["value"]
    assert receipt["write_state"] == "committed"
    assert receipt["file"]["local_path"] == str(path)
    assert read_records(path)["records"] == [{"total": 24}]


def test_append_preview_errors_are_not_reported_as_skipped(tmp_path):
    """预览写入失败直接报错，不能回退为成功跳过。"""
    parent = tmp_path / "not-a-directory"
    parent.write_text("occupied", encoding="utf-8")
    req = request(
        APPEND,
        {"save_location": str(parent / "r.jsonl")},
        {"value": {"value": {}}},
        {"_preview_execution": True},
    )
    with pytest.raises((OSError, InvalidRequestError)):
        APPEND.handler(req)


def test_read_node_cursor_roundtrip(tmp_path):
    """使用真实文件验证 value.v1 输入输出链路。"""
    path = tmp_path / "test.jsonl"
    append_record(path, {"total": 80}, operation="one")
    first = READ.handler(request(READ, {"local_path": str(path)}))
    assert first["records"]["value"] == [{"total": 80}]
    second = READ.handler(
        request(READ, {"local_path": str(path)}, {"cursor": first["next_cursor"]})
    )
    assert second["records"]["value"] == []
