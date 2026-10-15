"""POSIX 组身份守护：目标退出后保留组身份，owner 管道断开时整组结束。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.runtime.processes.birth_identity import read_process_birth_identity


def main() -> int:
    """在放行目标之前公布身份；本进程与目标始终属于同一 session/process group。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready-fd", type=int)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    root = Path(os.environ["AMVISION_PROCESS_SCOPE"])
    group_id = os.environ["AMVISION_PROCESS_PARENT"]
    temporary = root / f"{group_id}.anchor.tmp"
    temporary.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "birth_identity": read_process_birth_identity(os.getpid()),
                "pgid": os.getpgrp(),
            }
        ),
        encoding="utf-8",
    )
    temporary.replace(root / f"{group_id}.anchor")
    if args.ready_fd is not None:
        token = os.read(0, 1)
        if token != b"\x01":
            os.killpg(os.getpgrp(), signal.SIGKILL)
            return 125
        os.write(args.ready_fd, token)
        os.close(args.ready_fd)
    # 使用原始 fd，不持有 Python 缓冲流锁，也不依赖业务主线程心跳。
    while os.read(0, 1):
        pass
    os.killpg(os.getpgrp(), signal.SIGKILL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
