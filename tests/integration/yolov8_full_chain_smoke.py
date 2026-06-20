"""YOLOv8 短链路验收入口。

保留该入口是为了旧命令仍能运行；真实实现统一在 yolo_primary_full_chain_smoke。
"""

from __future__ import annotations

import sys

from tests.integration.yolo_primary_full_chain_smoke import main


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--model-type" not in argv:
        argv = ["--model-type", "yolov8", *argv]
    raise SystemExit(main(argv))
