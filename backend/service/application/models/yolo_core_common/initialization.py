"""YOLOv8/11/26 共用模型初始化规则。"""

from __future__ import annotations

from typing import Any


def initialize_yolo_module_settings(*, torch_module: Any, model: Any) -> None:
    """对齐 Ultralytics 的 BatchNorm 和激活层初始化参数。"""

    activation_types = {
        torch_module.nn.Hardswish,
        torch_module.nn.LeakyReLU,
        torch_module.nn.ReLU,
        torch_module.nn.ReLU6,
        torch_module.nn.SiLU,
    }
    for module in model.modules():
        if type(module) is torch_module.nn.BatchNorm2d:
            module.eps = 1e-3
            module.momentum = 0.03
        elif type(module) in activation_types:
            module.inplace = True


def initialize_yolo_graph_model(*, torch_module: Any, model: Any) -> None:
    """在任何 checkpoint 加载前初始化模型设置和任务 head bias。"""

    initialize_yolo_module_settings(torch_module=torch_module, model=model)
    if len(model.model) <= 0:
        return
    task_head = model.model[-1]
    bias_initializer = getattr(task_head, "bias_init", None)
    if callable(bias_initializer):
        bias_initializer()
