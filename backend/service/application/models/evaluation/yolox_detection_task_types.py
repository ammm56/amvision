"""YOLOX detection 评估任务类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.contracts.datasets.exports.voc_detection_export import VOC_DETECTION_DATASET_FORMAT


YOLOX_EVALUATION_TASK_KIND = "yolox-evaluation"
YOLOX_EVALUATION_QUEUE_NAME = "yolox-evaluations"
YOLOX_EVALUATION_DEFAULT_SCORE_THRESHOLD = 0.01
YOLOX_EVALUATION_DEFAULT_NMS_THRESHOLD = 0.65
YOLOX_EVALUATION_SUPPORTED_FORMATS = frozenset(
    {
        COCO_DETECTION_DATASET_FORMAT,
        VOC_DETECTION_DATASET_FORMAT,
    }
)


@dataclass(frozen=True)
class YoloXEvaluationTaskRequest:
    """描述一次 YOLOX 数据集级评估任务创建请求。"""

    project_id: str
    model_version_id: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    score_threshold: float | None = None
    nms_threshold: float | None = None
    save_result_package: bool = True
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXEvaluationTaskSubmission:
    """描述一次 YOLOX 评估任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str
    model_version_id: str


@dataclass(frozen=True)
class YoloXEvaluationTaskResult:
    """描述一次 YOLOX 评估任务处理结果。"""

    task_id: str
    status: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str
    model_version_id: str
    output_object_prefix: str
    report_object_key: str
    detections_object_key: str
    result_package_object_key: str | None
    map50: float
    map50_95: float
    report_summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXEvaluationTaskPackage:
    """描述一次 YOLOX 评估结果包输出。"""

    task_id: str
    package_object_key: str
    package_file_name: str
    package_size: int
    packaged_at: str
