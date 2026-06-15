"""RF-DETR core 导出处理模块：`export._onnx.__init__`。"""

from backend.service.application.models.rfdetr_core.export._onnx import (
    exporter,
    symbolic,
)
from backend.service.application.models.rfdetr_core.export._onnx.exporter import (
    OnnxOptimizer,
    export_onnx,
    onnx_simplify,
)
from backend.service.application.models.rfdetr_core.export._onnx.symbolic import (
    CustomOpSymbolicRegistry,
)
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    ModelTaskType,
)

RFDETR_DETECTION_ONNX_OUTPUT_NAMES = ("pred_boxes", "pred_logits")
RFDETR_SEGMENTATION_ONNX_OUTPUT_NAMES = (
    "pred_boxes",
    "pred_logits",
    "pred_masks",
)


def resolve_rfdetr_onnx_output_names(
    task_type: ModelTaskType,
) -> tuple[str, ...]:
    """执行 `resolve_rfdetr_onnx_output_names`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    normalized_task_type = str(task_type).strip().lower()
    if normalized_task_type == SEGMENTATION_TASK_TYPE:
        return RFDETR_SEGMENTATION_ONNX_OUTPUT_NAMES
    if normalized_task_type == DETECTION_TASK_TYPE:
        return RFDETR_DETECTION_ONNX_OUTPUT_NAMES
    raise ValueError(f"RF-DETR ONNX 导出不支持 task_type={task_type!r}")

__all__ = [
    "CustomOpSymbolicRegistry",
    "OnnxOptimizer",
    "RFDETR_DETECTION_ONNX_OUTPUT_NAMES",
    "RFDETR_SEGMENTATION_ONNX_OUTPUT_NAMES",
    "export_onnx",
    "exporter",
    "onnx_simplify",
    "resolve_rfdetr_onnx_output_names",
    "symbolic",
]
