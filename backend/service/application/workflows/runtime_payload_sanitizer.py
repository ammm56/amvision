"""workflow runtime 输入输出脱敏 helper。"""

from __future__ import annotations


def sanitize_runtime_value(value: object) -> object:
    """把 workflow runtime 的输入输出值转换为可持久化的脱敏结构。

    参数：
    - value：待脱敏的任意运行时值。

    返回：
    - object：JSON 安全且已做敏感字段脱敏的值。
    """

    if isinstance(value, dict):
        return _sanitize_mapping(value)
    if isinstance(value, list):
        return [sanitize_runtime_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_runtime_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {
            "binary_redacted": True,
            "byte_length": len(bytes(value)),
        }
    return {
        "value_type": value.__class__.__name__,
        "redacted": True,
    }


def sanitize_runtime_mapping(value: object) -> dict[str, object]:
    """把 workflow runtime 对象值转换为脱敏后的字典。

    参数：
    - value：待脱敏的对象值。

    返回：
    - dict[str, object]：脱敏后的字典；非字典输入返回空字典。
    """

    if not isinstance(value, dict):
        return {}
    sanitized = sanitize_runtime_value(value)
    return sanitized if isinstance(sanitized, dict) else {}


def serialize_node_execution_record(item: object) -> dict[str, object]:
    """把节点执行记录序列化为稳定且已脱敏的 JSON 结构。

    参数：
    - item：节点执行记录对象或字典。

    返回：
    - dict[str, object]：稳定的节点执行记录字典。
    """

    if isinstance(item, dict):
        return {
            "node_id": _read_text(item.get("node_id")),
            "node_type_id": _read_text(item.get("node_type_id")),
            "runtime_kind": _read_text(item.get("runtime_kind")),
            "inputs": sanitize_runtime_mapping(item.get("inputs")),
            "outputs": sanitize_runtime_mapping(item.get("outputs")),
        }
    return {
        "node_id": _read_text(getattr(item, "node_id", "")),
        "node_type_id": _read_text(getattr(item, "node_type_id", "")),
        "runtime_kind": _read_text(getattr(item, "runtime_kind", "")),
        "inputs": sanitize_runtime_mapping(getattr(item, "inputs", {}) or {}),
        "outputs": sanitize_runtime_mapping(getattr(item, "outputs", {}) or {}),
    }


def _sanitize_mapping(value: dict[str, object]) -> dict[str, object]:
    """递归脱敏字典结构中的敏感字段。"""

    sanitized: dict[str, object] = {}
    for key, item in value.items():
        if key == "image_handle" and isinstance(item, str):
            sanitized["image_handle_redacted"] = True
            continue
        if key.endswith("_base64") and isinstance(item, str):
            sanitized[f"{key}_redacted"] = True
            continue
        sanitized[key] = sanitize_runtime_value(item)
    return sanitized


def _read_text(value: object) -> str:
    """把节点记录中的文本字段规范化为字符串。"""

    return value.strip() if isinstance(value, str) else ""