"""生成模型任务 E2E 使用的确定性最小数据集压缩包。

资产由代码生成到 ``.tmp/model-task-e2e-assets``，不依赖被 ``/data`` 忽略的
本机开发数据。每个压缩包都覆盖 train/val/test，并保留真实导入器要求的目录、
manifest 和标注格式。
"""

from __future__ import annotations

import binascii
import json
import struct
import uuid
import zipfile
import zlib
from pathlib import Path
from typing import Final

from backend.service.infrastructure.filesystem.atomic_files import (
    replace_path_with_retry,
)


PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
E2E_ASSET_SCHEMA_VERSION: Final = 1
E2E_ASSET_ROOT: Final = (
    PROJECT_ROOT / ".tmp" / "model-task-e2e-assets" / f"v{E2E_ASSET_SCHEMA_VERSION}"
)
TASK_TYPES: Final = ("detection", "classification", "segmentation", "pose", "obb")


def ensure_model_task_e2e_archives() -> dict[str, Path]:
    """生成或复用五类模型任务的确定性最小数据集压缩包。"""

    E2E_ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    archives: dict[str, Path] = {}
    for task_type in TASK_TYPES:
        archive_path = E2E_ASSET_ROOT / f"{task_type}-minimal-v1.zip"
        if not _is_current_archive(archive_path=archive_path, task_type=task_type):
            _write_archive_atomically(archive_path=archive_path, task_type=task_type)
        archives[task_type] = archive_path
    return archives


def _write_archive_atomically(*, archive_path: Path, task_type: str) -> None:
    """先完整生成 zip，再原子替换公开资产路径。"""

    temporary_path = archive_path.with_name(
        f".{archive_path.name}.{uuid.uuid4().hex[:12]}.tmp"
    )
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for member_name, content in _build_archive_members(task_type).items():
                _write_member(archive=archive, member_name=member_name, content=content)
        replace_path_with_retry(temporary_path, archive_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _is_current_archive(*, archive_path: Path, task_type: str) -> bool:
    """检查已有资产是否完整并属于当前 schema。"""

    if not archive_path.is_file():
        return False
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            if archive.testzip() is not None:
                return False
            manifest = json.loads(
                archive.read(f"amvision-e2e-{task_type}/fixture-manifest.json")
            )
            return manifest == {
                "schema_version": E2E_ASSET_SCHEMA_VERSION,
                "task_type": task_type,
            }
    except (KeyError, OSError, ValueError, zipfile.BadZipFile):
        return False


def _build_archive_members(task_type: str) -> dict[str, bytes]:
    """按 task_type 构造 zip 内文件。"""

    root = f"amvision-e2e-{task_type}"
    image_by_split = {
        "train": _build_png_bytes(color=(62, 138, 214)),
        "val": _build_png_bytes(color=(78, 176, 124)),
        "test": _build_png_bytes(color=(218, 142, 70)),
    }
    members: dict[str, bytes] = {
        f"{root}/fixture-manifest.json": (
            json.dumps(
                {
                    "schema_version": E2E_ASSET_SCHEMA_VERSION,
                    "task_type": task_type,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        ).encode(),
    }
    if task_type == "classification":
        for split, image_bytes in image_by_split.items():
            members[f"{root}/{split}/ok/{split}-ok.png"] = image_bytes
            members[f"{root}/{split}/ng/{split}-ng.png"] = _build_png_bytes(
                color=(190, 72, 82)
            )
        return members

    members[f"{root}/data.yaml"] = _build_yolo_yaml(task_type).encode()
    labels = {
        "detection": "0 0.5 0.5 0.5 0.5\n",
        "segmentation": "0 0.2 0.2 0.8 0.2 0.8 0.8 0.2 0.8\n",
        "pose": "0 0.5 0.5 0.6 0.6 0.35 0.4 2 0.65 0.6 2\n",
        "obb": "0 0.25 0.35 0.65 0.25 0.75 0.65 0.35 0.75\n",
    }
    for split, image_bytes in image_by_split.items():
        members[f"{root}/images/{split}/{split}-sample.png"] = image_bytes
        members[f"{root}/labels/{split}/{split}-sample.txt"] = labels[
            task_type
        ].encode()
    return members


def _build_yolo_yaml(task_type: str) -> str:
    """构造 detection/segmentation/pose/obb 共用的 YOLO manifest。"""

    lines = [
        "path: .",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        "names:",
        "  0: target",
    ]
    if task_type == "pose":
        lines.extend(("kpt_shape: [2, 3]", "flip_idx: [1, 0]"))
    return "\n".join(lines) + "\n"


def _build_png_bytes(
    *,
    width: int = 96,
    height: int = 64,
    color: tuple[int, int, int],
) -> bytes:
    """只用标准库构造一张确定性 RGB PNG 图片。"""

    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(color) * width
    image_data = zlib.compress(row * height, level=9)
    return (
        signature
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", image_data)
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(chunk_type: bytes, content: bytes) -> bytes:
    """序列化一个 PNG chunk。"""

    checksum = binascii.crc32(chunk_type + content) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(content))
        + chunk_type
        + content
        + struct.pack(">I", checksum)
    )


def _write_member(
    *,
    archive: zipfile.ZipFile,
    member_name: str,
    content: bytes,
) -> None:
    """用固定元数据写入 zip member，避免运行时间影响资产摘要。"""

    member = zipfile.ZipInfo(member_name, date_time=(2026, 1, 1, 0, 0, 0))
    member.compress_type = zipfile.ZIP_DEFLATED
    member.external_attr = 0o100644 << 16
    archive.writestr(member, content)
