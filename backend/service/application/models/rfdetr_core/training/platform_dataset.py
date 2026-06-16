"""RF-DETR 平台训练数据准备。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.models.model_task_types import (
    ModelTaskType,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class RfdetrPreparedDataset:
    """已经整理成 RF-DETR Roboflow COCO 目录的数据集。"""

    dataset_dir: Path
    labels: tuple[str, ...]


_SPLIT_NAME_MAP: dict[str, str] = {
    "train": "train",
    "training": "train",
    "val": "valid",
    "valid": "valid",
    "validation": "valid",
    "test": "test",
}


def prepare_roboflow_coco_dataset(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
    dataset_dir: Path,
    task_type: ModelTaskType,
) -> RfdetrPreparedDataset:
    """把平台 DatasetExport manifest 整理成 RF-DETR 训练读取目录。"""

    split_payloads = _read_manifest_splits(manifest_payload)
    category_names_by_id: dict[int, str] = {}
    prepared_splits: dict[str, dict[str, object]] = {}

    for split_payload in split_payloads:
        split_name = _normalize_split_name(split_payload.get("name"))
        if split_name is None:
            continue
        annotation_key = str(split_payload.get("annotation_file") or "").strip()
        image_root = str(split_payload.get("image_root") or "").strip()
        if not annotation_key or not image_root:
            continue

        annotation_payload = dataset_storage.read_json(annotation_key)
        if not isinstance(annotation_payload, dict):
            continue
        prepared_payload = _copy_coco_split(
            dataset_storage=dataset_storage,
            annotation_payload=annotation_payload,
            image_root=image_root,
            target_split_dir=dataset_dir / split_name,
            task_type=task_type,
        )
        prepared_splits[split_name] = prepared_payload
        for category in prepared_payload.get("categories", []):
            if isinstance(category, dict):
                category_names_by_id[int(category.get("id", -1))] = str(
                    category.get("name", "")
                )

    if "train" not in prepared_splits:
        raise InvalidRequestError("RF-DETR 训练数据缺少 train split")
    if "valid" not in prepared_splits:
        prepared_splits["valid"] = json.loads(json.dumps(prepared_splits["train"]))
        _copy_split_directory(dataset_dir / "train", dataset_dir / "valid")

    for split_name, prepared_payload in prepared_splits.items():
        split_dir = dataset_dir / split_name
        split_dir.mkdir(parents=True, exist_ok=True)
        (split_dir / "_annotations.coco.json").write_text(
            json.dumps(prepared_payload, ensure_ascii=False),
            encoding="utf-8",
        )

    labels = tuple(
        category_name
        for _, category_name in sorted(category_names_by_id.items())
        if category_name
    )
    if not labels:
        raise InvalidRequestError("RF-DETR 训练数据缺少类别")
    return RfdetrPreparedDataset(dataset_dir=dataset_dir, labels=labels)


def _read_manifest_splits(manifest_payload: dict[str, object]) -> list[dict[str, object]]:
    """读取 DatasetExport manifest 中的 split 列表。"""

    raw_splits = manifest_payload.get("splits")
    if not isinstance(raw_splits, list):
        raise InvalidRequestError("DatasetExport manifest 缺少 splits")
    return [item for item in raw_splits if isinstance(item, dict)]


def _copy_coco_split(
    *,
    dataset_storage: LocalDatasetStorage,
    annotation_payload: dict[str, object],
    image_root: str,
    target_split_dir: Path,
    task_type: ModelTaskType,
) -> dict[str, object]:
    """复制一个 COCO split 的图片，并过滤当前任务可训练的 annotation。"""

    target_split_dir.mkdir(parents=True, exist_ok=True)
    image_payloads = [
        image for image in annotation_payload.get("images", []) if isinstance(image, dict)
    ]
    image_ids = {int(image.get("id", -1)) for image in image_payloads}
    kept_annotations: list[dict[str, object]] = []

    for image_payload in image_payloads:
        file_name = _normalize_coco_file_name(image_payload.get("file_name"))
        source_path = _resolve_coco_source_image_path(
            dataset_storage=dataset_storage,
            image_root=image_root,
            file_name=file_name,
        )
        rfdetr_file_name = _build_rfdetr_roboflow_file_name(
            split_name=target_split_dir.name,
            file_name=file_name,
        )
        destination_path = target_split_dir / rfdetr_file_name
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        image_payload["file_name"] = rfdetr_file_name

    for annotation in annotation_payload.get("annotations", []):
        if not isinstance(annotation, dict):
            continue
        if int(annotation.get("image_id", -1)) not in image_ids:
            continue
        if task_type == SEGMENTATION_TASK_TYPE and not annotation.get("segmentation"):
            continue
        kept_annotations.append(annotation)

    return {
        "images": image_payloads,
        "annotations": kept_annotations,
        "categories": [
            category
            for category in annotation_payload.get("categories", [])
            if isinstance(category, dict)
        ],
    }


def _normalize_split_name(raw_name: object) -> str | None:
    """把平台 split 名称映射到 RF-DETR 训练目录名称。"""

    return _SPLIT_NAME_MAP.get(str(raw_name or "").strip().lower())


def _normalize_coco_file_name(raw_file_name: object) -> str:
    """清理 COCO file_name，避免空路径或绝对路径进入训练目录。"""

    file_name = PurePosixPath(str(raw_file_name or "").strip())
    normalized = PurePosixPath(*[part for part in file_name.parts if part not in {"", "/", "."}])
    if str(normalized) == ".":
        raise InvalidRequestError("COCO annotation 中存在空 file_name")
    return str(normalized)


def _resolve_coco_source_image_path(
    *,
    dataset_storage: LocalDatasetStorage,
    image_root: str,
    file_name: str,
) -> Path:
    """从 DatasetExport 中解析 COCO 图片源文件。"""

    normalized_file_name = PurePosixPath(file_name)
    candidate_keys = [
        str(PurePosixPath(image_root) / normalized_file_name),
    ]
    if len(normalized_file_name.parts) > 1:
        candidate_keys.append(str(PurePosixPath(image_root) / normalized_file_name.name))

    for candidate_key in dict.fromkeys(candidate_keys):
        source_path = dataset_storage.resolve(candidate_key)
        if source_path.is_file():
            return source_path

    raise InvalidRequestError(
        "RF-DETR 训练数据图片不存在",
        details={"candidates": candidate_keys},
    )


def _build_rfdetr_roboflow_file_name(*, split_name: str, file_name: str) -> str:
    """生成 RF-DETR Roboflow COCO 读取约定使用的 split 相对图片路径。"""

    normalized_file_name = PurePosixPath(file_name)
    parts = [
        part
        for part in normalized_file_name.parts
        if part not in {"", "/", "."}
    ]
    if parts and parts[0] == split_name:
        return str(PurePosixPath(*parts))
    return str(PurePosixPath(split_name) / normalized_file_name.name)


def _copy_split_directory(source_dir: Path, target_dir: Path) -> None:
    """复制已有 split 目录，用于缺少 valid split 时复用 train split。"""

    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
