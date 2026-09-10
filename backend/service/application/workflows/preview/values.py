"""Preview 完整 JSON 值与分页；摘要、完整值和不可用状态明确分开。"""

import json

from backend.service.application.workflows.runtime_preview import _copy_json


class PreviewValues:
    """完整值只发布到会话 SHM；大数组不进入控制事件队列。"""

    def __init__(self, bridge):
        """bridge 统一管理 Worker 的复制预算与发布所有权。"""
        self.bridge = bridge

    def describe(self, value):
        """小 JSON 内嵌，大 JSON 使用有界 Blob；运行时对象明确不可用。"""
        from uuid import uuid4
        key = f"json:{uuid4().hex}"
        try:
            # 先做不复制容器的结构检查；复制/序列化前预留空间。
            amount = _measure(value, [100_000])
            self.bridge.reserve(key, amount * 3)
            copied = _copy_json(value, [16 * 1024**2, 100_000])
            encoded = json.dumps(copied, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            # ROI 等完整 JSON 可含 execution registry 的不透明图像 id；它不是 OS
            # SHM 名称，也不能用于浏览器取图。保留业务结构并显式标注引用作用域。
            reference = {"reference_scope": "execution"} if _has_execution_image(value) else {}
            if len(encoded) <= 16 * 1024:
                return {"kind": "inline", "value": copied, **reference}
            return {"kind": "json", "transport_kind": "preview-memory",
                    **self.bridge.publish(encoded, "application/json"),
                    "value_type": type(copied).__name__, "total": len(copied) if isinstance(copied, (dict, list, str)) else 1, **reference}
        except (ValueError, TypeError, OverflowError) as error:
            return {"kind": "unavailable", "error": str(error)[:256]}
        finally:
            self.bridge.reserve(key, 0)


def _measure(value, remaining, depth=0):
    """限深、限元素和限字节，避免为检查超大输出先复制整个对象。"""
    import math
    remaining[0] -= 1
    if remaining[0] < 0 or depth > 32:
        raise ValueError("preview_structure_limit")
    if isinstance(value, str):
        size = len(value) * (1 if value.isascii() else 4) + 8
    elif value is None or isinstance(value, (bool, int)):
        size = 32
    elif isinstance(value, float) and math.isfinite(value):
        size = 32
    elif isinstance(value, dict):
        size = 64
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("preview_not_json")
            # SHM 名称、内部对象句柄不是可在浏览器使用的完整值。
            size += _measure(key, remaining, depth + 1) + _measure(item, remaining, depth + 1)
            if size > 16 * 1024**2:
                raise ValueError("preview_value_capacity")
    elif isinstance(value, (list, tuple)):
        size = 64
        for item in value:
            size += _measure(item, remaining, depth + 1)
            if size > 16 * 1024**2:
                raise ValueError("preview_value_capacity")
    else:
        raise ValueError("preview_not_json")
    if size > 16 * 1024**2:
        raise ValueError("preview_value_capacity")
    return size


def _has_execution_image(value):
    """只遍历已通过限深/限元素检查的 JSON；不解析或打开执行期引用。"""
    if isinstance(value, dict):
        return (value.get("transport_kind") == "memory" and "image_handle" in value) or any(_has_execution_image(item) for item in value.values())
    return isinstance(value, (list, tuple)) and any(_has_execution_image(item) for item in value)


def _page(value, path, offset, limit):
    """嵌套容器提供可继续读取的路径，不把它的摘要冒充完整内容。"""
    for key in path:
        value = value[key]
    children = []
    def item(key, content):
        if isinstance(content, (dict, list)) or isinstance(content, str) and len(content) > 1024:
            summary = {"value_type": type(content).__name__, "total": len(content), "summary": True}
            children.append({"key": key, "path": [*path, key], **summary})
            return summary
        return content
    if isinstance(value, dict):
        items = list(value.items())[offset:offset + limit]
        page = {key: item(key, content) for key, content in items}
        total = len(value)
    elif isinstance(value, list):
        page, total = [item(offset + index, content) for index, content in enumerate(value[offset:offset + limit])], len(value)
    elif isinstance(value, str):
        page, total = value[offset:offset + limit], len(value)
    else:
        page, total = value, 1
    if len(json.dumps(page, ensure_ascii=False).encode()) > 64 * 1024:
        raise ValueError("preview_value_page_capacity")
    return {"value": page, "total": total, "offset": offset, "limit": limit,
            "has_more": offset + limit < total, "value_type": type(value).__name__, "path": path, "children": children}
