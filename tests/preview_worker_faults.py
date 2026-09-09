"""仅依赖标准库的独立 Preview 故障进程，隔离测试模块导入开销。"""
from time import monotonic, sleep

def _uncooperative_worker(*, settings_payload, requests, responses, replies, cancellation):
    """故障注入：持有未发布写映射并忽略取消，验证父进程强制回收。"""
    from multiprocessing.shared_memory import SharedMemory
    responses.put(("ready", {}))
    requests.get()
    responses.put(("memory", {"action": "allocate", "request_id": "write", "byte_length": 1024, "media_type": "image/png"}))
    memory = SharedMemory(name=replies.get()["result"]["name"])
    memory.buf[:4] = b"test"
    responses.put(("lifecycle", {"message_type": "node-started", "node_invocation_id": "blocked",
        "deadline_monotonic": monotonic(), "kill_grace_seconds": .1}))
    sleep(60)
