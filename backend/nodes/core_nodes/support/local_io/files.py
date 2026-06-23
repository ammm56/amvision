"""本地文件记录与图片读取 helper。"""

from __future__ import annotations

from datetime import UTC, datetime
import io
from pathlib import Path

from PIL import Image

from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.nodes.runtime_support import infer_media_type, infer_media_type_from_image_bytes
from backend.service.application.errors import InvalidRequestError


def build_local_file_summary(
    *,
    local_path: Path,
    extra_fields: dict[str, object] | None = None,
) -> dict[str, object]:
    """构造本地文件输出摘要。"""

    summary: dict[str, object] = {
        "local_path": str(local_path),
        "file_name": local_path.name,
    }
    if local_path.exists():
        stat_result = local_path.stat()
        summary["size_bytes"] = stat_result.st_size
        summary["modified_time_iso"] = _build_iso_timestamp(stat_result.st_mtime)
    if extra_fields:
        summary.update(extra_fields)
    return build_value_payload(summary)


def build_directory_file_record(file_path: Path) -> dict[str, object]:
    """把文件路径规范化为目录扫描记录。"""

    stat_result = file_path.stat()
    return {
        "path": str(file_path),
        "file_name": file_path.name,
        "extension": file_path.suffix.lower(),
        "size_bytes": stat_result.st_size,
        "modified_time_epoch_ms": int(round(stat_result.st_mtime * 1000)),
        "modified_time_iso": _build_iso_timestamp(stat_result.st_mtime),
    }


def require_file_record_list(
    payload: object,
    *,
    field_name: str,
    node_id: str,
) -> list[dict[str, object]]:
    """读取并规范化文件记录列表。"""

    raw_items = require_value_payload(payload, field_name=field_name)["value"]
    if not isinstance(raw_items, list):
        raise InvalidRequestError(
            f"{field_name} payload 中的 value 必须是数组",
            details={"node_id": node_id, "field_name": field_name},
        )
    normalized_records: list[dict[str, object]] = []
    for item_index, raw_item in enumerate(raw_items, start=1):
        if isinstance(raw_item, str) and raw_item.strip():
            file_path = Path(raw_item.strip()).expanduser().resolve()
            normalized_records.append({"path": str(file_path), "file_name": file_path.name})
            continue
        if isinstance(raw_item, dict):
            raw_path = raw_item.get("path")
            if isinstance(raw_path, str) and raw_path.strip():
                file_path = Path(raw_path.strip()).expanduser().resolve()
                normalized_record = dict(raw_item)
                normalized_record["path"] = str(file_path)
                normalized_record.setdefault("file_name", file_path.name)
                normalized_record.setdefault("extension", file_path.suffix.lower())
                normalized_records.append(normalized_record)
                continue
        raise InvalidRequestError(
            f"{field_name} 数组项必须是路径字符串或包含 path 的对象",
            details={"node_id": node_id, "field_name": field_name, "item_index": item_index},
        )
    return normalized_records


def read_local_image_file(file_path: Path) -> tuple[bytes, str, int, int]:
    """读取本地图像文件并返回字节、媒体类型和尺寸。"""

    image_bytes = file_path.read_bytes()
    if not image_bytes:
        raise InvalidRequestError(
            "本地图像文件不能为空",
            details={"local_path": str(file_path)},
        )
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
    except Exception as exc:  # noqa: BLE001
        raise InvalidRequestError(
            "本地图像文件不是有效图片",
            details={"local_path": str(file_path)},
        ) from exc
    if width <= 0 or height <= 0:
        raise InvalidRequestError(
            "本地图像文件宽高无效",
            details={"local_path": str(file_path)},
        )
    media_type = infer_media_type_from_image_bytes(image_bytes)
    if media_type == "image/png":
        media_type = infer_media_type(file_path.name)
    return image_bytes, media_type, width, height


def _build_iso_timestamp(timestamp_seconds: float) -> str:
    """把时间戳转换为 UTC ISO 文本。"""

    return datetime.fromtimestamp(timestamp_seconds, tz=UTC).isoformat()
