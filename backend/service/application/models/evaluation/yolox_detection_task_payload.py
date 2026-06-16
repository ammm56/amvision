"""YOLOX detection 评估任务 payload 读写工具。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.evaluation.yolox_detection_task_types import (
    YoloXEvaluationTaskRequest,
    YoloXEvaluationTaskResult,
)
from backend.service.domain.tasks.task_records import TaskRecord


class YoloXEvaluationTaskPayloadMixin:
    """封装 YOLOX 评估任务 TaskRecord 与结果快照读写规则。"""

    def _build_request_from_task_record(self, task_record: TaskRecord) -> YoloXEvaluationTaskRequest:
        """从 TaskRecord 反解析评估任务请求。"""

        task_spec = dict(task_record.task_spec)
        return YoloXEvaluationTaskRequest(
            project_id=self._require_str(task_spec, "project_id"),
            model_version_id=self._require_str(task_spec, "model_version_id"),
            dataset_export_id=self._read_optional_str(task_spec, "dataset_export_id"),
            dataset_export_manifest_key=(
                self._read_optional_str(task_spec, "manifest_object_key")
                or self._read_optional_str(task_spec, "dataset_export_manifest_key")
            ),
            score_threshold=self._read_optional_float(task_spec, "score_threshold"),
            nms_threshold=self._read_optional_float(task_spec, "nms_threshold"),
            save_result_package=self._read_optional_bool(task_spec, "save_result_package") is not False,
            extra_options=self._read_dict(task_spec, "extra_options"),
        )

    def _build_existing_result(self, task_record: TaskRecord) -> YoloXEvaluationTaskResult | None:
        """从已有 TaskRecord 中恢复已完成的评估结果。"""

        result = dict(task_record.result)
        report_object_key = self._read_optional_str(result, "report_object_key")
        detections_object_key = self._read_optional_str(result, "detections_object_key")
        if not report_object_key or not detections_object_key:
            return None
        map50 = self._read_optional_float(result, "map50")
        map50_95 = self._read_optional_float(result, "map50_95")
        return YoloXEvaluationTaskResult(
            task_id=task_record.task_id,
            status=task_record.state,
            dataset_export_id=self._require_str(result, "dataset_export_id"),
            dataset_export_manifest_key=self._require_str(result, "dataset_export_manifest_key"),
            dataset_version_id=self._require_str(result, "dataset_version_id"),
            format_id=self._require_str(result, "format_id"),
            model_version_id=self._require_str(result, "model_version_id"),
            output_object_prefix=self._require_str(result, "output_object_prefix"),
            report_object_key=report_object_key,
            detections_object_key=detections_object_key,
            result_package_object_key=self._read_optional_str(result, "result_package_object_key"),
            map50=map50 if map50 is not None else 0.0,
            map50_95=map50_95 if map50_95 is not None else 0.0,
            report_summary=self._read_dict(result, "report_summary"),
        )

    def _serialize_task_result(self, task_result: YoloXEvaluationTaskResult) -> dict[str, object]:
        """把评估任务处理结果序列化为任务结果快照。"""

        return {
            "dataset_export_id": task_result.dataset_export_id,
            "dataset_export_manifest_key": task_result.dataset_export_manifest_key,
            "dataset_version_id": task_result.dataset_version_id,
            "format_id": task_result.format_id,
            "model_version_id": task_result.model_version_id,
            "output_object_prefix": task_result.output_object_prefix,
            "report_object_key": task_result.report_object_key,
            "detections_object_key": task_result.detections_object_key,
            "result_package_object_key": task_result.result_package_object_key,
            "map50": task_result.map50,
            "map50_95": task_result.map50_95,
            "report_summary": dict(task_result.report_summary),
        }

    @staticmethod
    def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
        """从字典中读取可选字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _read_optional_float(payload: dict[str, object], key: str) -> float | None:
        """从字典中读取可选浮点数字段。"""

        value = payload.get(key)
        if isinstance(value, int | float):
            return float(value)
        return None

    @staticmethod
    def _read_optional_bool(payload: dict[str, object], key: str) -> bool | None:
        """从字典中读取可选布尔字段。"""

        value = payload.get(key)
        if isinstance(value, bool):
            return value
        return None

    @staticmethod
    def _read_dict(payload: dict[str, object], key: str) -> dict[str, object]:
        """从字典中读取可选对象字段。"""

        value = payload.get(key)
        if isinstance(value, dict):
            return {str(item_key): item_value for item_key, item_value in value.items()}
        return {}

    def _require_str(self, payload: dict[str, object], key: str) -> str:
        """从字典中读取必填字符串字段。"""

        value = self._read_optional_str(payload, key)
        if value is None:
            raise InvalidRequestError(
                "评估任务缺少必要字段",
                details={"field": key},
            )
        return value
