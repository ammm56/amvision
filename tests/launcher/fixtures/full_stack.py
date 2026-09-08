"""C# 集成测试使用的短生命周期 full 栈，不绑定端口或读取项目业务数据。"""

import json
from pathlib import Path
import subprocess
import socket
import sys
import time

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "launchers"))
from common import clear_full_state, full_state_guard, read_process_identity, write_full_json  # noqa: E402

identity = read_process_identity(__import__("os").getpid())
state_file = root / "logs" / "full-stack" / "runtime-state.json"
request_file = state_file.with_name("runtime-state.shutdown-request.json")
status_file = state_file.with_name("launcher-status.json")
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
listener = socket.socket()
listener.bind(("127.0.0.1", int((root / "listener-port.txt").read_text())))
listener.listen()
try:
    with full_state_guard(state_file):
        write_full_json(state_file, {
            "format_id": "amvision.full-supervisor-state.v1", "app_root": str(root),
            "root_process": identity, "components": [{"name": "fixture-worker", "process": read_process_identity(child.pid), "stop_mode": "process-tree"}],
        })
        write_full_json(status_file, {"format_id": "amvision.launcher-status.v1", "root_process": identity, "state": "running"})
    print("测试栈就绪，中文输出。", flush=True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if request_file.is_file() and json.loads(request_file.read_text(encoding="utf-8")).get("root_process") == identity:
            break
        time.sleep(0.1)
finally:
    listener.close()
    child.terminate()
    child.wait(timeout=5)
    clear_full_state(state_file, identity)
