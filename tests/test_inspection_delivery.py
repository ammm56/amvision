"""三态经过现有文件、SQL、HTTP 输出，数值与空值不被转换。"""

import csv
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend.nodes.core_nodes.support.inspection_record import (
    build_result_record_payload,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.database_nodes.providers.sql.backend.nodes import sql_upsert
from custom_nodes.http_nodes.categories.request.backend.nodes import http_request
from custom_nodes.http_nodes.categories.request.backend.runtime import (
    execution as http_runtime,
)
from tests.test_industrial_io_output_nodes import (
    _csv_append_local_handler,
    _json_save_local_handler,
)


def _request(parameters, record, node_type_id="output"):
    """按现有输出节点共同请求结构构造一次调用。"""
    return WorkflowNodeExecutionRequest(
        node_id="delivery",
        node_definition=SimpleNamespace(node_type_id=node_type_id),
        parameters=parameters,
        input_values={"result": record},
        execution_metadata={},
    )


@pytest.mark.parametrize(
    "state,value", [("ok", 1.000000001), ("ng", 1.25), ("invalid", None)]
)
def test_all_decisions_preserve_values_in_existing_outputs(
    tmp_path: Path, monkeypatch, state, value
):
    """真实本地存储与 SQL，HTTP 只替换传输端，不替换节点映射和序列化。"""
    record = build_result_record_payload(
        state=state,
        reason_value="missing_surface" if state == "invalid" else None,
        metrics_value={"height": value, "unit": "mm"},
    )
    _json_save_local_handler(
        _request({"save_directory": str(tmp_path), "file_name": "record.json"}, record)
    )
    assert json.loads((tmp_path / "record.json").read_text(encoding="utf-8")) == record
    _csv_append_local_handler(
        _request({"save_location": str(tmp_path / "record.csv")}, record)
    )
    with (tmp_path / "record.csv").open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["state"] == state and row["passed"] == str(state == "ok")
    assert row["metrics.height"] == ("" if value is None else str(value))
    database = tmp_path / "results.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE results (state TEXT PRIMARY KEY, passed BOOLEAN, height REAL)"
        )
    sql_upsert.handle_node(
        _request(
            {
                "database_url": f"sqlite:///{database.as_posix()}",
                "table_name": "results",
                "key_columns": ["state"],
                "column_mappings": [
                    {
                        "column_name": column,
                        "source_kind": "result",
                        "source_path": path,
                    }
                    for column, path in (
                        ("state", "state"),
                        ("passed", "passed"),
                        ("height", "metrics.height"),
                    )
                ],
            },
            record,
            sql_upsert.NODE_TYPE_ID,
        )
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT state, passed, height FROM results"
        ).fetchone() == (state, int(state == "ok"), value)
    captured = {}

    def receive(**kwargs):
        """捕获最终 HTTP JSON，保留真实节点的组装路径。"""
        captured.update(kwargs)
        return httpx.Response(
            202, json={"accepted": True}, request=httpx.Request("POST", kwargs["url"])
        )

    monkeypatch.setattr(http_runtime, "execute_bounded_http_request", receive)
    http_request.handle_node(
        _request(
            {"url": "https://mes.example.test/results"},
            record,
            http_request.NODE_TYPE_ID,
        )
    )
    assert captured["json"] == record
