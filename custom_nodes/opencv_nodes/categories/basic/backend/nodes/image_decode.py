"""Image Decode：显式解码一次，供同次执行的多个节点复用原始矩阵。"""

from __future__ import annotations

from backend.nodes.runtime_support import (
    load_image_content,
    register_typed_image_matrix,
    resolve_image_reference,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.images.image_matrix import IMAGE_MEDIA_TYPE_RAW
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import (
    load_image_matrix,
    resolve_image_file_path,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.image-decode"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """保留像素类型及通道，输出生命周期限于当前 Run 的 memory/raw 引用。

    不扩大全局解码缓存，不跨 Run 保留大图；已解码的 memory 输入直接复用。
    """
    cv2, _ = require_opencv_imports()
    method = request.parameters.get("decode_method", "opencv")
    if method not in {"opencv", "bmp-bgr24"}:
        raise InvalidRequestError("Image Decode 的 decode_method 无效")
    reference = resolve_image_reference(request)
    if reference.media_type == IMAGE_MEDIA_TYPE_RAW:
        # 原始像素不经过编码格式解码；协议 buffer/frame 仍复用现有读取与校验。
        source, _, matrix = load_image_matrix(
            request, imdecode_flags=cv2.IMREAD_UNCHANGED
        )
        if reference.transport_kind == "memory":
            return {"image": source}
    elif method == "bmp-bgr24":
        from custom_nodes.opencv_nodes.shared.backend.runtime.bmp import (
            decode_bgr24_bmp,
            read_bgr24_bmp,
        )

        if reference.transport_kind in {"local-path", "storage"}:
            source, path = resolve_image_file_path(request)
            matrix = read_bgr24_bmp(path)
        else:
            # 上传/协议输入也遵循相同格式约束，不落盘或隐式换用其他解码器。
            source, content = load_image_content(request)
            try:
                matrix = decode_bgr24_bmp(content)
            finally:
                if isinstance(content, memoryview):
                    content.release()
    else:
        source, _, matrix = load_image_matrix(
            request, imdecode_flags=cv2.IMREAD_UNCHANGED
        )
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
