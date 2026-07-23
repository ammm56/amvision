"""RF-DETR TensorRT runtime 小工具。"""

from __future__ import annotations

from typing import Any


def list_rfdetr_tensorrt_output_names(
    engine: Any, *, tensorrt_module: Any
) -> list[str]:
    """按 TensorRT engine 的 I/O tensor 顺序列出所有输出张量名。"""

    names: list[str] = []
    for index in range(int(engine.num_io_tensors)):
        name = engine.get_tensor_name(index)
        if engine.get_tensor_mode(name) == tensorrt_module.TensorIOMode.OUTPUT:
            names.append(name)
    return names
