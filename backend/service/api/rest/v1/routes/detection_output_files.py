"""detection 任务输出文件读取 helper。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.yolox_output_files import (
    YoloXTrainingMetricsFileResponse,
    YoloXTrainingOutputFileDetailResponse,
    YoloXTrainingOutputFileSummaryResponse,
    _YOLOX_TRAINING_OUTPUT_FILE_ORDER as _DETECTION_TRAINING_OUTPUT_FILE_ORDER,
)
from backend.service.api.rest.v1.routes.yolox_output_files import (
    _build_yolox_training_metrics_file_response,
    _build_yolox_training_output_file_summary_response,
    _parse_yolox_training_output_file_name as _parse_detection_training_output_file_name,
    _read_yolox_training_output_file as _read_detection_training_output_file,
)


class DetectionTrainingMetricsFileResponse(YoloXTrainingMetricsFileResponse):
    """描述 detection 训练 JSON 输出文件读取响应。"""


class DetectionTrainingOutputFileSummaryResponse(YoloXTrainingOutputFileSummaryResponse):
    """描述单个 detection 训练输出文件的读取状态。"""


class DetectionTrainingOutputFileDetailResponse(YoloXTrainingOutputFileDetailResponse):
    """描述单个 detection 训练输出文件的读取结果。"""


def _build_detection_training_metrics_file_response(
    output_file: YoloXTrainingOutputFileDetailResponse,
) -> DetectionTrainingMetricsFileResponse:
    """把训练 JSON 输出文件详情转换为 detection metrics 响应。"""

    response = _build_yolox_training_metrics_file_response(output_file)
    return DetectionTrainingMetricsFileResponse.model_validate(response.model_dump())


def _build_detection_training_output_file_summary_response(
    output_file: YoloXTrainingOutputFileDetailResponse,
) -> DetectionTrainingOutputFileSummaryResponse:
    """把训练输出文件详情压缩成 detection 列表项响应。"""

    response = _build_yolox_training_output_file_summary_response(output_file)
    return DetectionTrainingOutputFileSummaryResponse.model_validate(response.model_dump())
