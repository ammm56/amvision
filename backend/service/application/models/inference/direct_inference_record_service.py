"""同步推理显式保存记录的应用服务。"""

from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from backend.service.application.deployments.deployment_instance_service import (
    SqlAlchemyDeploymentInstanceService,
)
from backend.service.application.errors import (
    InvalidRequestError,
    PersistenceOperationError,
    ResourceNotFoundError,
)
from backend.service.application.project_mutation import ProjectMutationAdmissionService
from backend.service.application.project_public_files import (
    resolve_public_project_file_reference,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.infrastructure.object_store.object_key_layout import (
    is_public_project_object_key,
)
from backend.service.infrastructure.persistence.direct_inference_record_orm import (
    DirectInferenceRecord,
)

SUPPORTED_INFERENCE_TASK_TYPES: tuple[str, ...] = (
    "detection",
    "classification",
    "segmentation",
    "pose",
    "obb",
)


def _now_isoformat() -> str:
    """生成 ISO8601 UTC 时间戳。"""

    return datetime.now(timezone.utc).isoformat()


def normalize_inference_task_type(value: str) -> str:
    """校验并规范化当前平台支持的在线推理任务类型。"""

    normalized = value.strip().lower() if isinstance(value, str) else ""
    if normalized not in SUPPORTED_INFERENCE_TASK_TYPES:
        raise InvalidRequestError(
            "当前仅支持已接入在线推理的任务类型",
            details={
                "task_type": value,
                "supported_task_types": list(SUPPORTED_INFERENCE_TASK_TYPES),
            },
        )
    return normalized


@dataclass(frozen=True)
class SaveDirectInferenceRecordCommand:
    """显式保存一次同步推理结果所需的输入参数。

    字段：
    - project_id：所属 Project id。
    - request_id：客户端/服务端关联的唯一请求标识。
    - task_type：任务类型。
    - deployment_instance_id：执行推理的部署实例 id。
    - result_payload：完整的同步推理响应 JSON。
    - input_label：可选输入名称。
    - input_image_bytes：可选上传图片字节。
    - input_image_filename：可选上传图片文件名。
    - input_image_base64：可选 Base64 输入图片内容。
    - parameters：推理参数快照。
    - created_by：创建主体 id。
    """

    project_id: str
    request_id: str
    task_type: str
    deployment_instance_id: str
    result_payload: dict[str, object]
    input_label: str = ""
    input_image_bytes: bytes | None = None
    input_image_filename: str | None = None
    input_image_base64: str | None = None
    parameters: dict[str, object] | None = None
    created_by: str | None = None


class SqlAlchemyDirectInferenceRecordService:
    """管理同步推理显式保存记录的落盘、查询、回看与清理。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化同步保存记录服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.project_mutations = ProjectMutationAdmissionService(session_factory)
        self.deployments = SqlAlchemyDeploymentInstanceService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """打开并在退出时关闭 Unit of Work。"""

        uow = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield uow
        finally:
            uow.close()

    def save_record(self, command: SaveDirectInferenceRecordCommand) -> DirectInferenceRecord:
        """显式保存一次同步推理结果；同 Project 同 request_id 幂等返回已有记录。"""

        task_type = normalize_inference_task_type(command.task_type)
        request_id = command.request_id.strip()
        if not request_id:
            raise InvalidRequestError("request_id 不能为空")

        with self._open_unit_of_work() as uow:
            existing = uow.direct_inference_records.get_by_request_id(
                command.project_id,
                request_id,
            )
            if existing is not None:
                uow.session.expunge(existing)
                return existing

        deployment_display_name = ""
        model_version_id = _read_optional_str(command.result_payload, "model_version_id")
        model_build_id = _read_optional_str(command.result_payload, "model_build_id")
        try:
            deployment = self.deployments.get_visible_deployment_instance(
                command.deployment_instance_id,
                visible_project_ids=(command.project_id,),
            )
            deployment_display_name = deployment.display_name
            if not model_version_id:
                model_version_id = deployment.model_version_id
            if not model_build_id:
                model_build_id = deployment.model_build_id
        except ResourceNotFoundError:
            deployment_display_name = ""

        record_id = f"direct-record-{uuid4().hex}"
        output_prefix = f"projects/{command.project_id}/results/direct-inference/{record_id}"
        result_object_key = f"{output_prefix}/raw-result.json"

        input_source_kind = (
            _read_optional_str(command.result_payload, "input_source_kind") or "unknown"
        )
        input_uri = _read_optional_str(command.result_payload, "input_uri")
        input_file_id = _read_optional_str(command.result_payload, "input_file_id")

        input_image_object_key: str | None = None
        raw_input_bytes, input_suffix = self._extract_input_image_bytes(
            upload_bytes=command.input_image_bytes,
            upload_filename=command.input_image_filename,
            image_base64=command.input_image_base64,
        )
        if raw_input_bytes is not None:
            input_image_object_key = f"{output_prefix}/input{input_suffix}"
            self.dataset_storage.write_bytes(input_image_object_key, raw_input_bytes)
        elif input_file_id:
            try:
                file_ref = resolve_public_project_file_reference(
                    dataset_storage=self.dataset_storage,
                    file_id=input_file_id,
                    expected_project_id=command.project_id,
                )
                input_image_object_key = file_ref.object_key
            except InvalidRequestError:
                input_image_object_key = None
        elif input_uri and is_public_project_object_key(
            project_id=command.project_id,
            object_key=input_uri,
        ):
            if self.dataset_storage.resolve(input_uri).is_file():
                input_image_object_key = input_uri

        preview_image_object_key: str | None = None
        preview_bytes = self._extract_preview_image_bytes(command.result_payload)
        if preview_bytes is not None:
            preview_image_object_key = f"{output_prefix}/preview.jpg"
            self.dataset_storage.write_bytes(preview_image_object_key, preview_bytes)

        persisted_payload = dict(command.result_payload)
        persisted_payload.pop("preview_image_base64", None)
        persisted_payload["result_object_key"] = result_object_key
        if preview_image_object_key is not None:
            persisted_payload["preview_image_uri"] = preview_image_object_key
        self.dataset_storage.write_json(result_object_key, persisted_payload)

        item_count = compute_result_item_count(task_type, persisted_payload)
        latency_ms = _read_optional_float(persisted_payload, "latency_ms")
        image_width = _read_optional_int(persisted_payload, "image_width")
        image_height = _read_optional_int(persisted_payload, "image_height")
        input_label = (
            command.input_label.strip()
            or (command.input_image_filename or "").strip()
            or _infer_input_label(input_uri, input_file_id, input_source_kind)
        )
        summary = build_result_summary(task_type, persisted_payload)

        record = DirectInferenceRecord(
            record_id=record_id,
            project_id=command.project_id,
            request_id=request_id,
            task_type=task_type,
            deployment_instance_id=command.deployment_instance_id,
            deployment_display_name=deployment_display_name,
            model_version_id=model_version_id,
            model_build_id=model_build_id,
            input_source_kind=input_source_kind,
            input_label=input_label,
            input_uri=input_uri,
            input_file_id=input_file_id,
            input_image_object_key=input_image_object_key,
            preview_image_object_key=preview_image_object_key,
            result_object_key=result_object_key,
            output_object_prefix=output_prefix,
            item_count=item_count,
            latency_ms=latency_ms,
            image_width=image_width,
            image_height=image_height,
            parameters_json=dict(command.parameters or {}),
            result_summary_json=summary,
            created_by=command.created_by,
            created_at=_now_isoformat(),
        )

        try:
            with self.project_mutations.operation(
                project_id=command.project_id,
                mutation_kind="direct-inference-record-save",
                resource_id=record_id,
            ):
                with self._open_unit_of_work() as uow:
                    existing = uow.direct_inference_records.get_by_request_id(
                        command.project_id,
                        request_id,
                    )
                    if existing is not None:
                        self._safe_cleanup_tree(output_prefix)
                        uow.session.expunge(existing)
                        return existing
                    uow.direct_inference_records.add(record)
                    uow.commit()
                    uow.session.refresh(record)
                    uow.session.expunge(record)
                    return record
        except IntegrityError:
            self._safe_cleanup_tree(output_prefix)
            with self._open_unit_of_work() as uow:
                existing = uow.direct_inference_records.get_by_request_id(
                    command.project_id,
                    request_id,
                )
                if existing is not None:
                    uow.session.expunge(existing)
                    return existing
            raise
        except Exception:
            self._safe_cleanup_tree(output_prefix)
            raise

    def list_records(
        self,
        *,
        project_id: str,
        task_type: str | None = None,
        deployment_instance_id: str | None = None,
        request_id: str | None = None,
        q: str | None = None,
    ) -> list[DirectInferenceRecord]:
        """按 Project 和公开过滤条件查询已保存同步推理记录。"""

        normalized_task_type = (
            normalize_inference_task_type(task_type) if task_type else None
        )
        with self._open_unit_of_work() as uow:
            rows = uow.direct_inference_records.list(
                project_id,
                task_type=normalized_task_type,
                deployment_instance_id=deployment_instance_id,
                request_id=request_id,
                q=q,
            )
            for row in rows:
                uow.session.expunge(row)
            return rows

    def get_record(
        self,
        record_id: str,
        *,
        visible_project_ids: tuple[str, ...] = (),
    ) -> DirectInferenceRecord:
        """读取并校验指定同步保存记录的访问权限。"""

        with self._open_unit_of_work() as uow:
            record = uow.direct_inference_records.get(record_id)
            if record is not None:
                uow.session.expunge(record)
        if record is None:
            raise ResourceNotFoundError(
                "找不到指定的同步推理保存记录",
                details={"record_id": record_id},
            )
        if visible_project_ids and record.project_id not in visible_project_ids:
            raise ResourceNotFoundError(
                "找不到指定的同步推理保存记录",
                details={"record_id": record_id},
            )
        return record

    def read_record_payload(self, record: DirectInferenceRecord) -> tuple[str, dict[str, object]]:
        """从本地存储读取保存的结果 JSON；文件缺失时返回 missing 状态。"""

        path = self.dataset_storage.resolve(record.result_object_key)
        if not path.is_file():
            return "missing", {}
        payload = self.dataset_storage.read_json(record.result_object_key)
        if not isinstance(payload, dict):
            return "missing", {}
        return "ready", payload

    def resolve_record_image_path(
        self,
        record: DirectInferenceRecord,
        *,
        kind: str,
    ) -> tuple[str, Path]:
        """安全解析同步保存记录的输入图或预览图本地路径。"""

        object_key = (
            record.preview_image_object_key
            if kind == "preview"
            else record.input_image_object_key
        )
        if not object_key and kind == "input" and record.input_file_id:
            try:
                object_key = resolve_public_project_file_reference(
                    dataset_storage=self.dataset_storage,
                    file_id=record.input_file_id,
                    expected_project_id=record.project_id,
                ).object_key
            except InvalidRequestError:
                object_key = None
        if not object_key:
            raise ResourceNotFoundError(
                "当前记录不包含可读取的图片文件",
                details={"record_id": record.record_id, "kind": kind},
            )
        root = self.dataset_storage.resolve(f"projects/{record.project_id}").resolve()
        candidate = self.dataset_storage.resolve(object_key).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ResourceNotFoundError(
                "记录关联的图片文件不存在或已移除",
                details={"record_id": record.record_id, "kind": kind, "object_key": object_key},
            )
        return object_key, candidate

    def delete_record(
        self,
        record_id: str,
        *,
        visible_project_ids: tuple[str, ...] = (),
    ) -> None:
        """同步清理记录产物后删除数据库记录；文件清理失败时保留数据库行以便重试。"""

        record = self.get_record(record_id, visible_project_ids=visible_project_ids)
        try:
            self.dataset_storage.delete_tree(record.output_object_prefix)
        except OSError as error:
            raise PersistenceOperationError(
                "清理同步推理产物文件失败，记录已保留；请解除文件占用后重试删除",
                details={"record_id": record_id, "error": str(error)},
            ) from error
        with self.project_mutations.operation(
            project_id=record.project_id,
            mutation_kind="direct-inference-record-delete",
            resource_id=record_id,
        ):
            with self._open_unit_of_work() as uow:
                current = uow.direct_inference_records.get(record_id)
                if current is not None:
                    uow.direct_inference_records.delete(current)
                    uow.commit()

    def _safe_cleanup_tree(self, object_prefix: str) -> None:
        """异常回滚时尽量清理已写入的临时目录。"""

        try:
            self.dataset_storage.delete_tree(object_prefix)
        except Exception:
            return

    @staticmethod
    def _extract_input_image_bytes(
        *,
        upload_bytes: bytes | None,
        upload_filename: str | None,
        image_base64: str | None,
    ) -> tuple[bytes | None, str]:
        """提取需要随记录持久化的输入图片字节。"""

        if upload_bytes:
            suffix = Path(upload_filename or "input.jpg").suffix.lower() or ".jpg"
            return upload_bytes, suffix
        if image_base64 and isinstance(image_base64, str):
            raw = image_base64.strip()
            suffix = ".jpg"
            if raw.startswith("data:"):
                header, _, body = raw.partition(",")
                raw = body
                if "png" in header.lower():
                    suffix = ".png"
                elif "webp" in header.lower():
                    suffix = ".webp"
                elif "bmp" in header.lower():
                    suffix = ".bmp"
            try:
                decoded = base64.b64decode("".join(raw.split()), validate=True)
                if decoded:
                    return decoded, suffix
            except (ValueError, binascii.Error):
                return None, ".jpg"
        return None, ".jpg"

    def _extract_preview_image_bytes(self, result_payload: dict[str, object]) -> bytes | None:
        """从预览图 base64 或同步临时输出键中提取预览图字节。"""

        b64_value = result_payload.get("preview_image_base64")
        if isinstance(b64_value, str) and b64_value.strip():
            raw = b64_value.strip()
            if raw.startswith("data:"):
                _, _, raw = raw.partition(",")
            try:
                decoded = base64.b64decode("".join(raw.split()), validate=True)
                if decoded:
                    return decoded
            except (ValueError, binascii.Error):
                pass
        preview_uri = result_payload.get("preview_image_uri")
        if isinstance(preview_uri, str) and preview_uri.strip():
            try:
                path = self.dataset_storage.resolve(preview_uri.strip())
                if path.is_file():
                    return path.read_bytes()
            except Exception:
                return None
        return None


def compute_result_item_count(task_type: str, payload: dict[str, object]) -> int:
    """按任务类型从推理结果载荷计算对象或分类数量。"""

    if task_type == "detection":
        count = _read_optional_int(payload, "detection_count")
        if count is not None:
            return count
        items = payload.get("detections")
        return len(items) if isinstance(items, list) else 0
    if task_type == "classification":
        count = _read_optional_int(payload, "category_count")
        if count is not None:
            return count
        items = payload.get("categories")
        return len(items) if isinstance(items, list) else 0
    count = _read_optional_int(payload, "instance_count")
    if count is not None:
        return count
    items = payload.get("instances")
    return len(items) if isinstance(items, list) else 0


def build_result_summary(task_type: str, payload: dict[str, object]) -> dict[str, object]:
    """为列表与回看卡片提炼精简结果摘要。"""

    item_count = compute_result_item_count(task_type, payload)
    summary: dict[str, object] = {
        "item_count": item_count,
        "image_width": _read_optional_int(payload, "image_width"),
        "image_height": _read_optional_int(payload, "image_height"),
        "latency_ms": _read_optional_float(payload, "latency_ms"),
    }
    if task_type == "classification":
        top = payload.get("top_category")
        if isinstance(top, dict):
            summary["top_label"] = top.get("class_name") or f"class_{top.get('class_id', 0)}"
            summary["top_score"] = top.get("probability")
    else:
        raw_items = payload.get("detections") if task_type == "detection" else payload.get("instances")
        class_counts: dict[str, int] = {}
        if isinstance(raw_items, list):
            for entry in raw_items:
                if not isinstance(entry, dict):
                    continue
                label = str(entry.get("class_name") or f"class_{entry.get('class_id', 0)}")
                class_counts[label] = class_counts.get(label, 0) + 1
        summary["class_counts"] = class_counts
    return summary


def _infer_input_label(
    input_uri: str | None,
    input_file_id: str | None,
    input_source_kind: str,
) -> str:
    """构造无文件名时兜底的输入显示名称。"""

    if input_uri:
        normalized = input_uri.replace("\\", "/").rstrip("/")
        if "/" in normalized:
            return normalized.rsplit("/", 1)[-1]
        return normalized
    if input_file_id:
        return input_file_id[:32]
    return input_source_kind or "同步推理图像"


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _read_optional_float(payload: dict[str, object], key: str) -> float | None:
    value = payload.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
