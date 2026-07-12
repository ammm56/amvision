"""workflow 节点参数读取公共工具。"""

from __future__ import annotations


def is_empty_parameter(value: object) -> bool:
    """判断节点参数是否按“未填写”处理。

    参数：
    - value：节点参数原始值，可能来自前端表单、图像交互面板或 workflow JSON。

    返回：
    - bool：仅 None 和空字符串表示未填写；数组、对象、数值和布尔值必须保留给后续类型校验。
    """

    return value is None or (isinstance(value, str) and value == "")
