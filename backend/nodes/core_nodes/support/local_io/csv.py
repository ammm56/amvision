"""CSV 字段展开 helper。"""

from __future__ import annotations

import json


def flatten_mapping_for_csv(value: object) -> dict[str, str]:
    """把 JSON 安全值扁平化为 CSV 可写的一行字符串字典。"""

    normalized_value = json.loads(json.dumps(value, ensure_ascii=False))
    flattened: dict[str, str] = {}
    _flatten_value_for_csv(
        value=normalized_value,
        target=flattened,
        prefix="",
    )
    return flattened


def _flatten_value_for_csv(
    *,
    value: object,
    target: dict[str, str],
    prefix: str,
) -> None:
    """递归展开 CSV 行字段。"""

    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_value_for_csv(value=item, target=target, prefix=next_prefix)
        return
    if isinstance(value, list):
        target[prefix or "value"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return
    target[prefix or "value"] = "" if value is None else str(value)
