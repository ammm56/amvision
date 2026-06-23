"""工业输入输出节点轻量回归测试。"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from PIL import Image

from backend.nodes.core_nodes.io.batch.batch_files_relocate import (
    _batch_files_relocate_handler,
)
from backend.nodes.core_nodes.io.directory.directory_cursor_advance import (
    _directory_cursor_advance_handler,
)
from backend.nodes.core_nodes.io.directory.directory_cursor_normalize import (
    _directory_cursor_normalize_handler,
)
from backend.nodes.core_nodes.io.directory.directory_batch_window import (
    _directory_batch_window_handler,
)
from backend.nodes.core_nodes.io.directory.directory_poll_window import (
    _directory_poll_window_handler,
)
from backend.nodes.core_nodes.io.directory.directory_scan import _directory_scan_handler
from backend.nodes.core_nodes.io.local.image_list_local import _image_list_local_handler
from backend.nodes.core_nodes.io.local.image_load_local import _image_load_local_handler
from backend.nodes.core_nodes.io.local.json_load_local import _json_load_local_handler
from backend.nodes.core_nodes.output.batch_record import _batch_record_handler
from backend.nodes.core_nodes.output.batch_result_summary import (
    _batch_result_summary_handler,
)
from backend.nodes.core_nodes.output.csv_append_local import _csv_append_local_handler
from backend.nodes.core_nodes.output.http_post import _http_post_handler
from backend.nodes.core_nodes.output.json_save_local import _json_save_local_handler
from backend.nodes.core_nodes.output.workflow_result import _workflow_result_handler
from backend.nodes.runtime_support import require_execution_image_registry
from backend.service.application.errors import InvalidRequestError, OperationTimeoutError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def test_image_load_local_handler_registers_memory_image(tmp_path: Path) -> None:
    """验证本地图像载入节点会输出 memory image-ref 与摘要。"""

    image_path = tmp_path / "sample.png"
    image_path.write_bytes(_build_png_bytes(width=8, height=6))
    execution_metadata: dict[str, object] = {}

    output = _image_load_local_handler(
        WorkflowNodeExecutionRequest(
            node_id="image-load-local",
            node_definition=object(),
            parameters={"local_path": str(image_path)},
            input_values={},
            execution_metadata=execution_metadata,
        )
    )

    assert output["image"]["transport_kind"] == "memory"
    assert output["image"]["width"] == 8
    assert output["image"]["height"] == 6
    assert output["summary"]["value"]["local_path"] == str(image_path.resolve())
    image_registry = require_execution_image_registry(
        WorkflowNodeExecutionRequest(
            node_id="image-load-local",
            node_definition=object(),
            parameters={},
            input_values={},
            execution_metadata=execution_metadata,
        )
    )
    assert image_registry.read_bytes(output["image"]["image_handle"]).startswith(
        b"\x89PNG"
    )


def test_directory_scan_handler_filters_extensions_and_limit(tmp_path: Path) -> None:
    """验证目录扫描节点会按扩展名和数量上限筛选。"""

    (tmp_path / "a.png").write_bytes(b"a")
    (tmp_path / "b.jpg").write_bytes(b"bb")
    (tmp_path / "c.txt").write_bytes(b"ccc")

    output = _directory_scan_handler(
        WorkflowNodeExecutionRequest(
            node_id="directory-scan",
            node_definition=object(),
            parameters={
                "directory_path": str(tmp_path),
                "extensions": ["png", ".jpg"],
                "sort_by": "name",
                "limit": 2,
            },
            input_values={},
            execution_metadata={},
        )
    )

    files_value = output["files"]["value"]
    assert len(files_value) == 2
    assert files_value[0]["file_name"] == "a.png"
    assert files_value[1]["file_name"] == "b.jpg"
    assert output["summary"]["value"]["count"] == 2


def test_directory_scan_handler_filters_unstable_files_and_dedupes_by_file_name_size(
    tmp_path: Path,
) -> None:
    """验证目录扫描节点支持稳定期过滤和按文件名+大小去重。"""

    first_file = tmp_path / "dup-a.png"
    second_file = tmp_path / "dup-b.png"
    duplicate_dir = tmp_path / "nested"
    duplicate_dir.mkdir()
    duplicate_file = duplicate_dir / "dup-a.png"
    first_file.write_bytes(b"same")
    second_file.write_bytes(b"newer")
    duplicate_file.write_bytes(b"same")
    stable_timestamp = 1_700_000_000
    fresh_timestamp = stable_timestamp + 10
    os.utime(first_file, (stable_timestamp, stable_timestamp))
    os.utime(duplicate_file, (stable_timestamp, stable_timestamp))
    os.utime(second_file, (fresh_timestamp, fresh_timestamp))

    with patch(
        "backend.nodes.core_nodes.io.directory.directory_scan.time.time",
        return_value=fresh_timestamp,
    ):
        output = _directory_scan_handler(
            WorkflowNodeExecutionRequest(
                node_id="directory-scan",
                node_definition=object(),
                parameters={
                    "directory_path": str(tmp_path),
                    "recursive": True,
                    "extensions": ["png"],
                    "sort_by": "name",
                    "min_stable_age_seconds": 5,
                    "dedupe_by": "file_name_and_size",
                },
                input_values={},
                execution_metadata={},
            )
        )

    files_value = output["files"]["value"]
    assert len(files_value) == 1
    assert files_value[0]["file_name"] == "dup-a.png"
    assert output["summary"]["value"]["raw_count"] == 3
    assert output["summary"]["value"]["unstable_skipped_count"] == 1
    assert output["summary"]["value"]["deduped_count"] == 1


def test_json_save_local_handler_writes_result_record(tmp_path: Path) -> None:
    """验证本地 JSON 保存节点会把 result-record 写到指定位置。"""

    output_path = tmp_path / "inspection.json"

    output = _json_save_local_handler(
        WorkflowNodeExecutionRequest(
            node_id="json-save-local",
            node_definition=object(),
            parameters={"local_path": str(output_path), "indent": 2},
            input_values={
                "result": {
                    "ok_ng": "NG",
                    "ok": False,
                    "reason": "coverage too low",
                    "metrics": {"coverage_ratio": 0.12},
                }
            },
            execution_metadata={},
        )
    )

    assert output_path.is_file()
    assert '"ok_ng": "NG"' in output_path.read_text(encoding="utf-8")
    assert output["summary"]["value"]["record_kind"] == "result-record"


def test_http_post_handler_posts_json_and_returns_summary(monkeypatch: object) -> None:
    """验证 HTTP 回传节点会发送 JSON 并返回摘要。"""

    captured_request: dict[str, object] = {}

    def _fake_request(**kwargs: object) -> httpx.Response:
        captured_request.update(kwargs)
        request = httpx.Request(method=str(kwargs["method"]), url=str(kwargs["url"]))
        return httpx.Response(
            status_code=201,
            headers={"content-type": "application/json"},
            json={"accepted": True},
            request=request,
        )

    monkeypatch.setattr("backend.nodes.core_nodes.output.http_post._send_http_request", _fake_request)

    output = _http_post_handler(
        WorkflowNodeExecutionRequest(
            node_id="http-post",
            node_definition=object(),
            parameters={"url": "http://example.test/callback", "method": "POST"},
            input_values={
                "value": {"value": {"ok_ng": "OK", "station_id": "line-a-01"}}
            },
            execution_metadata={},
        )
    )

    assert captured_request["method"] == "POST"
    assert captured_request["url"] == "http://example.test/callback"
    assert captured_request["json"] == {"ok_ng": "OK", "station_id": "line-a-01"}
    assert output["response"]["value"]["ok"] is True
    assert output["response"]["value"]["status_code"] == 201
    assert output["response"]["value"]["body_json"]["accepted"] is True


def test_http_post_handler_maps_timeout_to_operation_timeout(
    monkeypatch: object,
) -> None:
    """验证 HTTP 超时会转换为节点超时错误。"""

    def _fake_request(**_: object) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(
        "backend.nodes.core_nodes.output.http_post._send_http_request",
        _fake_request,
    )

    with pytest.raises(OperationTimeoutError):
        _http_post_handler(
            WorkflowNodeExecutionRequest(
                node_id="http-post-timeout",
                node_definition=object(),
                parameters={
                    "url": "http://example.test/callback",
                    "method": "POST",
                    "timeout_seconds": 0.1,
                },
                input_values={"value": {"value": {"ok_ng": "OK"}}},
                execution_metadata={},
            )
        )


def test_csv_append_local_handler_appends_alarm_record(tmp_path: Path) -> None:
    """验证 CSV 追加节点会把报警对象扁平化后写入本地文件。"""

    output_path = tmp_path / "alarms.csv"

    output = _csv_append_local_handler(
        WorkflowNodeExecutionRequest(
            node_id="csv-append-local",
            node_definition=object(),
            parameters={"local_path": str(output_path)},
            input_values={
                "alarm": {
                    "active": True,
                    "level": "warning",
                    "message": "glue coverage low",
                    "metrics": {"coverage_ratio": 0.12},
                }
            },
            execution_metadata={},
        )
    )

    csv_text = output_path.read_text(encoding="utf-8")
    assert "active,level,message,metrics.coverage_ratio" in csv_text
    assert "True,warning,glue coverage low,0.12" in csv_text
    assert output["summary"]["value"]["record_kind"] == "alarm-record"


def test_directory_batch_window_handler_returns_subset() -> None:
    """验证目录批次窗口节点会按起始索引和批次大小切片。"""

    output = _directory_batch_window_handler(
        WorkflowNodeExecutionRequest(
            node_id="directory-batch-window",
            node_definition=object(),
            parameters={"start_index": 1, "batch_size": 2},
            input_values={
                "files": {
                    "value": [
                        {"path": "W:/tmp/a.png", "file_name": "a.png"},
                        {"path": "W:/tmp/b.png", "file_name": "b.png"},
                        {"path": "W:/tmp/c.png", "file_name": "c.png"},
                    ]
                }
            },
            execution_metadata={},
        )
    )

    batch_files = output["files"]["value"]
    assert len(batch_files) == 2
    assert batch_files[0]["file_name"] == "b.png"
    assert output["summary"]["value"]["has_next"] is False
    assert output["summary"]["value"]["next_start_index"] == 3
    assert output["cursor"]["value"]["completed"] is True


def test_directory_batch_window_handler_accepts_runtime_start_index_and_batch_size() -> (
    None
):
    """验证目录批次窗口节点支持运行时 start_index 和 batch_size 输入。"""

    output = _directory_batch_window_handler(
        WorkflowNodeExecutionRequest(
            node_id="directory-batch-window",
            node_definition=object(),
            parameters={"start_index": 0, "batch_size": 8},
            input_values={
                "files": {
                    "value": [
                        {"path": "W:/tmp/a.png", "file_name": "a.png"},
                        {"path": "W:/tmp/b.png", "file_name": "b.png"},
                        {"path": "W:/tmp/c.png", "file_name": "c.png"},
                        {"path": "W:/tmp/d.png", "file_name": "d.png"},
                    ]
                },
                "start_index": {"value": 1},
                "batch_size": {"value": 2},
            },
            execution_metadata={},
        )
    )

    batch_files = output["files"]["value"]
    assert len(batch_files) == 2
    assert batch_files[0]["file_name"] == "b.png"
    assert batch_files[1]["file_name"] == "c.png"
    assert output["summary"]["value"]["start_index"] == 1
    assert output["summary"]["value"]["batch_size"] == 2
    assert output["summary"]["value"]["has_next"] is True
    assert output["summary"]["value"]["next_start_index"] == 3


def test_directory_batch_window_handler_rejects_empty_directory() -> None:
    """验证目录批次窗口节点在空目录输入下沿用当前报错语义。"""

    with pytest.raises(InvalidRequestError, match="当前没有可处理文件"):
        _directory_batch_window_handler(
            WorkflowNodeExecutionRequest(
                node_id="directory-batch-window",
                node_definition=object(),
                parameters={"batch_size": 4},
                input_values={"files": {"value": []}},
                execution_metadata={},
            )
        )


def test_directory_batch_window_handler_accepts_cursor_last_path() -> None:
    """验证目录批次窗口节点支持按 cursor.last_path 继续推进。"""

    output = _directory_batch_window_handler(
        WorkflowNodeExecutionRequest(
            node_id="directory-batch-window",
            node_definition=object(),
            parameters={"batch_size": 2},
            input_values={
                "files": {
                    "value": [
                        {"path": "W:/tmp/a.png", "file_name": "a.png"},
                        {"path": "W:/tmp/b.png", "file_name": "b.png"},
                        {"path": "W:/tmp/c.png", "file_name": "c.png"},
                    ]
                },
                "cursor": {
                    "value": {"last_path": "W:/tmp/a.png", "next_start_index": 1}
                },
            },
            execution_metadata={},
        )
    )

    batch_files = output["files"]["value"]
    assert len(batch_files) == 2
    assert batch_files[0]["file_name"] == "b.png"
    assert output["summary"]["value"]["start_source"] == "cursor.last_path"
    assert output["summary"]["value"]["cursor_anchor_found"] is True


def test_directory_poll_window_handler_returns_no_work_for_empty_file_list() -> None:
    """验证目录轮询窗口节点在空文件列表下返回 has_work=false，而不是直接报错。"""

    output = _directory_poll_window_handler(
        WorkflowNodeExecutionRequest(
            node_id="directory-poll-window",
            node_definition=object(),
            parameters={"batch_size": 4},
            input_values={"files": {"value": []}},
            execution_metadata={},
        )
    )

    assert output["files"]["value"] == []
    assert output["has_work"]["value"] is False
    assert output["summary"]["value"]["empty"] is True
    assert output["summary"]["value"]["no_work_reason"] == "no-files"
    assert output["cursor"]["value"]["next_start_index"] == 0


def test_directory_poll_window_handler_returns_no_new_files_when_cursor_reaches_end() -> (
    None
):
    """验证目录轮询窗口节点在 cursor 已推进到末尾时返回 no-new-files。"""

    output = _directory_poll_window_handler(
        WorkflowNodeExecutionRequest(
            node_id="directory-poll-window",
            node_definition=object(),
            parameters={"batch_size": 2},
            input_values={
                "files": {
                    "value": [
                        {"path": "W:/tmp/a.png", "file_name": "a.png"},
                        {"path": "W:/tmp/b.png", "file_name": "b.png"},
                    ]
                },
                "cursor": {
                    "value": {"last_path": "W:/tmp/b.png", "next_start_index": 2}
                },
            },
            execution_metadata={},
        )
    )

    assert output["files"]["value"] == []
    assert output["has_work"]["value"] is False
    assert output["summary"]["value"]["no_work_reason"] == "no-new-files"
    assert output["summary"]["value"]["start_source"] == "cursor.last_path"
    assert output["cursor"]["value"]["last_path"] == str(Path("W:/tmp/b.png").resolve())


def test_directory_poll_window_handler_returns_next_batch_when_new_files_exist() -> None:
    """验证目录轮询窗口节点在存在新文件时会返回实际批次。"""

    output = _directory_poll_window_handler(
        WorkflowNodeExecutionRequest(
            node_id="directory-poll-window",
            node_definition=object(),
            parameters={"batch_size": 2},
            input_values={
                "files": {
                    "value": [
                        {"path": "W:/tmp/a.png", "file_name": "a.png"},
                        {"path": "W:/tmp/b.png", "file_name": "b.png"},
                        {"path": "W:/tmp/c.png", "file_name": "c.png"},
                    ]
                },
                "cursor": {
                    "value": {"last_path": "W:/tmp/a.png", "next_start_index": 1}
                },
            },
            execution_metadata={},
        )
    )

    batch_files = output["files"]["value"]
    assert output["has_work"]["value"] is True
    assert [item["file_name"] for item in batch_files] == ["b.png", "c.png"]
    assert output["summary"]["value"]["no_work_reason"] is None
    assert output["cursor"]["value"]["last_path"] == str(Path("W:/tmp/c.png").resolve())


def test_directory_cursor_normalize_handler_normalizes_summary_cursor() -> None:
    """验证目录游标规范化节点可直接读取 window summary 中的 cursor。"""

    output = _directory_cursor_normalize_handler(
        WorkflowNodeExecutionRequest(
            node_id="directory-cursor-normalize",
            node_definition=object(),
            parameters={},
            input_values={
                "cursor": {
                    "value": {
                        "start_index": 1,
                        "window_first_path": "W:/tmp/b.png",
                        "cursor": {
                            "next_start_index": 3,
                            "count": 2,
                            "last_path": "W:/tmp/c.png",
                            "has_next": False,
                        },
                    }
                }
            },
            execution_metadata={},
        )
    )

    cursor_value = output["cursor"]["value"]
    assert cursor_value["start_index"] == 0
    assert cursor_value["next_start_index"] == 3
    assert cursor_value["count"] == 2
    assert cursor_value["last_path"] == str(Path("W:/tmp/c.png").resolve())
    assert output["summary"]["value"]["source"] == "input.cursor.cursor"


def test_directory_cursor_normalize_handler_uses_default_value() -> None:
    """验证目录游标规范化节点可回退默认值。"""

    output = _directory_cursor_normalize_handler(
        WorkflowNodeExecutionRequest(
            node_id="directory-cursor-normalize",
            node_definition=object(),
            parameters={
                "default_value": {"next_start_index": 4, "last_path": "W:/tmp/d.png"},
                "default_batch_size": 2,
            },
            input_values={},
            execution_metadata={},
        )
    )

    cursor_value = output["cursor"]["value"]
    assert cursor_value["next_start_index"] == 4
    assert cursor_value["batch_size"] == 2
    assert cursor_value["last_path"] == str(Path("W:/tmp/d.png").resolve())


def test_directory_cursor_advance_handler_merges_previous_and_window_cursor() -> None:
    """验证目录游标推进节点会基于 window cursor 生成下一版 cursor。"""

    output = _directory_cursor_advance_handler(
        WorkflowNodeExecutionRequest(
            node_id="directory-cursor-advance",
            node_definition=object(),
            parameters={},
            input_values={
                "cursor": {
                    "value": {"next_start_index": 1, "last_path": "W:/tmp/a.png", "completed": False}
                },
                "window_cursor": {
                    "value": {
                        "start_index": 1,
                        "end_index": 3,
                        "next_start_index": 3,
                        "count": 2,
                        "batch_size": 2,
                        "total_count": 3,
                        "has_next": False,
                        "completed": True,
                        "last_path": "W:/tmp/c.png",
                        "has_work": True,
                        "empty": False,
                    }
                },
            },
            execution_metadata={},
        )
    )

    cursor_value = output["cursor"]["value"]
    assert cursor_value["next_start_index"] == 3
    assert cursor_value["last_path"] == str(Path("W:/tmp/c.png").resolve())
    assert cursor_value["completed"] is True
    assert output["summary"]["value"]["advanced"] is True
    assert output["summary"]["value"]["advanced_count"] == 2


def test_batch_record_handler_builds_batch_archive_object() -> None:
    """验证批次归档节点会统一组装 batch record。"""

    output = _batch_record_handler(
        WorkflowNodeExecutionRequest(
            node_id="batch-record",
            node_definition=object(),
            parameters={"record_kind": "inspection-batch"},
            input_values={
                "scan_summary": {"value": {"directory_path": "W:/tmp", "count": 3}},
                "window_summary": {"value": {"count": 2, "has_next": True}},
                "cursor": {"value": {"next_start_index": 2, "last_path": "W:/tmp/b.png"}},
                "files": {
                    "value": [
                        {"path": "W:/tmp/a.png", "file_name": "a.png"},
                        {"path": "W:/tmp/b.png", "file_name": "b.png"},
                    ]
                },
                "inspection_results": {
                    "value": [
                        {"ok_ng": "OK", "ok": True, "reason": "ok"},
                        {
                            "ok_ng": "NG",
                            "ok": False,
                            "reason": "coverage low",
                            "alarm": {
                                "active": True,
                                "level": "warning",
                                "message": "coverage low",
                            },
                        },
                    ]
                },
            },
            execution_metadata={},
        )
    )

    record_value = output["record"]["value"]
    assert record_value["record_kind"] == "inspection-batch"
    assert len(record_value["batch_files"]) == 2
    assert record_value["inspection_result_summary"]["count"] == 2
    assert record_value["inspection_result_summary"]["ok_count"] == 1
    assert record_value["inspection_result_summary"]["ng_count"] == 1
    assert record_value["inspection_result_summary"]["alarm_count"] == 1


def test_batch_files_relocate_handler_copies_files_and_returns_mappings(
    tmp_path: Path,
) -> None:
    """验证批次文件归档节点会复制文件并输出目标映射。"""

    source_directory = tmp_path / "incoming"
    target_directory = tmp_path / "archive"
    source_directory.mkdir()
    first_file = source_directory / "a.png"
    second_file = source_directory / "nested" / "b.png"
    second_file.parent.mkdir()
    first_file.write_bytes(b"a")
    second_file.write_bytes(b"bb")

    output = _batch_files_relocate_handler(
        WorkflowNodeExecutionRequest(
            node_id="batch-files-relocate",
            node_definition=object(),
            parameters={
                "target_directory": str(target_directory),
                "mode": "copy",
                "preserve_subdirectories": True,
            },
            input_values={
                "files": {
                    "value": [
                        {"path": str(first_file)},
                        {"path": str(second_file)},
                    ]
                }
            },
            execution_metadata={},
        )
    )

    relocated_files = output["files"]["value"]
    mapping_items = output["mappings"]["value"]
    assert len(relocated_files) == 2
    assert len(mapping_items) == 2
    assert (target_directory / "a.png").is_file()
    assert (target_directory / "nested" / "b.png").is_file()
    assert output["summary"]["value"]["relocated_count"] == 2
    assert output["summary"]["value"]["mode"] == "copy"


def test_workflow_result_handler_builds_workflow_result_from_execution_metadata() -> None:
    """验证统一 workflow 结果节点会输出 workflow-result.v1。"""

    output = _workflow_result_handler(
        WorkflowNodeExecutionRequest(
            node_id="workflow-result",
            node_definition=object(),
            parameters={"status": "accepted", "code": 202},
            input_values={
                "result": {"ok_ng": "OK", "ok": True, "reason": "ok"},
                "metrics": {"value": {"elapsed_ms": 18.5}},
                "files": {"value": [{"path": "W:/archive/result.json"}]},
            },
            execution_metadata={
                "trace_id": "trace-001",
                "trigger_event_id": "event-001",
            },
        )
    )

    workflow_result = output["workflow_result"]
    assert workflow_result["status"] == "accepted"
    assert workflow_result["code"] == 202
    assert workflow_result["message"] == "accepted"
    assert workflow_result["trace_id"] == "trace-001"
    assert workflow_result["event_id"] == "event-001"
    assert workflow_result["data"]["ok_ng"] == "OK"
    assert output["summary"]["value"]["data_source"] == "input.result"


def test_batch_result_summary_handler_aggregates_record_and_direct_results() -> None:
    """验证批次结果摘要节点会汇总 record 内结果和直连结果。"""

    output = _batch_result_summary_handler(
        WorkflowNodeExecutionRequest(
            node_id="batch-result-summary",
            node_definition=object(),
            parameters={},
            input_values={
                "record": {
                    "value": {
                        "inspection_results": [
                            {"ok_ng": "OK", "ok": True, "reason": "ok"},
                            {"ok_ng": "NG", "ok": False, "reason": "coverage low"},
                        ]
                    }
                },
                "inspection_result": (
                    {
                        "ok_ng": "NG",
                        "ok": False,
                        "reason": "coverage low",
                        "alarm": {
                            "active": True,
                            "level": "warning",
                            "message": "coverage low",
                        },
                    },
                ),
            },
            execution_metadata={},
        )
    )

    summary_value = output["summary"]["value"]
    assert summary_value["count"] == 3
    assert summary_value["ok_count"] == 1
    assert summary_value["ng_count"] == 2
    assert summary_value["alarm_count"] == 1
    assert summary_value["summary_source"] == "computed"
    assert summary_value["batch_reason_summary"][0] == {
        "reason": "coverage low",
        "count": 2,
    }


def test_batch_result_summary_handler_uses_precomputed_summary_when_record_has_no_items() -> None:
    """验证批次结果摘要节点可复用 batch-record 中已有的预计算摘要。"""

    output = _batch_result_summary_handler(
        WorkflowNodeExecutionRequest(
            node_id="batch-result-summary",
            node_definition=object(),
            parameters={},
            input_values={
                "record": {
                    "value": {
                        "inspection_result_summary": {
                            "count": 4,
                            "ok_count": 3,
                            "ng_count": 1,
                            "alarm_count": 1,
                            "pass_ratio": 0.75,
                        }
                    }
                }
            },
            execution_metadata={},
        )
    )

    summary_value = output["summary"]["value"]
    assert summary_value["count"] == 4
    assert summary_value["used_precomputed_summary"] is True
    assert summary_value["summary_source"] == "record.inspection_result_summary"


def test_json_load_local_handler_reads_valid_json_file(tmp_path: Path) -> None:
    """验证本地 JSON 读取节点会输出 value.v1 和摘要。"""

    input_path = tmp_path / "cursor.json"
    input_path.write_text(
        json.dumps({"next_start_index": 4, "last_path": "W:/tmp/c.png"}),
        encoding="utf-8",
    )

    output = _json_load_local_handler(
        WorkflowNodeExecutionRequest(
            node_id="json-load-local",
            node_definition=object(),
            parameters={"local_path": str(input_path)},
            input_values={},
            execution_metadata={},
        )
    )

    assert output["value"]["value"]["next_start_index"] == 4
    assert output["summary"]["value"]["loaded_from_default"] is False
    assert output["summary"]["value"]["value_type"] == "object"


def test_json_load_local_handler_falls_back_when_file_is_missing(
    tmp_path: Path,
) -> None:
    """验证本地 JSON 读取节点可在文件缺失时回退默认值。"""

    missing_path = tmp_path / "missing.json"

    output = _json_load_local_handler(
        WorkflowNodeExecutionRequest(
            node_id="json-load-local",
            node_definition=object(),
            parameters={
                "local_path": str(missing_path),
                "allow_missing": True,
                "default_value": {"next_start_index": 0},
            },
            input_values={},
            execution_metadata={},
        )
    )

    assert output["value"]["value"] == {"next_start_index": 0}
    assert output["summary"]["value"]["loaded_from_default"] is True
    assert output["summary"]["value"]["default_reason"] == "missing-file"


def test_json_load_local_handler_falls_back_when_json_is_invalid(
    tmp_path: Path,
) -> None:
    """验证本地 JSON 读取节点可在坏 JSON 时回退默认值。"""

    input_path = tmp_path / "broken.json"
    input_path.write_text("{not-json", encoding="utf-8")

    output = _json_load_local_handler(
        WorkflowNodeExecutionRequest(
            node_id="json-load-local",
            node_definition=object(),
            parameters={
                "local_path": str(input_path),
                "allow_invalid_json": True,
                "default_value": {"next_start_index": 0},
            },
            input_values={},
            execution_metadata={},
        )
    )

    assert output["value"]["value"] == {"next_start_index": 0}
    assert output["summary"]["value"]["loaded_from_default"] is True
    assert output["summary"]["value"]["default_reason"] == "invalid-json"


def test_image_list_local_handler_loads_multiple_images(tmp_path: Path) -> None:
    """验证本地图像列表节点会输出 image-refs.v1。"""

    first_image = tmp_path / "first.png"
    second_image = tmp_path / "second.png"
    first_image.write_bytes(_build_png_bytes(width=10, height=8))
    second_image.write_bytes(_build_png_bytes(width=6, height=4))
    execution_metadata: dict[str, object] = {}

    output = _image_list_local_handler(
        WorkflowNodeExecutionRequest(
            node_id="image-list-local",
            node_definition=object(),
            parameters={},
            input_values={
                "files": {
                    "value": [
                        {"path": str(first_image)},
                        {"path": str(second_image)},
                    ]
                }
            },
            execution_metadata=execution_metadata,
        )
    )

    assert output["images"]["count"] == 2
    assert output["images"]["items"][0]["transport_kind"] == "memory"
    assert output["summary"]["value"]["count"] == 2


def _build_png_bytes(*, width: int, height: int) -> bytes:
    """构造测试用 PNG 图片字节。"""

    image = Image.new("RGB", (width, height), color=(32, 96, 160))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
