"""OpenCV shared payload contract 读取辅助。"""

from __future__ import annotations

import json
from pathlib import Path


def get_shared_workflow_dir() -> Path:
    """返回 OpenCV shared workflow 目录。"""

    return Path(__file__).resolve().parent


def get_shared_payload_contracts_path() -> Path:
    """返回共享 payload contract JSON 文件路径。"""

    return get_shared_workflow_dir() / "payload_contracts.json"


def load_shared_opencv_payload_contracts_payload() -> list[object]:
    """读取共享 OpenCV payload contract JSON 数组。"""

    payload = json.loads(get_shared_payload_contracts_path().read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("OpenCV shared payload_contracts.json 必须是数组")
    return payload

