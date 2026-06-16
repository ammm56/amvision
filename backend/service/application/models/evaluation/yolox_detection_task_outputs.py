"""YOLOX detection 评估任务输出工具。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import zipfile

from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.models.evaluation.yolox_detection import (
    YoloXDetectionEvaluationResult,
)
from backend.service.application.models.evaluation.yolox_detection_task_types import (
    YoloXEvaluationTaskPackage,
    YoloXEvaluationTaskRequest,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class YoloXEvaluationOutputObjectKeys:
    """YOLOX 评估产物在对象存储中的 object key 集合。"""

    output_object_prefix: str
    output_files_root: str
    report_object_key: str
    detections_object_key: str
    result_package_object_key: str | None


class YoloXEvaluationTaskOutputsMixin:
    """封装 YOLOX 评估产物 object key、报告写入和结果包打包规则。"""

    def _build_evaluation_output_object_keys(
        self,
        *,
        task_id: str,
        save_result_package: bool,
    ) -> YoloXEvaluationOutputObjectKeys:
        """根据任务 id 生成稳定的评估产物 object key。"""

        output_object_prefix = self._build_output_object_prefix(task_id)
        output_files_root = f"{output_object_prefix}/artifacts"
        return YoloXEvaluationOutputObjectKeys(
            output_object_prefix=output_object_prefix,
            output_files_root=output_files_root,
            report_object_key=f"{output_files_root}/reports/evaluation-report.json",
            detections_object_key=f"{output_files_root}/reports/detections.json",
            result_package_object_key=(
                self._build_result_package_object_key(task_id)
                if save_result_package
                else None
            ),
        )

    def _write_evaluation_report_outputs(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        output_keys: YoloXEvaluationOutputObjectKeys,
        evaluation_result: YoloXDetectionEvaluationResult,
    ) -> None:
        """写出评估报告和逐样本 detection 明细。"""

        dataset_storage.write_json(output_keys.report_object_key, evaluation_result.report_payload)
        dataset_storage.write_json(
            output_keys.detections_object_key,
            evaluation_result.detections_payload,
        )

    def _build_report_summary(
        self,
        *,
        request: YoloXEvaluationTaskRequest,
        dataset_export: DatasetExport,
        evaluation_result: YoloXDetectionEvaluationResult,
        report_object_key: str,
        detections_object_key: str,
        result_package_object_key: str | None,
    ) -> dict[str, object]:
        """构建评估任务摘要。"""

        return {
            "implementation_mode": "yolox-evaluation-core",
            "model_version_id": request.model_version_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_version_id": dataset_export.dataset_version_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "split_name": evaluation_result.split_name,
            "sample_count": evaluation_result.sample_count,
            "score_threshold": self._resolve_score_threshold(request),
            "nms_threshold": self._resolve_nms_threshold(request),
            "save_result_package": request.save_result_package,
            "duration_seconds": evaluation_result.duration_seconds,
            "map50": evaluation_result.map50,
            "map50_95": evaluation_result.map50_95,
            "per_class_metrics": [dict(item) for item in evaluation_result.per_class_metrics],
            "report_object_key": report_object_key,
            "detections_object_key": detections_object_key,
            "result_package_object_key": result_package_object_key,
        }

    def _require_packageable_result(self, task_record: TaskRecord) -> tuple[str, str]:
        """返回评估结果包所需的 report 和 detections object key。"""

        if task_record.state != "succeeded":
            raise InvalidRequestError(
                "当前评估任务尚未成功完成，不能生成结果包",
                details={"task_id": task_record.task_id, "state": task_record.state},
            )
        result = dict(task_record.result)
        report_object_key = self._read_optional_str(result, "report_object_key")
        detections_object_key = self._read_optional_str(result, "detections_object_key")
        if report_object_key is None or detections_object_key is None:
            raise InvalidRequestError(
                "当前评估任务缺少可打包输出",
                details={"task_id": task_record.task_id},
            )

        dataset_storage = self._require_dataset_storage()
        for file_name, object_key in (
            ("report", report_object_key),
            ("detections", detections_object_key),
        ):
            if not dataset_storage.resolve(object_key).is_file():
                raise ResourceNotFoundError(
                    "当前评估任务缺少可打包输出文件",
                    details={
                        "task_id": task_record.task_id,
                        "file_name": file_name,
                        "object_key": object_key,
                    },
                )
        return report_object_key, detections_object_key

    def _write_result_package(
        self,
        *,
        result_package_object_key: str,
        report_object_key: str,
        detections_object_key: str,
    ) -> None:
        """把 report 和 detections 打包成评估结果包。"""

        dataset_storage = self._require_dataset_storage()
        package_path = dataset_storage.resolve(result_package_object_key)
        package_path.parent.mkdir(parents=True, exist_ok=True)
        report_path = dataset_storage.resolve(report_object_key)
        detections_path = dataset_storage.resolve(detections_object_key)
        with zipfile.ZipFile(package_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(report_path, arcname="report.json")
            archive.write(detections_path, arcname="detections.json")

    def _build_evaluation_task_package(
        self,
        *,
        task_id: str,
        package_object_key: str,
    ) -> YoloXEvaluationTaskPackage:
        """按 object key 构建评估结果包输出摘要。"""

        dataset_storage = self._require_dataset_storage()
        package_path = dataset_storage.resolve(package_object_key)
        if not package_path.is_file():
            raise ResourceNotFoundError(
                "评估结果包文件不存在",
                details={"task_id": task_id, "object_key": package_object_key},
            )
        package_stat = package_path.stat()
        return YoloXEvaluationTaskPackage(
            task_id=task_id,
            package_object_key=package_object_key,
            package_file_name=package_path.name,
            package_size=package_stat.st_size,
            packaged_at=datetime.fromtimestamp(package_stat.st_mtime, tz=timezone.utc).isoformat(),
        )

    def _build_result_package_object_key(self, task_id: str) -> str:
        """构建评估结果包默认 object key。"""

        return f"{self._build_output_object_prefix(task_id)}/artifacts/packages/result-package.zip"

    def _build_output_object_prefix(self, task_id: str) -> str:
        """构建评估任务输出目录前缀。"""

        return f"task-runs/evaluation/{task_id}"

    @staticmethod
    def _normalize_optional_object_key(value: str | None) -> str | None:
        """规范化可选结果包 object key。"""

        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
