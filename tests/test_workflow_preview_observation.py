"""Preview 循环调用身份、真实进度与内存预算的行为验证。"""

from threading import Thread, Barrier

import pytest

from backend.service.application.workflows.preview.events import PreviewNodeEvents
from backend.service.application.workflows.preview.buffers import PreviewBuffers, PreviewMemoryError


def test_loop_and_parallel_invocations_share_display_progress_identity():
    """同一节点并行/循环不能互相覆盖，结束后不保留调用历史表。"""
    events = []
    observer = PreviewNodeEvents(lambda kind, payload: events.append((kind, payload)), ["loop", "node"])
    barrier = Barrier(2)

    def branch(index):
        for iteration in range(10):
            payload = {"node_id": f"loop[{iteration + 1}].node", "for_each_node_id": "loop",
                       "for_each_iteration_index": iteration, "parallel_branch_index": index}
            observer({"event_type": "node.started", "payload": payload})
            identity = observer.current()
            barrier.wait(timeout=2)
            observer.progress(completed=0, total=1)
            assert identity == observer.current()
            observer({"event_type": "node.completed", "payload": payload})

    threads = [Thread(target=branch, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    assert not observer._active
    started = [payload for kind, payload in events if kind == "node.started"]
    finished = [payload for kind, payload in events if kind == "node.finished"]
    assert len(started) == 20
    assert {payload["node_id"] for payload in started} == {"node"}
    assert len({payload["invocation_id"] for payload in started}) == 20
    assert {payload["invocation_id"] for payload in started} == {payload["invocation_id"] for payload in finished}
    assert all(payload["completed"] == 0 for kind, payload in events if kind == "node.progress")


def test_shm_and_encoder_reservations_use_the_same_budget():
    """不能分别占满多个独立限额；借用数据释放后统一计量归零。"""
    buffers = PreviewBuffers(session_limit=16, total_limit=32)
    try:
        buffers.reserve("a", "worker:encode", 8)
        buffers.allocate("a", 8, media_type="image/png")
        with pytest.raises(PreviewMemoryError, match="capacity"):
            buffers.reserve("a", "worker:encode", 9)
        buffers.reserve("b", "state", 16)
        with pytest.raises(PreviewMemoryError, match="capacity"):
            buffers.allocate("c", 1, media_type="image/png")
        buffers.release_reservations("a", "worker:")
        buffers.release_owner("a")
        assert buffers.stats()["bytes"] == 0
        assert buffers.stats()["reserved_bytes"] == 16
    finally:
        buffers.close()
