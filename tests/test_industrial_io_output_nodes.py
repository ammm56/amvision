"""工业输入输出节点轻量回归测试。"""

from __future__ import annotations

import io
from pathlib import Path

import httpx
from PIL import Image

from backend.nodes.core_nodes.csv_append_local import _csv_append_local_handler
from backend.nodes.core_nodes.directory_batch_window import _directory_batch_window_handler
from backend.nodes.core_nodes.directory_scan import _directory_scan_handler
from backend.nodes.core_nodes.http_post import _http_post_handler
from backend.nodes.core_nodes.image_load_local import _image_load_local_handler
from backend.nodes.core_nodes.image_list_local import _image_list_local_handler
from backend.nodes.core_nodes.json_save_local import _json_save_local_handler
from backend.nodes.runtime_support import require_execution_image_registry
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


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
    assert image_registry.read_bytes(output["image"]["image_handle"]).startswith(b"\x89PNG")


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

    monkeypatch.setattr("backend.nodes.core_nodes.http_post.httpx.request", _fake_request)

    output = _http_post_handler(
        WorkflowNodeExecutionRequest(
            node_id="http-post",
            node_definition=object(),
            parameters={"url": "http://example.test/callback", "method": "POST"},
            input_values={"value": {"value": {"ok_ng": "OK", "station_id": "line-a-01"}}},
            execution_metadata={},
        )
    )

    assert captured_request["method"] == "POST"
    assert captured_request["url"] == "http://example.test/callback"
    assert captured_request["json"] == {"ok_ng": "OK", "station_id": "line-a-01"}
    assert output["response"]["value"]["ok"] is True
    assert output["response"]["value"]["status_code"] == 201
    assert output["response"]["value"]["body_json"]["accepted"] is True


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
