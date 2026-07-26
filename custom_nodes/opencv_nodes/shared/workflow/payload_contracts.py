"""OpenCV shared payload 规则 读取辅助。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.workflows.workflow_graph import WorkflowPayloadContract


def get_shared_workflow_dir() -> Path:
    """返回 OpenCV shared workflow 目录。"""

    return Path(__file__).resolve().parent


def get_shared_payload_contracts_path() -> Path:
    """返回共享 payload 规则 JSON 文件路径。"""

    return get_shared_workflow_dir() / "payload_contracts.json"


def load_shared_opencv_payload_contracts_payload() -> list[object]:
    """读取共享 OpenCV payload 规则 JSON 数组。"""

    payload = json.loads(get_shared_payload_contracts_path().read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("OpenCV shared payload_contracts.json 必须是数组")
    return payload


def merge_payload_contracts_for_validation(
    *,
    core_payload_contracts: tuple[WorkflowPayloadContract, ...],
    custom_payload_contracts: tuple[WorkflowPayloadContract, ...],
) -> tuple[WorkflowPayloadContract, ...]:
    """合并 core 与 OpenCV 节点包 payload 规则用于目录校验。

    参数：
    - core_payload_contracts：平台 core payload 规则，作为全局稳定规则优先保留。
    - custom_payload_contracts：当前 OpenCV 节点包随包声明的 payload 规则。

    返回：
    - tuple[WorkflowPayloadContract, ...]：按 payload_type_id 去重后的校验规则列表。

    说明：
    - 开发阶段部分 OpenCV payload 已从 shared 提升到 core，例如 rotated-rects.v1。
    - catalog.json 仍保留节点包自身声明，运行时合并校验时由这里统一去重，避免各节点包各自打补丁。
    """

    merged_payload_contracts: list[WorkflowPayloadContract] = list(core_payload_contracts)
    seen_payload_type_ids = {contract.payload_type_id for contract in merged_payload_contracts}
    for contract in custom_payload_contracts:
        if contract.payload_type_id in seen_payload_type_ids:
            continue
        merged_payload_contracts.append(contract)
        seen_payload_type_ids.add(contract.payload_type_id)
    return tuple(merged_payload_contracts)

