"""观测的原图身份；不散列整幅矩阵、不生成跨调用共享结果。"""

import hashlib
import json

from backend.contracts.workflows.metrology import ImageIdentity
from backend.service.application.errors import InvalidRequestError


def image_identity(request, payload, image) -> ImageIdentity:
    """引用摘要配合调用 ID 隔离错帧；缺少调用身份时拒绝猜测。"""
    run_id = request.execution_metadata.get(
        "workflow_run_id"
    ) or request.execution_metadata.get("metrology_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise InvalidRequestError("计量观测需要本次 workflow_run_id")
    token = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return ImageIdentity(
        run_id=run_id,
        image_id=hashlib.sha256(token.encode()).hexdigest(),
        width=image.shape[1],
        height=image.shape[0],
        dtype=str(image.dtype),
    )
