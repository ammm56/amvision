"""Preview RPC 超时不可复用；迟到回复不能污染下一轮会话。"""

from queue import Empty, Queue

import pytest

from backend.service.application.workflows.preview.bridge import PreviewMemoryBridge


def test_timeout_latches_channel_and_rejects_late_reply():
    """实际超时类型被转换成可诊断错误，后续调用不再发送或消费旧回复。"""

    class Replies(Queue):
        def get(self, *args, **kwargs):
            raise Empty

    requests, replies = Queue(), Replies()
    bridge = PreviewMemoryBridge(requests, replies)
    with pytest.raises(RuntimeError, match="channel_failed:reserve"):
        bridge.call("reserve", byte_length=8)
    assert bridge.failed and requests.qsize() == 1
    replies.put({"request_id": "late", "result": {}})
    with pytest.raises(RuntimeError, match="channel_failed"):
        bridge.call("allocate", byte_length=8)
    assert requests.qsize() == 1 and replies.qsize() == 1


def test_stale_reply_marks_worker_unusable():
    """旧请求的回复不允许被当作新请求结果。"""
    requests, replies = Queue(), Queue()
    replies.put({"request_id": "old", "result": {}})
    bridge = PreviewMemoryBridge(requests, replies)
    with pytest.raises(RuntimeError, match="protocol_invalid"):
        bridge.call("reserve", byte_length=8)
    assert bridge.failed


def test_business_rejection_does_not_poison_channel():
    """预算拒绝属于正常协议回复，不能使健康 Worker 退出。"""
    requests = Queue()

    class Replies:
        def get(self, timeout):
            _, request = requests.get_nowait()
            return {
                "request_id": request["request_id"],
                "error": "preview_memory_capacity",
            }

    bridge = PreviewMemoryBridge(requests, Replies())
    with pytest.raises(ValueError, match="preview_memory_capacity"):
        bridge.call("reserve", byte_length=8)
    assert not bridge.failed
