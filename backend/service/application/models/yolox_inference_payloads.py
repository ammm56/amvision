"""YOLOX 推理输入归一化与结果载荷定义。"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

if TYPE_CHECKING:
    from backend.service.application.models.yolox_inference_task_service import YoloXInferenceExecutionResult


YOLOX_INFERENCE_INPUT_SOURCE_URI = "input_uri"
YOLOX_INFERENCE_INPUT_SOURCE_BASE64 = "image_base64"
YOLOX_INFERENCE_INPUT_SOURCE_MULTIPART = "multipart"


@dataclass(frozen=True)
class YoloXInferenceInputSource:
    """描述一次推理请求提供的原始输入源。

    字段：
    - input_uri：本地 object key 或输入 URI。
    - image_base64：JSON 中直接提供的 base64 图片内容。
    - upload_bytes：multipart 上传的原始二进制内容。
    - upload_filename：multipart 上传文件名。
    - upload_content_type：multipart 上传 content-type。
    """

    input_uri: str | None = None
    image_base64: str | None = None
    upload_bytes: bytes | None = None
    upload_filename: str | None = None
    upload_content_type: str | None = None


@dataclass(frozen=True)
class YoloXNormalizedInferenceInput:
    """描述完成 one-of 归一化后的推理输入。

    字段：
    - input_uri：归一化后可直接读取的输入 URI。
    - input_source_kind：输入来源类型。
    - input_file_id：平台文件 id；当前固定为空。
    """

    input_uri: str
    input_source_kind: str
    input_file_id: str | None = None


@dataclass(frozen=True)
class YoloXInferencePayload:
    """描述同步直返与异步结果共用的推理结果载荷。

    字段：
    - request_id：统一请求 id；异步场景与 task_id 相同。
    - inference_task_id：异步推理任务 id；同步场景为空。
    - deployment_instance_id：DeploymentInstance id。
    - instance_id：实际执行的推理实例 id。
    - model_version_id：推理使用的 ModelVersion id。
    - model_build_id：推理使用的 ModelBuild id。
    - input_uri：归一化后的输入 URI。
    - input_source_kind：输入来源类型。
    - input_file_id：平台文件 id；当前固定为空。
    - score_threshold：本次推理阈值。
    - save_result_image：是否保存结果图。
    - return_preview_image_base64：是否回传 base64 预览图。
    - image_width：输入图片宽度。
    - image_height：输入图片高度。
    - detection_count：检测框数量。
    - latency_ms：推理耗时。
    - labels：类别列表。
    - detections：检测结果。
    - runtime_session_info：运行时会话信息。
    - preview_image_uri：预览图 object key 或 URI。
    - preview_image_base64：预览图 base64 内容。
    - result_object_key：异步结果文件 object key。
    """

    request_id: str
    inference_task_id: str | None
    deployment_instance_id: str
    instance_id: str | None
    model_version_id: str
    model_build_id: str | None
    input_uri: str
    input_source_kind: str
    input_file_id: str | None
    score_threshold: float
    save_result_image: bool
    return_preview_image_base64: bool
    image_width: int
    image_height: int
    detection_count: int
    latency_ms: float | None
    labels: tuple[str, ...]
    detections: tuple[dict[str, object], ...]
    runtime_session_info: dict[str, object]
    preview_image_uri: str | None = None
    preview_image_base64: str | None = None
    result_object_key: str | None = None


def normalize_yolox_inference_input(
    *,
    dataset_storage: LocalDatasetStorage,
    request_id: str,
    source: YoloXInferenceInputSource,
) -> YoloXNormalizedInferenceInput:
    """按 one-of 规则把推理输入归一化为可直接读取的 input_uri。

    参数：
    - dataset_storage：本地文件存储服务。
    - request_id：当前请求 id。
    - source：原始输入源。

    返回：
    - YoloXNormalizedInferenceInput：归一化后的输入信息。
    """

    normalized_input_uri = source.input_uri.strip() if isinstance(source.input_uri, str) and source.input_uri.strip() else None
    normalized_base64 = source.image_base64.strip() if isinstance(source.image_base64, str) and source.image_base64.strip() else None
    upload_bytes = source.upload_bytes if isinstance(source.upload_bytes, bytes) and source.upload_bytes else None
    provided_count = sum(
        1
        for item in (normalized_input_uri, normalized_base64, upload_bytes)
        if item is not None
    )
    if provided_count != 1:
        raise InvalidRequestError(
            "input_uri、image_base64、multipart 文件三者必须且只能提供一个",
            details={
                "provided_input_uri": normalized_input_uri is not None,
                "provided_image_base64": normalized_base64 is not None,
                "provided_multipart_file": upload_bytes is not None,
            },
        )

    if normalized_input_uri is not None:
        resolved_path = dataset_storage.resolve(normalized_input_uri)
        if not resolved_path.is_file():
            raise InvalidRequestError(
                "input_uri 对应的本地文件不存在",
                details={"input_uri": normalized_input_uri},
            )
        return YoloXNormalizedInferenceInput(
            input_uri=normalized_input_uri,
            input_source_kind=YOLOX_INFERENCE_INPUT_SOURCE_URI,
        )

    if normalized_base64 is not None:
        image_bytes, suffix = _decode_image_base64(normalized_base64)
        input_uri = f"runtime/inference-inputs/{request_id}/input{suffix}"
        dataset_storage.write_bytes(input_uri, image_bytes)
        return YoloXNormalizedInferenceInput(
            input_uri=input_uri,
            input_source_kind=YOLOX_INFERENCE_INPUT_SOURCE_BASE64,
        )

    suffix = _infer_suffix_from_upload(
        upload_filename=source.upload_filename,
        upload_content_type=source.upload_content_type,
    )
    normalized_upload_bytes = upload_bytes or b""
    _validate_image_bytes(image_bytes=normalized_upload_bytes, field_name="input_image")
    input_uri = f"runtime/inference-inputs/{request_id}/input{suffix}"
    dataset_storage.write_bytes(input_uri, normalized_upload_bytes)
    return YoloXNormalizedInferenceInput(
        input_uri=input_uri,
        input_source_kind=YOLOX_INFERENCE_INPUT_SOURCE_MULTIPART,
    )


def build_yolox_inference_payload(
    *,
    request_id: str,
    inference_task_id: str | None,
    deployment_instance_id: str,
    instance_id: str | None,
    runtime_target: RuntimeTargetSnapshot,
    normalized_input: YoloXNormalizedInferenceInput,
    score_threshold: float,
    save_result_image: bool,
    return_preview_image_base64: bool,
    execution_result: YoloXInferenceExecutionResult,
    preview_image_uri: str | None,
    result_object_key: str | None,
) -> YoloXInferencePayload:
    """构建同步直返与异步结果共用的标准载荷。"""

    preview_image_base64 = None
    if return_preview_image_base64 and execution_result.preview_image_bytes is not None:
        preview_image_base64 = base64.b64encode(execution_result.preview_image_bytes).decode("ascii")
    return YoloXInferencePayload(
        request_id=request_id,
        inference_task_id=inference_task_id,
        deployment_instance_id=deployment_instance_id,
        instance_id=instance_id,
        model_version_id=runtime_target.model_version_id,
        model_build_id=runtime_target.model_build_id,
        input_uri=normalized_input.input_uri,
        input_source_kind=normalized_input.input_source_kind,
        input_file_id=normalized_input.input_file_id,
        score_threshold=score_threshold,
        save_result_image=save_result_image,
        return_preview_image_base64=return_preview_image_base64,
        image_width=execution_result.image_width,
        image_height=execution_result.image_height,
        detection_count=len(execution_result.detections),
        latency_ms=execution_result.latency_ms,
        labels=runtime_target.labels,
        detections=execution_result.detections,
        runtime_session_info=execution_result.runtime_session_info,
        preview_image_uri=preview_image_uri,
        preview_image_base64=preview_image_base64,
        result_object_key=result_object_key,
    )


def serialize_yolox_inference_payload(payload: YoloXInferencePayload) -> dict[str, object]:
    """把统一推理结果载荷序列化为 JSON 字典。"""

    return {
        "request_id": payload.request_id,
        "inference_task_id": payload.inference_task_id,
        "deployment_instance_id": payload.deployment_instance_id,
        "instance_id": payload.instance_id,
        "model_version_id": payload.model_version_id,
        "model_build_id": payload.model_build_id,
        "input_uri": payload.input_uri,
        "input_source_kind": payload.input_source_kind,
        "input_file_id": payload.input_file_id,
        "score_threshold": payload.score_threshold,
        "save_result_image": payload.save_result_image,
        "return_preview_image_base64": payload.return_preview_image_base64,
        "image_width": payload.image_width,
        "image_height": payload.image_height,
        "detection_count": payload.detection_count,
        "latency_ms": payload.latency_ms,
        "labels": list(payload.labels),
        "detections": [dict(item) for item in payload.detections],
        "runtime_session_info": dict(payload.runtime_session_info),
        "preview_image_uri": payload.preview_image_uri,
        "preview_image_base64": payload.preview_image_base64,
        "result_object_key": payload.result_object_key,
    }


def _decode_image_base64(value: str) -> tuple[bytes, str]:
    """解析可能带 data URI 前缀的图片 base64，并验证图片内容可读。

    参数：
    - value：请求中提交的 base64 字符串。

    返回：
    - tuple[bytes, str]：解码后的图片字节和推断出的文件后缀。
    """

    raw_value = value
    suffix = ".jpg"
    if value.startswith("data:"):
        header, _, body = value.partition(",")
        if not body:
            raise InvalidRequestError("image_base64 缺少有效的 base64 内容")
        raw_value = body
        suffix = _infer_suffix_from_data_uri(header)
    normalized_value = "".join(raw_value.split())
    if not normalized_value:
        raise InvalidRequestError("image_base64 缺少有效的 base64 内容")
    try:
        image_bytes = base64.b64decode(normalized_value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise InvalidRequestError("image_base64 不是合法的 base64 图片内容") from error
    _validate_image_bytes(image_bytes=image_bytes, field_name="image_base64")
    return image_bytes, suffix


def _validate_image_bytes(*, image_bytes: bytes, field_name: str) -> None:
    """校验原始图片字节是否可以被 OpenCV 正常读取。

    参数：
    - image_bytes：待校验的原始图片字节。
    - field_name：当前输入字段名称。
    """

    if not image_bytes:
        raise InvalidRequestError(
            f"{field_name} 缺少有效图片内容",
            details={"field": field_name},
        )
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except Exception:
        return
    buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise InvalidRequestError(
            f"{field_name} 不是可读取的图片内容",
            details={"field": field_name},
        )


def _infer_suffix_from_data_uri(header: str) -> str:
    """从 data URI 头部推断文件后缀。"""

    if "image/png" in header:
        return ".png"
    if "image/webp" in header:
        return ".webp"
    if "image/bmp" in header:
        return ".bmp"
    return ".jpg"


def _infer_suffix_from_upload(*, upload_filename: str | None, upload_content_type: str | None) -> str:
    """从上传文件名或 content-type 推断图片后缀。"""

    if isinstance(upload_filename, str) and upload_filename.strip():
        suffix = Path(upload_filename.strip()).suffix.lower()
        if suffix:
            return suffix
    content_type = upload_content_type.strip().lower() if isinstance(upload_content_type, str) else ""
    if content_type == "image/png":
        return ".png"
    if content_type == "image/webp":
        return ".webp"
    if content_type == "image/bmp":
        return ".bmp"
    return ".jpg"