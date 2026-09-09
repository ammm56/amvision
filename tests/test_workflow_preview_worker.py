"""真实 spawn Worker 的内存快照、实时节点事件与取消测试。"""

from time import monotonic, sleep
from uuid import uuid4

from backend.contracts.workflows.workflow_graph import WorkflowGraphNode, WorkflowGraphEdge, WorkflowGraphInput, FlowApplicationBinding
from backend.service.application.workflows.preview.pool import PreviewSessionPool
from backend.service.application.workflows.preview.session import PreviewSessionManager
from tests.test_workflow_runtime_invoke_api import _build_file_metadata_application, _create_runtime_api_client


from tests.preview_worker_faults import _uncooperative_worker


def test_quarantined_writer_is_reaped_only_after_confirmed_process_exit():
    """模拟首次终止失败；活进程借用不能被提前释放，稍后死亡必须回收。"""
    from types import SimpleNamespace
    from backend.service.settings import BackendServiceSettings
    manager = PreviewSessionManager()
    pool = PreviewSessionPool(settings=BackendServiceSettings(), manager=manager)
    alive = [True]
    try:
        sid = manager.create(principal_id="test", project_id="p", application_id="a", editor_session_id="e")["session_id"]
        block = manager.buffers.allocate(sid, 8, media_type="image/png")
        manager.buffers.writer_descriptor(sid, block)
        slot = pool._slots[0]
        slot.process = SimpleNamespace(is_alive=lambda: alive[0], close=lambda: None)
        slot.quarantined = slot.busy = True
        slot.deferred_cleanup = lambda: manager.buffers.unpin(sid, block)
        manager.release(sid, "test")
        pool.reap()
        assert manager.buffers.stats()["pins"] == 1 and slot.busy
        alive[0] = False
        pool.reap()
        assert manager.buffers.stats() == {"blocks": 0, "bytes": 0, "pins": 0, "reserved_bytes": 0}
        assert slot.process is None and not slot.quarantined and not slot.busy
    finally:
        alive[0] = False
        pool.close()
        manager.close()


def test_forced_timeout_reclaims_unpublished_writer_after_process_exit(tmp_path, monkeypatch):
    """仅注入独立测试子进程；确认退出、pin 和预留全部归零。"""
    from backend.service.settings import BackendServiceSettings
    import backend.service.application.workflows.preview.pool as module
    monkeypatch.setattr(module, "run_preview_worker", _uncooperative_worker)
    manager = PreviewSessionManager()
    pool = PreviewSessionPool(settings=BackendServiceSettings(), manager=manager)
    manager.pool = pool
    try:
        sid = manager.create(principal_id="test", project_id="p", application_id="a", editor_session_id="e")["session_id"]
        manager.subscribe(sid, "test")
        manager.submit(sid, "test", {"request_id": str(uuid4()), "document_revision": "r", "timeout_seconds": 10}, pool.submit)
        deadline = monotonic() + 20
        while manager.authorize(sid, "test").run["state"] == "accepted" and monotonic() < deadline:
            sleep(.02)
        assert manager.authorize(sid, "test").run["state"] == "timed_out"
        manager.close()
        assert manager.buffers.stats() == {"blocks": 0, "bytes": 0, "pins": 0, "reserved_bytes": 0}
        assert all(slot.process is None for slot in pool._slots)
    finally:
        manager.close()


