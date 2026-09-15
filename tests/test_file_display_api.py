"""隔离数据库/文件的实际 Worker、REST 和 WebSocket 联调。"""

import json
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from backend.contracts.workflows.preview_session import decode_preview_frame

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from tests.api_test_support import build_test_headers
from tests.test_workflow_runtime_invoke_api import (
    _create_runtime_api_client,
    _create_and_start_runtime,
)
from tests.workflow_file_display_support import build_file_display_graph


def _saved_result_graph(root, source: Path, image: Path | None):
    """从任意 JSON 路径提取现有字段；只读现场结果，写入隔离测试目录。"""
    app, graph = build_file_display_graph(root, image_path=image)
    document = graph.model_dump(mode="json")
    document["nodes"] = [n for n in document["nodes"] if n["node_id"] != "counts"]
    document["nodes"].append(
        dict(
            node_id="source",
            node_type_id="core.io.json-load-local",
            parameters={"local_path": str(source)},
        )
    )
    for n in document["nodes"]:
        if n["node_id"] in {"count_ok", "count_ng"}:
            n["parameters"]["path"] = (
                "data.empty_count"
                if n["node_id"] == "count_ok"
                else "data.abnormal_count"
            )
        if n["node_id"] == "values":
            n["parameters"]["fields"].insert(
                0,
                {
                    "path": "summary.latest.state",
                    "label": "本次结果",
                    "format": "status",
                    "states": {"ok": "success", "ng": "danger"},
                },
            )
    for edge in document["edges"]:
        if edge["source_node_id"] == "counts":
            edge.update(source_node_id="source", source_port="value")
    document["nodes"].extend(
        [
            dict(
                node_id="state",
                node_type_id="core.logic.value-field-extract",
                parameters={"path": "data.state"},
            ),
            dict(
                node_id="state_field",
                node_type_id="core.logic.object-field",
                parameters={"key": "state"},
            ),
        ]
    )
    document["edges"].extend(
        [
            dict(
                edge_id="state_in",
                source_node_id="source",
                source_port="value",
                target_node_id="state",
                target_port="value",
            ),
            dict(
                edge_id="state_field_in",
                source_node_id="state",
                source_port="value",
                target_node_id="state_field",
                target_port="value",
            ),
            dict(
                edge_id="state_record",
                source_node_id="state_field",
                source_port="field",
                target_node_id="record",
                target_port="entries",
            ),
        ]
    )
    document["template_inputs"] = []
    app_data = app.model_dump(mode="json")
    app_data["bindings"] = [
        b for b in app_data["bindings"] if b["direction"] == "output"
    ]
    return FlowApplication.model_validate(
        app_data
    ), WorkflowGraphTemplate.model_validate(document)


