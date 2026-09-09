"""Preview 会话事件顺序、资源隔离、断线和慢消费者测试。"""

from uuid import uuid4

import pytest

from backend.service.application.workflows.preview.session import PreviewSessionError, PreviewSessionManager


def test_deployment_rejects_multiple_api_processes():
    """会话归属不能因标准启动参数分裂；Preview 执行并发不受此约束。"""
    from backend.service.application.workflows.preview.deployment import validate_preview_api_processes
    validate_preview_api_processes(["uvicorn", "--workers", "1"], {})
    for argv, env in [(["uvicorn", "--workers=2"], {}), (["uvicorn", "--workers", "2"], {}), ([], {"WEB_CONCURRENCY": "2"})]:
        with pytest.raises(RuntimeError, match="one API process"):
            validate_preview_api_processes(argv, env)


@pytest.fixture
def manager():
    """所有测试会话在结束后回收。"""
    value = PreviewSessionManager(queue_items=4)
    yield value
    value.close()


def _begin(manager):
    """受理前先订阅，方便用同步事件验证无需 REST 拉取。"""
    session = manager.create(principal_id="alice", project_id="p", application_id="a", editor_session_id="editor")
    sid = session["session_id"]
    sub, snapshot = manager.subscribe(sid, "alice")
    assert snapshot["payload"]["watermark"] == 0
    request = {"request_id": str(uuid4()), "document_revision": "r1"}
    reply = manager.submit(sid, "alice", request, lambda session, request: None)
    return sid, sub, request, reply["run_id"]


def test_node_results_arrive_before_workflow_finishes(manager):
    """业务未结束时节点状态和值已经是可直接消费的事件。"""
    sid, sub, _, rid = _begin(manager)
    manager.accept(sid, rid, "run.started", {})
    manager.accept(sid, rid, "node.started", {"node_id": "value", "invocation_id": "value", "status": "running"})
    manager.accept(sid, rid, "node.finished", {"node_id": "value", "invocation_id": "value", "status": "succeeded", "outputs": {"value": False}})
    events = [manager.take(sub) for _ in range(4)]
    assert events[-1]["payload"]["outputs"]["value"] is False
    assert manager.authorize(sid, "alice").run["state"] == "running"
    assert [e["seq"] for e in events] == [1, 2, 3, 4]


def test_rerun_retains_stale_images_until_replaced(manager):
    """同一 Blob 同时用于显示和终态输出时，重跑不能提前释放它。"""
    from multiprocessing.shared_memory import SharedMemory
    sid, _, request, rid = _begin(manager)
    blob = manager.buffers.allocate(sid, 4, media_type="image/png")
    writer = manager.buffers.writer_descriptor(sid, blob)
    memory = SharedMemory(name=writer["name"])
    memory.buf[:4] = b"test"
    memory.close()
    descriptor = {"transport_kind": "preview-memory", **manager.buffers.publish_writer(sid, blob)}
    payload = {"node_id": "image", "output_port": "body", "payload": {"type": "image-preview", "image": descriptor}}
    manager.accept(sid, rid, "display.updated", payload)
    manager.accept(sid, rid, "run.finished", {"status": "succeeded", "outputs": descriptor})
    next_run = manager.submit(sid, "alice", {**request, "request_id": str(uuid4()), "template": {"nodes": [{"node_id": "image"}]}}, lambda *args: None)
    assert manager.authorize(sid, "alice").displays["image:body"]["stale"]
    with manager.buffers.borrow(sid, blob) as content:
        assert bytes(content) == b"test"
    manager.accept(sid, next_run["run_id"], "display.unavailable", {"node_id": "image", "output_port": "body", "error": "encoding"})
    assert blob in manager.referenced_blobs(sid)
    manager.accept(sid, next_run["run_id"], "display.updated", {**payload, "payload": {"type": "value-preview", "value": False}})
    assert blob not in manager.buffers.live_ids(sid)


def test_deletion_guard_covers_project_and_app_without_blocking_other_projects(manager):
    """活动执行阻止删除；删除期间不能并发新建同项目执行。"""
    from backend.service.application.errors import ResourceInUseError
    sid, _, _, rid = _begin(manager)
    with pytest.raises(ResourceInUseError):
        with manager.deleting_document("p"):
            pass
    manager.accept(sid, rid, "run.finished", {"status": "succeeded"})
    with manager.deleting_document("p", "a"):
        with pytest.raises(PreviewSessionError, match="deleting"):
            with manager.deleting_document("p"):
                pass
        with pytest.raises(PreviewSessionError, match="deleting"):
            manager.create(principal_id="alice", project_id="p", application_id="a", editor_session_id="e")
        assert manager.create(principal_id="alice", project_id="other", application_id="a", editor_session_id="e")


