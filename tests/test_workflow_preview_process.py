"""Preview 使用真实 spawn 子进程，复用执行资源并保持同步 API 输出。"""

import json
from dataclasses import replace
from time import monotonic, sleep
import pytest
from backend.contracts.workflows.workflow_graph import WorkflowGraphNode, WorkflowGraphEdge

from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from tests.test_workflow_runtime_invoke_api import _build_file_metadata_application, _create_runtime_api_client
from tests.api_test_support import build_test_headers


def test_preview_reuses_process_and_cleans_uploaded_files(tmp_path, monkeypatch):
    """真实文件输入连续执行两次，确认输出、进程复用和退出闭环。"""
    client, sessions, storage = _create_runtime_api_client(
        tmp_path, database_name="preview-process.db", enable_local_buffer_broker=False)
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    with client:
        state = client.app.state
        pool = state.workflow_preview_run_manager.execution_pool
        published = []
        monkeypatch.setattr(state.workflow_preview_run_manager, "_publish_preview_run_event", published.append)
        workflow = LocalWorkflowJsonService(dataset_storage=storage, node_catalog_registry=state.node_catalog_registry)
        template, application = _build_file_metadata_application(multiple=True)
        workflow.save_template(project_id="project-1", template=template)
        workflow.save_application(project_id="project-1", application=application)
        pids = []
        for index in range(3):
            if index == 2:
                # 明确终止测试拥有的空闲进程，下一次接入应重建，不能永久丢失容量。
                pool._slots[0].process.terminate()
                pool._slots[0].process.join(5)
            result = client.post("/api/v1/workflows/preview-runs/multipart", headers=headers,
                data={"request": json.dumps({"project_id": "project-1", "application_ref": {
                    "application_id": application.application_id}})},
                files=[("request_files", ("a.txt", b"a", "text/plain")),
                       ("request_files", ("b.txt", b"bb", "text/plain"))])
            assert result.status_code == 201, result.text
            assert result.json()["state"] == "succeeded", result.text
            assert result.json()["outputs"]["metadata"]["value"]["file_name"] == "b.txt"
            events = [event for event in published if event.preview_run_id == result.json()["preview_run_id"]]
            assert events[-1].event_type == "preview.succeeded"
            assert len({event.sequence for event in events}) == len(events)
            replay = client.get(f"/api/v1/workflows/preview-runs/{result.json()['preview_run_id']}/events", headers=headers).json()
            assert [event["sequence"] for event in replay] == [event.sequence for event in events]
            pids.append(pool._slots[0].process.pid)
        assert pids[0] == pids[1]
        assert pids[2] != pids[1]
        assert not tuple(storage.resolve("workflows/runtime-inputs").rglob("content.*"))
    assert all(slot.process is None for slot in pool._slots)
    sessions.engine.dispose()


@pytest.mark.parametrize("uncooperative", [False, True])
def test_async_long_preview_is_queryable_busy_and_cancellable(tmp_path, monkeypatch, uncooperative):
    """30 秒节点不占用 HTTP 请求；并发受控，取消后才回收真实上传文件。"""
    if uncooperative:
        monkeypatch.setattr("backend.service.application.workflows.preview_execution_pool.run_preview_process", _uncooperative_preview)
    client, sessions, storage = _create_runtime_api_client(
        tmp_path, database_name="preview-long.db", enable_local_buffer_broker=False)
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    with client:
        state = client.app.state
        workflow = LocalWorkflowJsonService(dataset_storage=storage, node_catalog_registry=state.node_catalog_registry)
        template, application = _build_file_metadata_application(multiple=True)
        output = template.template_outputs[0]
        template = template.model_copy(update={
            "nodes": (*template.nodes, WorkflowGraphNode(node_id="delay", node_type_id="core.logic.delay", parameters={"seconds": 30})),
            "edges": (*template.edges, WorkflowGraphEdge(edge_id="slow", source_node_id=output.source_node_id,
                source_port=output.source_port, target_node_id="delay", target_port="value")),
            "template_outputs": (output.model_copy(update={"source_node_id": "delay", "source_port": "value"}),)})
        workflow.save_template(project_id="project-1", template=template)
        workflow.save_application(project_id="project-1", application=application)
        def submit():
            """每次请求使用独立上传文件，失败请求也应清理。"""
            return client.post("/api/v1/workflows/preview-runs/multipart", headers=headers,
                data={"request": json.dumps({"project_id": "project-1", "wait_mode": "async",
                    "application_ref": {"application_id": application.application_id}})},
                files=[("request_files", ("a.txt", b"a", "text/plain"))])
        started = monotonic()
        result = submit()
        assert result.status_code == 201, result.text
        assert monotonic() - started < 5
        run_id = result.json()["preview_run_id"]
        assert result.json()["state"] == "running"
        assert submit().status_code == 409
        for _ in range(5):
            assert client.get("/api/v1/system/liveness").status_code == 200
            assert client.get(f"/api/v1/workflows/preview-runs/{run_id}", headers=headers).json()["state"] == "running"
            sleep(.1)
        assert tuple(storage.resolve("workflows/runtime-inputs").rglob("content.*"))
        assert client.post(f"/api/v1/workflows/preview-runs/{run_id}/cancel", headers=headers).status_code == 200
        deadline = monotonic() + 20
        while monotonic() < deadline:
            record = client.get(f"/api/v1/workflows/preview-runs/{run_id}", headers=headers).json()
            if record["state"] != "running":
                break
            sleep(.1)
        assert record["state"] == "cancelled", record
        assert not tuple(storage.resolve("workflows/runtime-inputs").rglob("content.*"))
    sessions.engine.dispose()


