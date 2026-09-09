"""仅供内部 segmentation 评估保留原始 mask，不扩展公开推理协议。"""

from dataclasses import dataclass, field

from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionInstance,
    SegmentationPredictionRequest,
)


@dataclass(frozen=True)
class SegmentationEvaluationPredictionRequest(SegmentationPredictionRequest):
    """请求指标所需的原始 mask；普通 extra_options 不能启用此模式。"""


@dataclass(frozen=True)
class SegmentationEvaluationPredictionInstance(SegmentationPredictionInstance):
    """离线指标实例保留压缩 RLE，避免孔洞和细线被外轮廓重建改变。"""

    mask_rle: dict[str, object] = field(kw_only=True)


def retain_segmentation_metric_mask(request: SegmentationPredictionRequest) -> bool:
    """仅识别内部强类型请求，普通逐帧结果不增加 RLE 编码。"""
    return isinstance(request, SegmentationEvaluationPredictionRequest)
