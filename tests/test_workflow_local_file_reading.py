"""目录最新文件、文件记录和有界本地读取的确定性回归。"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from PIL import Image

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.core_nodes.io.directory.directory_latest_file import (
    CORE_NODE_SPEC as LATEST,
)
from backend.nodes.core_nodes.io.directory.directory_scan import CORE_NODE_SPEC as SCAN
from backend.nodes.core_nodes.io.local.image_load_local import CORE_NODE_SPEC as IMAGE
from backend.nodes.core_nodes.io.local.image_list_local import CORE_NODE_SPEC as IMAGES
from backend.nodes.core_nodes.io.local.json_load_local import CORE_NODE_SPEC as JSON
from backend.nodes.core_nodes.io.local.text_load_local import CORE_NODE_SPEC as TEXT
from backend.nodes.core_nodes.support.local_io.files import build_directory_file_record
from backend.nodes.core_nodes.support.local_io.reading import read_local_bytes
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRequest,
    WorkflowNodeRuntimeRegistry,
)


def call(spec, parameters=None, inputs=None, metadata=None):
    """用真实节点定义执行处理器。"""
    return spec.handler(
        WorkflowNodeExecutionRequest(
            node_id="test",
            node_definition=spec.node_definition,
            parameters=parameters or {},
            input_values=inputs or {},
            execution_metadata=metadata or {},
        )
    )


def test_latest_uses_mtime_not_name_with_deterministic_ties(tmp_path):
    """文件名日期与事件观察顺序不替代 mtime，同时间按路径倒序。"""
    for name, ns in (
        ("2099.json", 1_000_000_000),
        ("a.json", 2_000_000_000),
        ("b.json", 2_000_000_000),
    ):
        path = tmp_path / name
        path.write_text("{}")
        os.utime(path, ns=(ns, ns))
    result = call(LATEST, {"directory_path": str(tmp_path), "extensions": ["json"]})
    record = result["file"]["value"]
    assert record["file_name"] == "b.json"
    assert record["format_id"] == "amvision.local-file-record.v1"
    assert isinstance(record["observed_version"]["inode"], str)
    scan = call(
        SCAN,
        {
            "directory_path": str(tmp_path),
            "sort_by": "modified_time",
            "descending": True,
            "limit": 1,
        },
    )
    assert scan["files"]["value"] == [record]
    assert result["summary"]["value"]["raw_count"] == 3


def test_filters_empty_and_directory_errors_are_explicit(tmp_path):
    """空结果不等待，目录不存在不是空结果；过滤和稳定年龄可组合。"""
    (tmp_path / ".hidden.json").write_text("{}")
    (tmp_path / "a.txt").write_text("text")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "a.json").write_text("{}")
    params = {"directory_path": str(tmp_path), "extensions": ["JSON"]}
    assert call(LATEST, params)["file"]["value"] is None
    assert (
        call(LATEST, {**params, "recursive": True})["file"]["value"]["file_name"]
        == "a.json"
    )
    assert (
        call(LATEST, {**params, "recursive": True, "min_stable_age_seconds": 60})[
            "summary"
        ]["value"]["unstable_skipped_count"]
        == 1
    )
    with pytest.raises(InvalidRequestError):
        call(LATEST, {"directory_path": str(tmp_path / "absent")})
    for age in (float("nan"), float("inf"), -1, True):
        with pytest.raises(InvalidRequestError):
            call(LATEST, {**params, "min_stable_age_seconds": age})


@pytest.mark.parametrize("spec", [JSON, TEXT, IMAGE])
def test_record_input_cannot_silently_fall_back(spec, tmp_path):
    """null/样本/双输入拒绝；连接 File 不退回固定路径。"""
    for inputs in (
        {"file": {"value": None}},
        {"file": {"value": {"path": str(tmp_path)}}},
        {"file": {"value": None}, "path": {"value": str(tmp_path)}},
    ):
        with pytest.raises(InvalidRequestError):
            call(spec, {"local_path": str(tmp_path)}, inputs)


def test_json_text_and_image_records_keep_source(tmp_path):
    """读取结果携带同一来源记录，保留标准业务输出类型。"""
    stream = io.BytesIO()
    Image.new("RGB", (12, 8)).save(stream, format="PNG")
    for spec, name, content, port in (
        (JSON, "a.json", b'{"items":[1,2]}', "value"),
        (TEXT, "a.txt", "批次 abc".encode(), "text"),
        (IMAGE, "a.png", stream.getvalue(), "image"),
    ):
        path = tmp_path / name
        path.write_bytes(content)
        record = build_directory_file_record(path)
        output = call(spec, inputs={"file": {"value": record}})
        assert port in output
        assert (
            output["summary"]["value"]["observed_version"] == record["observed_version"]
        )
    with pytest.raises(InvalidRequestError, match="max_pixels"):
        call(IMAGE, {"local_path": str(tmp_path / "a.png"), "max_pixels": 90})


def test_changed_removed_large_and_bad_encoding_fail(tmp_path):
    """选取后变化、删除、超限不被 JSON 回退开关吞掉。"""
    path = tmp_path / "a.json"
    path.write_bytes(b"{}")
    record = build_directory_file_record(path)
    path.write_bytes(b"[1,2]")
    with pytest.raises(InvalidRequestError) as exc:
        call(JSON, {"allow_invalid_json": True}, {"file": {"value": record}})
    assert exc.value.details["error_code"] == "local_file_changed"
    path.unlink()
    with pytest.raises(InvalidRequestError) as exc:
        call(JSON, {"allow_missing": True}, {"file": {"value": record}})
    assert exc.value.details["error_code"] == "local_file_missing"
    path.write_bytes(b"[1,2]")
    for spec in (JSON, TEXT):
        with pytest.raises(InvalidRequestError) as exc:
            call(
                spec,
                {"local_path": str(path), "max_bytes": 4, "allow_invalid_json": True},
            )
        assert exc.value.details["error_code"] == "local_file_too_large"
        assert call(spec, {"local_path": str(path), "max_bytes": 5})
    path.write_bytes(b"\xff")
    with pytest.raises(InvalidRequestError):
        call(TEXT, {"local_path": str(path)})


def test_replacement_during_read_is_detected(tmp_path, monkeypatch):
    """读取中路径被替换时不把旧内容报告成新文件。"""
    path = tmp_path / "a.json"
    path.write_bytes(b"{}")
    original = Path.open

    class ReplacingReader:
        """保持原句柄，read 后模拟生产者替换同名路径。"""

        def __enter__(self):
            self.stream = original(path, "rb")
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            data = self.stream.read(size)
            # Windows 不允许打开句柄时 replace；同一路径写入同样能模拟变化。
            with original(path, "wb") as writer:
                writer.write(b"[1,2]")
            return data

    monkeypatch.setattr(Path, "open", lambda self, *args, **kwargs: ReplacingReader())
    with pytest.raises(InvalidRequestError) as exc:
        read_local_bytes(path, max_bytes=100)
    assert exc.value.details["error_code"] == "local_file_changed"


def test_image_list_keeps_records_and_total_limit(tmp_path):
    """图像列表保留来源，复用观察版本检查和显式资源上限。"""
    records = []
    for index in range(2):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (8, 8)).save(path)
        records.append(build_directory_file_record(path))
    inputs = {"files": {"value": records}}
    result = call(IMAGES, inputs=inputs)
    assert result["summary"]["value"]["files"] == records
    with pytest.raises(InvalidRequestError, match="max_bytes"):
        call(IMAGES, {"max_total_bytes": records[0]["size_bytes"]}, inputs)
    (tmp_path / "0.png").write_bytes(b"changed")
    with pytest.raises(InvalidRequestError) as exc:
        call(IMAGES, inputs=inputs)
    assert exc.value.details["error_code"] == "local_file_changed"


def test_image_media_type_comes_from_content_not_suffix(tmp_path):
    """扩展名不能覆盖已识别出的 PNG 内容类型。"""
    path = tmp_path / "actually-png.jpg"
    Image.new("RGB", (8, 8)).save(path, format="PNG")
    result = call(IMAGE, {"local_path": str(path)})
    assert result["image"]["media_type"] == "image/png"


def test_real_graph_latest_to_loader_and_dynamic_path(tmp_path):
    """验证目录参数端口 → 文件记录 → JSON 内容 → 图输出全链路。"""
    (tmp_path / "a.json").write_text('{"batch":"abc"}')
    registry = WorkflowNodeRuntimeRegistry()
    for spec in (LATEST, JSON):
        registry.register_python_callable(spec.node_definition, spec.handler)
    template = WorkflowGraphTemplate(
        template_id="local-file-test",
        template_version="1.0.0",
        display_name="Local File Test",
        nodes=(
            WorkflowGraphNode(
                node_id="latest", node_type_id=LATEST.node_definition.node_type_id
            ),
            WorkflowGraphNode(
                node_id="load", node_type_id=JSON.node_definition.node_type_id
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="file",
                source_node_id="latest",
                source_port="file",
                target_node_id="load",
                target_port="file",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="directory",
                display_name="Directory",
                payload_type_id="value.v1",
                target_node_id="latest",
                target_port="path",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="json",
                display_name="JSON",
                payload_type_id="value.v1",
                source_node_id="load",
                source_port="value",
            ),
        ),
    )
    result = WorkflowGraphExecutor(registry=registry).execute(
        template=template,
        input_values={"directory": {"value": str(tmp_path)}},
        execution_metadata={},
    )
    assert result.outputs["json"]["value"] == {"batch": "abc"}
    with pytest.raises(OperationTimeoutError):
        call(
            LATEST,
            {"directory_path": str(tmp_path)},
            metadata={"_workflow_execution_deadline_monotonic": 1.0},
        )
