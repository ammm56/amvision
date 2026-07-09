"""workflow runtime 输入输出脱敏 helper。"""

from __future__ import annotations


MAX_PERSISTED_STRING_CHARS = 8192
MAX_PERSISTED_COLLECTION_ITEMS = 256
MAX_PERSISTED_NESTING_DEPTH = 12


def sanitize_runtime_value(value: object) -> object:
    """把 workflow runtime 的输入输出值转换为可持久化的脱敏结构。

    参数：
    - value：待脱敏的任意运行时值。

    返回：
    - object：JSON 安全且已做敏感字段脱敏的值。
    """

    return _sanitize_runtime_value(value, depth=0)


def _sanitize_runtime_value(value: object, *, depth: int) -> object:
    """按深度限制把运行时值转换为可持久化结构。

    参数：
    - value：待脱敏的任意运行时值。
    - depth：当前递归深度。

    返回：
    - object：JSON 安全且大小受控的值。
    """

    if depth > MAX_PERSISTED_NESTING_DEPTH:
        return {
            "value_type": value.__class__.__name__,
            "redacted": True,
            "reason": "max_depth_exceeded",
        }

    if isinstance(value, dict):
        return _sanitize_mapping(value, depth=depth + 1)
    if isinstance(value, list):
        return _sanitize_sequence(value, depth=depth + 1)
    if isinstance(value, tuple):
        return _sanitize_sequence(list(value), depth=depth + 1)
    if isinstance(value, str):
        if len(value) > MAX_PERSISTED_STRING_CHARS:
            return {
                "text_redacted": True,
                "char_length": len(value),
            }
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {
            "binary_redacted": True,
            "byte_length": _read_binary_length(value),
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
            "duration_ms": _read_optional_float(item.get("duration_ms")),
            "inputs": sanitize_runtime_mapping(item.get("inputs")),
            "outputs": sanitize_runtime_mapping(item.get("outputs")),
        }
    return {
        "node_id": _read_text(getattr(item, "node_id", "")),
        "node_type_id": _read_text(getattr(item, "node_type_id", "")),
        "runtime_kind": _read_text(getattr(item, "runtime_kind", "")),
        "duration_ms": _read_optional_float(getattr(item, "duration_ms", None)),
        "inputs": sanitize_runtime_mapping(getattr(item, "inputs", {}) or {}),
        "outputs": sanitize_runtime_mapping(getattr(item, "outputs", {}) or {}),
    }


def serialize_node_execution_record_for_response(item: object) -> dict[str, object]:
    """把节点执行记录序列化为同步响应可直接返回的 JSON 结构。

    参数：
    - item：节点执行记录对象或字典。

    返回：
    - dict[str, object]：保留原始 outputs、仅对 inputs 做轻量脱敏的节点执行记录。
    """

    if isinstance(item, dict):
        return {
            "node_id": _read_text(item.get("node_id")),
            "node_type_id": _read_text(item.get("node_type_id")),
            "runtime_kind": _read_text(item.get("runtime_kind")),
            "duration_ms": _read_optional_float(item.get("duration_ms")),
            "inputs": sanitize_runtime_mapping(item.get("inputs")),
            "outputs": _copy_runtime_mapping(item.get("outputs")),
        }
    return {
        "node_id": _read_text(getattr(item, "node_id", "")),
        "node_type_id": _read_text(getattr(item, "node_type_id", "")),
        "runtime_kind": _read_text(getattr(item, "runtime_kind", "")),
        "duration_ms": _read_optional_float(getattr(item, "duration_ms", None)),
        "inputs": sanitize_runtime_mapping(getattr(item, "inputs", {}) or {}),
        "outputs": _copy_runtime_mapping(getattr(item, "outputs", {}) or {}),
    }


def _sanitize_mapping(value: dict[str, object], *, depth: int) -> dict[str, object]:
    """递归脱敏字典结构中的敏感字段。

    参数：
    - value：待脱敏的字典。
    - depth：当前递归深度。

    返回：
    - dict[str, object]：大小受控且已脱敏的字典。
    """

    sanitized: dict[str, object] = {}
    for index, (raw_key, item) in enumerate(value.items()):
        if index >= MAX_PERSISTED_COLLECTION_ITEMS:
            sanitized["mapping_truncated"] = True
            sanitized["original_key_count"] = len(value)
            break
        key = raw_key if isinstance(raw_key, str) else str(raw_key)
        if key == "image_handle" and isinstance(item, str):
            sanitized["image_handle_redacted"] = True
            continue
        if key.endswith("_base64") and isinstance(item, str):
            sanitized[f"{key}_redacted"] = True
            sanitized[f"{key}_char_length"] = len(item)
            continue
        sanitized[key] = _sanitize_runtime_value(item, depth=depth)
    return sanitized


def _copy_runtime_mapping(value: object) -> dict[str, object]:
    """把运行时字典浅拷贝为稳定 JSON mapping。

    参数：
    - value：待复制的运行时对象。

    返回：
    - dict[str, object]：键名规范化后的浅拷贝；非字典输入返回空字典。
    """

    if not isinstance(value, dict):
        return {}
    return {
        raw_key if isinstance(raw_key, str) else str(raw_key): item
        for raw_key, item in value.items()
    }


def _sanitize_sequence(value: list[object], *, depth: int) -> object:
    """递归脱敏列表并限制持久化条数。

    参数：
    - value：待脱敏的列表。
    - depth：当前递归深度。

    返回：
    - object：未超限时返回列表，超限时返回摘要字典。
    """

    if len(value) <= MAX_PERSISTED_COLLECTION_ITEMS:
        return [_sanitize_runtime_value(item, depth=depth) for item in value]
    return {
        "sequence_truncated": True,
        "item_count": len(value),
        "items": [
            _sanitize_runtime_value(item, depth=depth)
            for item in value[:MAX_PERSISTED_COLLECTION_ITEMS]
        ],
    }


def _read_binary_length(value: bytes | bytearray | memoryview) -> int:
    """读取二进制对象长度且避免复制完整内容。

    参数：
    - value：bytes、bytearray 或 memoryview 对象。

    返回：
    - int：二进制内容字节数。
    """

    if isinstance(value, memoryview):
        return value.nbytes
    return len(value)


def _read_text(value: object) -> str:
    """把节点记录中的文本字段规范化为字符串。"""

    return value.strip() if isinstance(value, str) else ""


def _read_optional_float(value: object) -> float | None:
    """把节点记录中的可选数值字段规范化为 float。"""

    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
