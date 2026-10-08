"""行业节点的本次图像身份、配置解析与通用计算适配。"""

from pydantic import ValidationError
from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.shared.backend.metrology.identity import image_identity

__all__ = ["parse", "image_identity"]


def parse(model, value):
    """把契约错误转换为既有节点参数错误，不吞掉算法异常。"""
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise InvalidRequestError(f"连接器节点输入或配置无效: {exc}") from exc
