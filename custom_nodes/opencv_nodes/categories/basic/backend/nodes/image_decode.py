"""Image Decode：显式解码一次，供同次执行的多个节点复用原始矩阵。"""

from __future__ import annotations

from backend.nodes.runtime_support import register_typed_image_matrix
from backend.service.application.images.image_matrix import IMAGE_MEDIA_TYPE_RAW
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.image-decode"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """保留像素类型及通道，输出生命周期限于当前 Run 的 memory/raw 引用。

    不扩大全局解码缓存，不跨 Run 保留大图；已解码的 memory 输入直接复用。
    """
    cv2, _ = require_opencv_imports()
    source, _, matrix = load_image_matrix(request, imdecode_flags=cv2.IMREAD_UNCHANGED)
    if (
        source.get("transport_kind") == "memory"
        and source.get("media_type") == IMAGE_MEDIA_TYPE_RAW
    ):
        return {"image": source}
    output = register_typed_image_matrix(request, image_matrix=matrix)
    # 解码不改变几何位置，仅传递已有的裁剪来源，不继承旧的存储句柄。
    for key in (
        "mapped_source",
        "roi_id",
        "crop_index",
        "bbox_xyxy",
        "source_object_key",
    ):
        if key in source:
            output[key] = source[key]
    return {"image": output}
