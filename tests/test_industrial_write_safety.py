"""工业文件输出的原子性、并发和幂等测试。"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from threading import Thread

from backend.nodes.core_nodes.io.batch.batch_files_relocate import (
    _batch_files_relocate_handler,
)
from backend.nodes.core_nodes.io.output.storage.csv_append_local import (
    _csv_append_local_handler,
)
from backend.nodes.core_nodes.io.output.storage.json_save_local import (
    _json_save_local_handler,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)


def _request(
    *,
    node_id: str,
    invocation_id: str,
    parameters: dict[str, object],
    input_values: dict[str, object],
) -> WorkflowNodeExecutionRequest:
    """构造带稳定 invocation id 的文件节点请求。"""

    return WorkflowNodeExecutionRequest(
        node_id=node_id,
        node_definition=object(),
        parameters=parameters,
        input_values=input_values,
        execution_metadata={"workflow_run_id": "run-1"},
        node_invocation_id=invocation_id,
    )


def test_json_save_local_replaces_complete_document(tmp_path: Path) -> None:
    """JSON 覆盖后目标文件应始终是完整文档。"""

    output_path = tmp_path / "result.json"
    output_path.write_text('{"old":true}', encoding="utf-8")

    _json_save_local_handler(
        _request(
            node_id="json-save",
            invocation_id="json-save:1",
            parameters={"save_location": str(output_path)},
            input_values={"value": {"value": {"new": True}}},
        )
    )

    assert json.loads(output_path.read_text(encoding="utf-8")) == {"new": True}
    assert not tuple(tmp_path.glob(".result.json.*.tmp"))


def test_csv_append_same_invocation_is_idempotent(tmp_path: Path) -> None:
    """同一个 invocation 重放不能重复追加 CSV 行。"""

    output_path = tmp_path / "records.csv"
    request = _request(
        node_id="csv-append",
        invocation_id="csv-append:1",
        parameters={"save_location": str(output_path)},
        input_values={"value": {"value": {"serial": "A-001", "ok": True}}},
    )

    first = _csv_append_local_handler(request)
    second = _csv_append_local_handler(request)

    with output_path.open("r", encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert len(rows) == 1
    assert first["summary"]["value"]["idempotent_replay"] is False
    assert second["summary"]["value"]["idempotent_replay"] is True


def test_csv_append_concurrent_invocations_do_not_interleave(tmp_path: Path) -> None:
    """并发 Workflow 写同一 CSV 时 header 和 row 不得交错。"""

    output_path = tmp_path / "concurrent.csv"
    errors: list[Exception] = []

    def append(index: int) -> None:
        try:
            _csv_append_local_handler(
                _request(
                    node_id="csv-append",
                    invocation_id=f"csv-append:{index}",
                    parameters={"save_location": str(output_path)},
                    input_values={
                        "value": {"value": {"index": index, "state": "ok"}}
                    },
                )
            )
        except Exception as exc:  # pragma: no cover - 失败时由主线程断言输出
            errors.append(exc)

    threads = [Thread(target=append, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)

    assert errors == []
    with output_path.open("r", encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert len(rows) == 8
    assert {int(row["index"]) for row in rows} == set(range(8))


def test_move_replay_recovers_committed_target(tmp_path: Path) -> None:
    """move 成功后重放同一 invocation 应返回目标而不是报告源文件缺失。"""

    source_path = tmp_path / "incoming" / "part.png"
    source_path.parent.mkdir()
    source_path.write_bytes(b"part-image")
    target_directory = tmp_path / "archive"
    request = _request(
        node_id="relocate",
        invocation_id="relocate:1",
        parameters={
            "save_location": str(target_directory),
            "mode": "move",
            "conflict_policy": "overwrite",
        },
        input_values={"files": {"value": [{"path": str(source_path)}]}},
    )

    first = _batch_files_relocate_handler(request)
    second = _batch_files_relocate_handler(request)

    target_path = target_directory / source_path.name
    assert not source_path.exists()
    assert target_path.read_bytes() == b"part-image"
    assert first["mappings"]["value"][0]["idempotent_replay"] is False
    assert second["mappings"]["value"][0]["idempotent_replay"] is True