def _uncooperative_preview(**kwargs):
    """隔离子进程模拟持续占用 CPU 且不检查取消的节点，不接触真实 Runtime。"""
    kwargs["responses"].put(("ready", None))
    kwargs["requests"].get()
    deadline = monotonic() + 60
    while monotonic() < deadline:
        sum(range(10000))


def test_async_complete_response_preserves_large_values(tmp_path):
    """完整异步结果保留长字符串，默认摘要仍按原合同脱敏。"""
    client, sessions, storage = _create_runtime_api_client(
        tmp_path, database_name="preview-payload.db", enable_local_buffer_broker=False)
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    with client:
        workflow = LocalWorkflowJsonService(dataset_storage=storage, node_catalog_registry=client.app.state.node_catalog_registry)
        template, application = _build_file_metadata_application(multiple=True)
        value = "完整结果" * 4000
        template = template.model_copy(update={
            "nodes": (WorkflowGraphNode(node_id="text", node_type_id="core.logic.string-value", parameters={"value": value}),),
            "edges": (), "template_inputs": (), "template_outputs": (
                template.template_outputs[0].model_copy(update={"source_node_id": "text", "source_port": "value"}),)})
        application = application.model_copy(update={"bindings": tuple(item for item in application.bindings if item.direction == "output")})
        workflow.save_template(project_id="project-1", template=template)
        workflow.save_application(project_id="project-1", application=application)
        response = client.post("/api/v1/workflows/preview-runs", headers=headers, json={
            "project_id": "project-1", "wait_mode": "async", "application_ref": {"application_id": application.application_id}})
        assert response.status_code == 201, response.text
        url = f"/api/v1/workflows/preview-runs/{response.json()['preview_run_id']}"
        deadline = monotonic() + 20
        while monotonic() < deadline:
            record = client.get(url, headers=headers).json()
            if record["state"] != "running":
                break
            sleep(.1)
        assert record["state"] == "succeeded", record
        assert record["outputs"]["metadata"]["value"]["text_redacted"] is True
        complete = client.get(url, headers=headers, params={"include_response_payload": True})
        assert complete.status_code == 200, complete.text
        assert complete.json()["outputs"]["metadata"]["value"] == value
        assert client.get(url, params={"include_response_payload": True}).status_code == 401
        manager = client.app.state.workflow_preview_run_manager
        with manager._open_unit_of_work() as uow:
            saved = uow.workflow_runtime.get_preview_run(record["preview_run_id"])
            owner = {**saved.metadata["preview_owner"], "create_time": saved.metadata["preview_owner"]["create_time"] - 1}
            uow.workflow_runtime.save_preview_run(replace(saved, state="running", finished_at=None,
                metadata={**saved.metadata, "preview_owner": owner}))
            uow.commit()
        # 所有者身份已失效，但子进程仍活着时不得释放输入或宣布任务结束。
        assert client.get(url, headers=headers).json()["state"] == "running"
        process = manager.execution_pool._slots[0].process
        process.terminate()
        process.join(5)
        assert client.get(url, headers=headers).json()["state"] == "failed"
    sessions.engine.dispose()


def _completed_error_preview(**kwargs):
    """已完成错误响应之后保持进程常驻，覆盖不能等待活进程退出的分支。"""
    kwargs["responses"].put(("ready", None))
    while kwargs["requests"].get() is not None:
        kwargs["responses"].put(("error", "isolated test failure"))


def test_completed_worker_error_releases_capacity_without_waiting_for_process_exit(tmp_path, monkeypatch):
    """已确认结束的错误不能锁死槽位，后继请求仍能接入。"""
    monkeypatch.setattr("backend.service.application.workflows.preview_execution_pool.run_preview_process", _completed_error_preview)
    client, sessions, storage = _create_runtime_api_client(tmp_path, database_name="preview-error.db", enable_local_buffer_broker=False)
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    with client:
        workflow = LocalWorkflowJsonService(dataset_storage=storage, node_catalog_registry=client.app.state.node_catalog_registry)
        template, application = _build_file_metadata_application(multiple=True)
        workflow.save_template(project_id="project-1", template=template)
        workflow.save_application(project_id="project-1", application=application)
        for _ in range(2):
            response = client.post("/api/v1/workflows/preview-runs", headers=headers, json={
                "project_id": "project-1", "wait_mode": "async", "application_ref": {"application_id": application.application_id}})
            assert response.status_code == 201, response.text
            url = f"/api/v1/workflows/preview-runs/{response.json()['preview_run_id']}"
            deadline = monotonic() + 15
            while monotonic() < deadline:
                record = client.get(url, headers=headers).json()
                if record["state"] != "running":
                    break
                sleep(.1)
            assert record["state"] == "failed", record
        assert client.app.state.workflow_preview_run_manager.execution_pool._slots[0].process.is_alive()
    sessions.engine.dispose()
