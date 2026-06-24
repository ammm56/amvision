"""本地数据库输出节点行为测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.output_local_db_nodes.backend.nodes import local_db_upsert


def test_local_db_upsert_inserts_and_updates_sqlite_row(tmp_path: Path) -> None:
    """验证 local-db-upsert 会对 SQLite 表执行单行 upsert。"""

    database_path = tmp_path / "inspection.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    _create_results_table(database_url=database_url)

    first_output = local_db_upsert.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="local-db-upsert-insert",
            node_definition=SimpleNamespace(node_type_id=local_db_upsert.NODE_TYPE_ID),
            parameters={
                "database_url": database_url,
                "table_name": "inspection_results",
                "key_columns": ["record_id"],
                "static_fields": {"station_id": "station-a"},
                "column_mappings": [
                    {
                        "column_name": "record_id",
                        "source_kind": "request",
                        "source_path": "record_id",
                    },
                    {
                        "column_name": "ok_ng",
                        "source_kind": "result",
                        "source_path": "ok_ng",
                    },
                    {
                        "column_name": "coverage_ratio",
                        "source_kind": "result",
                        "source_path": "metrics.coverage_ratio",
                    },
                    {
                        "column_name": "event_id",
                        "source_kind": "literal",
                        "literal_value": "evt-001",
                    },
                ],
            },
            input_values={
                "result": {
                    "ok_ng": "NG",
                    "ok": False,
                    "metrics": {"coverage_ratio": 0.42},
                },
                "request": {"value": {"record_id": "record-001"}},
            },
            execution_metadata={},
        )
    )

    second_output = local_db_upsert.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="local-db-upsert-update",
            node_definition=SimpleNamespace(node_type_id=local_db_upsert.NODE_TYPE_ID),
            parameters={
                "database_url": database_url,
                "table_name": "inspection_results",
                "key_columns": ["record_id"],
                "update_columns": ["ok_ng", "coverage_ratio", "station_id"],
                "static_fields": {"station_id": "station-b"},
                "column_mappings": [
                    {
                        "column_name": "record_id",
                        "source_kind": "request",
                        "source_path": "record_id",
                    },
                    {
                        "column_name": "ok_ng",
                        "source_kind": "result",
                        "source_path": "ok_ng",
                    },
                    {
                        "column_name": "coverage_ratio",
                        "source_kind": "result",
                        "source_path": "metrics.coverage_ratio",
                    },
                ],
            },
            input_values={
                "result": {
                    "ok_ng": "OK",
                    "ok": True,
                    "metrics": {"coverage_ratio": 0.91},
                },
                "request": {"value": {"record_id": "record-001"}},
            },
            execution_metadata={},
        )
    )

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT record_id, ok_ng, coverage_ratio, station_id, event_id FROM inspection_results WHERE record_id = ?",
            ("record-001",),
        ).fetchone()

    assert row == ("record-001", "OK", 0.91, "station-b", "evt-001")
    assert first_output["result"]["value"]["database_kind"] == "sqlite"
    assert first_output["prepared_row"]["value"]["record_id"] == "record-001"
    assert first_output["prepared_row"]["value"]["station_id"] == "station-a"
    assert second_output["result"]["value"]["skipped"] is False
    assert second_output["result"]["value"]["written_row"]["ok_ng"] == "OK"
    assert second_output["result"]["value"]["update_columns"] == [
        "ok_ng",
        "coverage_ratio",
        "station_id",
    ]


def test_local_db_upsert_rejects_multiple_primary_inputs(tmp_path: Path) -> None:
    """验证 local-db-upsert 会拒绝同时提供多个主业务输入。"""

    database_url = f"sqlite:///{(tmp_path / 'inspection.db').as_posix()}"

    with pytest.raises(InvalidRequestError, match="只能同时提供一个"):
        local_db_upsert.handle_node(
            WorkflowNodeExecutionRequest(
                node_id="local-db-upsert-invalid",
                node_definition=SimpleNamespace(
                    node_type_id=local_db_upsert.NODE_TYPE_ID
                ),
                parameters={
                    "database_url": database_url,
                    "table_name": "inspection_results",
                    "key_columns": ["record_id"],
                    "column_mappings": [
                        {
                            "column_name": "record_id",
                            "source_kind": "literal",
                            "literal_value": "record-001",
                        }
                    ],
                },
                input_values={
                    "result": {"ok_ng": "OK", "ok": True},
                    "workflow_result": {
                        "status": "succeeded",
                        "code": 0,
                        "message": "ok",
                    },
                },
                execution_metadata={},
            )
        )


def test_local_db_upsert_requires_key_columns_to_match_unique_constraint(
    tmp_path: Path,
) -> None:
    """验证 local-db-upsert 会拒绝非主键/非唯一键的冲突列。"""

    database_path = tmp_path / "inspection.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE inspection_results (
                        record_id TEXT PRIMARY KEY,
                        event_id TEXT,
                        ok_ng TEXT
                    )
                    """
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(InvalidRequestError, match="主键或唯一约束"):
        local_db_upsert.handle_node(
            WorkflowNodeExecutionRequest(
                node_id="local-db-upsert-invalid-key",
                node_definition=SimpleNamespace(
                    node_type_id=local_db_upsert.NODE_TYPE_ID
                ),
                parameters={
                    "database_url": database_url,
                    "table_name": "inspection_results",
                    "key_columns": ["event_id"],
                    "column_mappings": [
                        {
                            "column_name": "event_id",
                            "source_kind": "literal",
                            "literal_value": "evt-002",
                        },
                        {
                            "column_name": "ok_ng",
                            "source_kind": "literal",
                            "literal_value": "NG",
                        },
                    ],
                    "skip_if_no_update_columns": True,
                },
                input_values={
                    "summary": {"value": {"ok_count": 0, "ng_count": 1}},
                },
                execution_metadata={},
            )
        )


def _create_results_table(*, database_url: str) -> None:
    """创建 SQLite 测试结果表。"""

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE inspection_results (
                        record_id TEXT PRIMARY KEY,
                        ok_ng TEXT NOT NULL,
                        coverage_ratio REAL,
                        station_id TEXT,
                        event_id TEXT
                    )
                    """
                )
            )
    finally:
        engine.dispose()