def test_runtime_and_preview_file_display_with_saved_result(tmp_path):
    """实际进程执行同一通用图：独立调用追加，Preview 值流正确且可释放。"""
    source = (
        Path(os.environ["AMVISION_FILE_DISPLAY_TEST_JSON"])
        if os.environ.get("AMVISION_FILE_DISPLAY_TEST_JSON")
        else tmp_path / "input.json"
    )
    image = (
        Path(os.environ["AMVISION_FILE_DISPLAY_TEST_IMAGE"])
        if os.environ.get("AMVISION_FILE_DISPLAY_TEST_IMAGE")
        else None
    )
    if os.environ.get("AMVISION_FILE_DISPLAY_TEST_JSON"):
        assert source.is_file(), "指定的真实 JSON 不存在"
    else:
        source.write_text(
            json.dumps(
                {"data": {"state": "ok", "empty_count": 24, "abnormal_count": 0}}
            ),
            encoding="utf-8",
        )
    expected = json.loads(source.read_text(encoding="utf-8"))["data"]
    client, sessions, storage = _create_runtime_api_client(
        tmp_path, database_name="file-display-api.db", enable_local_buffer_broker=False
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    sid = runtime_id = None
    timings = []
    try:
        with client:
            app, graph = _saved_result_graph(
                tmp_path / "runtime-records", source, image
            )
            service = LocalWorkflowJsonService(
                dataset_storage=storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            service.save_template(project_id="project-1", template=graph)
            service.save_application(project_id="project-1", application=app)
            runtime_id = _create_and_start_runtime(
                client=client,
                headers=headers,
                application_id=app.application_id,
                display_name="File display isolated validation",
            )
            for cycle in (1, 2):
                tick = perf_counter()
                response = client.post(
                    f"/api/v1/workflows/app-runtimes/{runtime_id}/invoke",
                    headers=headers,
                    params={"response_mode": "run"},
                    json={"input_bindings": {}},
                )
                timings.append(round((perf_counter() - tick) * 1000, 2))
                assert response.status_code == 200, response.text
                run = response.json()
                assert run["state"] == "succeeded", run
                value = run["outputs"]["result"]["value"]
                assert value["totals"]["material_total"] == 24 * cycle
                assert value["totals"]["material_ok"] == expected["empty_count"] * cycle
                assert (
                    value["totals"]["material_ng"] == expected["abnormal_count"] * cycle
                )
            app, graph = _saved_result_graph(
                tmp_path / "preview-records", source, image
            )
            base = "/api/v1/workflows/preview-sessions"
            created = client.post(
                base,
                headers=headers,
                json={
                    "project_id": "project-1",
                    "application_id": app.application_id,
                    "editor_session_id": str(uuid4()),
                },
            )
            assert created.status_code == 201, created.text
            sid = created.json()["session_id"]
            with client.websocket_connect(
                f"/ws/v1/workflows/preview-sessions/{sid}", headers=headers
            ) as ws:
                assert ws.receive_json()["type"] == "session.snapshot"
                tick = perf_counter()
                accepted = client.post(
                    f"{base}/{sid}/runs",
                    headers=headers,
                    json={
                        "request_id": str(uuid4()),
                        "document_revision": "isolated-file-display",
                        "application": app.model_dump(mode="json"),
                        "template": graph.model_dump(mode="json"),
                        "input_bindings": {},
                        "timeout_seconds": 60,
                    },
                )
                assert accepted.status_code == 202, accepted.text
                displays = {}
                while True:
                    event = ws.receive_json()
                    if event["type"] == "display.updated":
                        displays[event["payload"]["node_id"]] = event["payload"][
                            "payload"
                        ]
                    if event["type"] == "run.finished":
                        assert event["payload"]["status"] == "succeeded", event
                    if event["type"] == "run.outputs":
                        assert event["payload"].get("delivery_state") == "ready", event
                        break
                preview_ms = round((perf_counter() - tick) * 1000, 2)
                assert displays["values"]["type"] == "value-display"
                assert displays["values"]["fields"][0]["value"] == expected["state"]
                if image:
                    assert (
                        displays["preview"]["presentation_context"]
                        == displays["values"]["context"]
                    )
                    blob = displays["preview"]["image"]["blob_id"]
                    ws.send_json({"type": "display.get", "blob_id": blob})
                    begin = ws.receive_json()
                    assert begin["type"] == "display.begin", begin
                    received = bytearray()
                    while len(received) < begin["byte_length"]:
                        _, index, chunk = decode_preview_frame(
                            ws.receive_bytes(), expected_kind=2
                        )
                        received.extend(chunk)
                        chunk.release()
                        ws.send_json(
                            {
                                "type": "display.ack",
                                "blob_id": blob,
                                "chunk_index": index,
                            }
                        )
                    end = ws.receive_json()
                    assert end["type"] == "display.end", end
                    assert received[:2] == b"\xff\xd8"
                    ws.send_json(
                        {
                            "type": "resource.received",
                            "blob_id": blob,
                            "receipt": end["receipt"],
                        }
                    )
            assert client.delete(f"{base}/{sid}", headers=headers).status_code == 204
            sid = None
            assert client.app.state.workflow_preview_sessions.buffers.stats() == {
                "blocks": 0,
                "bytes": 0,
                "pins": 0,
                "reserved_bytes": 0,
            }
            assert (
                client.post(
                    f"/api/v1/workflows/app-runtimes/{runtime_id}/stop", headers=headers
                ).status_code
                == 200
            )
            runtime_id = None
            report = {
                "runtime_request_ms": timings,
                "preview_display_ready_ms": preview_ms,
                "real_saved_result": bool(
                    os.environ.get("AMVISION_FILE_DISPLAY_TEST_JSON")
                ),
                "image_enabled": image is not None,
                "value_display": displays["values"],
            }
            if os.environ.get("AMVISION_FILE_DISPLAY_TEST_REPORT"):
                Path(os.environ["AMVISION_FILE_DISPLAY_TEST_REPORT"]).write_text(
                    json.dumps(report, ensure_ascii=False), encoding="utf-8"
                )
            print(json.dumps(report, ensure_ascii=False))
    finally:
        client.app.state.workflow_preview_sessions.close()
        sessions.engine.dispose()
