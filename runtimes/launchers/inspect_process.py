"""启动器的只读进程检查，复用 bundled Python/psutil 的完整身份定义。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from common import read_process_identity, resolve_app_root, resolve_code_root


def main() -> int:
    """读取指定 PID 的完整身份与祖先进程；不执行启动、停止或业务操作。"""

    parser = argparse.ArgumentParser(description="launcher process identity probe")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--app-root")
    parser.add_argument("--listening-port", type=int)
    args = parser.parse_args()
    code_root = resolve_code_root(resolve_app_root(
        script_file=Path(__file__), explicit_app_root=args.app_root,
    ))
    sys.path.insert(0, str(code_root))
    import psutil

    try:
        process = psutil.Process(args.pid)
        payload = {
            "format_id": "amvision.launcher-process.v2",
            "identity": read_process_identity(args.pid),
            "ancestor_pids": [parent.pid for parent in process.parents()],
        }
    except psutil.NoSuchProcess:
        payload = {"format_id": "amvision.launcher-process.v2", "identity": None, "ancestor_pids": []}
    if args.listening_port is not None:
        listeners = []
        pids = {
            connection.pid for connection in psutil.net_connections(kind="tcp")
            if connection.status == psutil.CONN_LISTEN and connection.pid
            and connection.laddr.port == args.listening_port
            and connection.laddr.ip in {"127.0.0.1", "0.0.0.0", "::", "::1"}
        }
        for pid in pids:
            try:
                listeners.append({"identity": read_process_identity(pid), "ancestor_pids": [parent.pid for parent in psutil.Process(pid).parents()]})
            except psutil.NoSuchProcess:
                continue
        payload["listeners"] = listeners
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