def test_memory_worker_streams_before_long_node_finishes(tmp_path):
    """只通过内存传递未保存图，前面的节点事件不能等长节点结束才到达。"""
    client, sessions, storage = _create_runtime_api_client(tmp_path, database_name="memory-preview.db", enable_local_buffer_broker=False)
    with client:
        import cv2
        import numpy as np
        import hashlib
        from backend.contracts.workflows.preview_session import PREVIEW_CHUNK_SIZE
        source = np.arange(1024 * 2048 * 3, dtype=np.uint8).reshape(1024, 2048, 3)
        encoded = cv2.imencode(".png", source)[1].tobytes()
        template, application = _build_file_metadata_application(multiple=True)
        template = template.model_copy(update={"nodes": (
            WorkflowGraphNode(node_id="text", node_type_id="core.logic.string-value", parameters={"value": "实时值"}),
            WorkflowGraphNode(node_id="display", node_type_id="core.io.value-preview"),
            WorkflowGraphNode(node_id="delay", node_type_id="core.logic.delay", parameters={"seconds": 30}),
            WorkflowGraphNode(node_id="image", node_type_id="core.io.image-preview", parameters={"response_transport_mode": "storage-ref"}),
        ), "edges": (
            WorkflowGraphEdge(edge_id="show", source_node_id="text", source_port="value", target_node_id="display", target_port="value"),
            WorkflowGraphEdge(edge_id="wait", source_node_id="text", source_port="value", target_node_id="delay", target_port="value"),
        ), "template_inputs": (WorkflowGraphInput(input_id="input", display_name="image", payload_type_id="image-ref.v1",
                                                  target_node_id="image", target_port="image"),), "template_outputs": (
            template.template_outputs[0].model_copy(update={"source_node_id": "delay", "source_port": "value"}),)})
        application = application.model_copy(update={"bindings": tuple(b for b in application.bindings if b.direction == "output") + (
            FlowApplicationBinding(binding_id="image", direction="input", template_port_id="input", binding_kind="api-request"),)})
        manager = PreviewSessionManager()
        pool = PreviewSessionPool(settings=client.app.state.backend_service_settings, manager=manager)
        manager.pool = pool
        try:
            sid = manager.create(principal_id="test", project_id="project-1", application_id=application.application_id,
                                 editor_session_id="editor")["session_id"]
            sub, _ = manager.subscribe(sid, "test")
            blob = manager.buffers.allocate(sid, len(encoded), media_type="image/png", digest=hashlib.sha256(encoded).hexdigest())
            for index, offset in enumerate(range(0, len(encoded), PREVIEW_CHUNK_SIZE)):
                manager.buffers.write_chunk(sid, blob, index, encoded[offset:offset + PREVIEW_CHUNK_SIZE])
            manager.buffers.commit(sid, blob)
            request = {"request_id": str(uuid4()), "document_revision": "draft", "application": application.model_dump(mode="json"),
                       "template": template.model_dump(mode="json"), "timeout_seconds": 60, "input_ids": {"image": blob}}
            reply = manager.submit(sid, "test", request, pool.submit)
            events = []
            deadline = monotonic() + 25
            while monotonic() < deadline:
                event = manager.take(sub)
                if event:
                    events.append(event)
                    if len([e for e in events if e["type"] == "display.updated"]) == 2:
                        break
                    if event["type"] == "run.finished":
                        raise AssertionError(event)
                else:
                    sleep(.02)
            assert any(e["type"] == "node.finished" and e["payload"]["node_id"] == "display" for e in events), events
            display = next(e["payload"]["payload"]["image"] for e in events if e["type"] == "display.updated" and e["payload"]["node_id"] == "image")
            assert display["source_width"] == 2048 and display["display_width"] == 1920
            with manager.buffers.borrow(sid, display["source_image"]["blob_id"]) as content:
                decoded = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
            assert np.array_equal(decoded, source)
            assert next(e["payload"]["payload"]["value"] for e in events if e["type"] == "display.updated" and e["payload"]["node_id"] == "display") == "实时值"
            assert manager.authorize(sid, "test").run["state"] == "running"
            pool.cancel(reply["run_id"])
            while monotonic() < deadline and manager.authorize(sid, "test").run["state"] == "running":
                sleep(.05)
            assert manager.authorize(sid, "test").run["state"] == "cancelled"
            idle_deadline = monotonic() + 5
            while pool._active and monotonic() < idle_deadline:
                sleep(.02)
            worker_pid = pool._slots[0].process.pid
            manager.release(sid, "test")
            for multiple in (False, True):
                file_template, file_app = _build_file_metadata_application(multiple=multiple)
                sid = manager.create(principal_id="test", project_id="project-1", application_id=file_app.application_id,
                                     editor_session_id="files")["session_id"]
                sub, _ = manager.subscribe(sid, "test")
                ids = []
                media_type = "text/plain" if multiple else "application/json"
                contents = [b'first', b'second'] if multiple else [b'{"value":false}']
                for index, content in enumerate(contents):
                    blob = manager.buffers.allocate(sid, len(content), media_type=media_type, file_name=f"file-{index}.txt")
                    manager.buffers.write_chunk(sid, blob, 0, content)
                    manager.buffers.commit(sid, blob)
                    ids.append(blob)
                binding = "request_files" if multiple else "request_file"
                manager.submit(sid, "test", {"request_id": str(uuid4()), "document_revision": "files",
                    "application": file_app.model_dump(mode="json"), "template": file_template.model_dump(mode="json"),
                    "input_ids": {binding: ids}}, pool.submit)
                deadline = monotonic() + 10
                while manager.authorize(sid, "test").run["state"] in {"accepted", "running"} and monotonic() < deadline:
                    sleep(.02)
                run = manager.authorize(sid, "test").run
                assert run["state"] == "succeeded", run
                metadata = run["outputs"]["metadata"]["value"]
                assert metadata["file_name"] == f"file-{1 if multiple else 0}.txt"
                assert metadata["content_length"] == len(contents[-1])
                assert not storage.resolve(metadata["object_key"]).exists()
                while pool._active and monotonic() < deadline:
                    sleep(.02)
                assert pool._slots[0].process.pid == worker_pid
                manager.release(sid, "test")
            assert manager.buffers.stats() == {"blocks": 0, "bytes": 0, "pins": 0, "reserved_bytes": 0}
            assert not list(storage.root_dir.rglob("preview-runs"))
        finally:
            manager.close()
    sessions.engine.dispose()