def test_snapshot_depth_limit_rejects_before_execution(manager):
    """深层 JSON 在复制或启动 Worker 前明确拒绝。"""
    sid, _, request, rid = _begin(manager)
    manager.accept(sid, rid, "run.finished", {"status": "succeeded"})
    deep = {}
    for _ in range(40):
        deep = {"child": deep}
    with pytest.raises(PreviewSessionError, match="snapshot_invalid"):
        manager.submit(sid, "alice", {**request, "request_id": str(uuid4()), "input_bindings": deep}, lambda *args: pytest.fail("不应执行"))


def test_submission_deduplicates_and_rejects_conflict(manager):
    """丢失 HTTP 回包后的重试不会重跑有副作用的图。"""
    sid, _, request, rid = _begin(manager)
    def unexpected(*args):
        raise AssertionError("不应重新提交")
    assert manager.submit(sid, "alice", request, unexpected)["run_id"] == rid
    with pytest.raises(PreviewSessionError, match="conflict"):
        manager.submit(sid, "alice", {**request, "document_revision": "r2"}, unexpected)
    with pytest.raises(PreviewSessionError, match="expired"):
        manager.subscribe(sid, "bob")
    with pytest.raises(PreviewSessionError, match="expired"):
        manager.authorize(sid, "alice", ["other"])


def test_late_terminal_and_wrong_run_cannot_overwrite(manager):
    """终态幂等，旧运行完成事件不能写入下一次运行。"""
    sid, _, request, rid = _begin(manager)
    assert manager.accept(sid, rid, "run.finished", {"status": "cancelled"})
    assert not manager.accept(sid, rid, "run.finished", {"status": "succeeded"})
    assert not manager.accept(sid, rid, "run.started", {})
    new = manager.submit(sid, "alice", {**request, "request_id": str(uuid4())}, lambda *args: None)
    assert not manager.accept(sid, rid, "display.updated", {"node_id": "a"})
    assert new["run_id"] != rid


def test_slow_subscriber_gets_current_snapshot_without_unbounded_replay(manager):
    """旧消费者溢出不阻塞执行，新订阅者从当前快照恢复而不读事件文件。"""
    sid, sub, _, rid = _begin(manager)
    manager.accept(sid, rid, "run.started", {})
    for index in range(10):
        manager.accept(sid, rid, "node.finished", {"node_id": f"n{index}", "invocation_id": str(index), "status": "succeeded"})
    manager.accept(sid, rid, "run.finished", {"status": "succeeded", "outputs": {"value": 0}})
    assert sub.overflowed and len(sub.messages) == 0 and sub.bytes == 0
    manager.unsubscribe(sid, sub)
    current, snapshot = manager.subscribe(sid, "alice")
    assert snapshot["payload"]["run"]["state"] == "succeeded"
    assert len(snapshot["payload"]["nodes"]) == 10
    assert manager.take(current) is None


def test_progress_coalesces_but_terminal_remains(manager):
    """只保留最新进度不丢节点终态；序号空隙是合法合并。"""
    sid, sub, _, rid = _begin(manager)
    manager.take(sub)
    for index in range(50):
        manager.accept(sid, rid, "node.progress", {"node_id": "n", "invocation_id": "i", "completed": index, "total": 50})
    manager.accept(sid, rid, "node.finished", {"node_id": "n", "invocation_id": "i", "status": "succeeded"})
    assert not sub.overflowed and len(sub.messages) == 2
    assert manager.take(sub)["payload"]["completed"] == 49
    assert manager.take(sub)["type"] == "node.finished"


def test_disconnect_grace_starts_only_when_last_subscriber_leaves(manager):
    """节点长时间无消息不触发过期，所有消费者离线后才回收。"""
    sid, first, _, _ = _begin(manager)
    second, _ = manager.subscribe(sid, "alice")
    manager.unsubscribe(sid, first)
    manager.expire(now=float("inf"))
    assert manager.authorize(sid, "alice")
    manager.unsubscribe(sid, second)
    manager.expire(now=float("inf"))
    with pytest.raises(PreviewSessionError, match="expired"):
        manager.authorize(sid, "alice")
