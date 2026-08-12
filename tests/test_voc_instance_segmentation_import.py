"""VOC indexed-mask instance segmentation 导入回归测试。"""

from __future__ import annotations

from pathlib import Path
import shutil

import numpy as np
from PIL import Image
from pycocotools import mask as coco_mask
import pytest

from backend.contracts.datasets.dataset_formats import (
    VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    get_dataset_format_specification,
    resolve_dataset_format_id,
)
from backend.maintenance.voc_instance_segmentation_dataset import (
    prepare_voc_instance_segmentation_dataset,
)
from backend.service.application.datasets.imports.service import (
    SqlAlchemyDatasetImportService,
)
from backend.service.application.datasets.exports import (
    DatasetExportRequest,
    SqlAlchemyDatasetExporter,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
    InstanceSegmentationAnnotation,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.api_test_support import create_test_runtime


def test_voc_instance_segmentation_import_preserves_indexed_mask_as_rle(
    tmp_path: Path,
) -> None:
    """验证 mask 几何、类别、XML 元数据和 split 被无损统一。"""

    dataset_root = tmp_path / "VOCdevkit" / "VOC2012"
    _write_voc_segmentation_sample(dataset_root)
    service, session_factory = _build_service(tmp_path)
    try:
        content = service._parse_voc_instance_segmentation(
            dataset_root=tmp_path,
            split_strategy=None,
            requested_class_map={},
        )
    finally:
        session_factory.engine.dispose()

    assert content.task_type == "segmentation"
    assert content.split_strategy == "image_sets"
    assert content.validation_report["format_profile"] == (
        VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT
    )
    assert content.validation_report["mask_encoding"] == "coco-compressed-rle"
    assert content.categories[0].name == "aeroplane"
    assert len(content.samples) == 1
    sample = content.samples[0].sample
    assert sample.split == "train"
    assert sample.width == 6
    assert sample.height == 5
    annotation = sample.annotations[0]
    assert isinstance(annotation, InstanceSegmentationAnnotation)
    assert annotation.bbox_xywh == (1.0, 1.0, 3.0, 2.0)
    assert annotation.area == 6.0
    assert annotation.metadata["difficult"] == 1
    assert annotation.metadata["truncated"] == 0
    assert annotation.metadata["xml_bbox_iou"] == pytest.approx(1.0)
    decoded = coco_mask.decode(annotation.segmentation)
    assert decoded.shape == (5, 6)
    assert int(decoded.sum()) == 6


def test_voc_instance_segmentation_supports_class_id_mapping(tmp_path: Path) -> None:
    """验证按官方 mask 类别 id 映射时 XML 和 mask 使用相同语义。"""

    dataset_root = tmp_path / "VOC2012"
    _write_voc_segmentation_sample(dataset_root)
    service, session_factory = _build_service(tmp_path)
    try:
        content = service._parse_voc_instance_segmentation(
            dataset_root=dataset_root,
            split_strategy="val",
            requested_class_map={"1": "aircraft"},
        )
    finally:
        session_factory.engine.dispose()

    assert [category.name for category in content.categories] == ["aircraft"]
    assert content.samples[0].sample.split == "val"


def test_voc_instance_segmentation_reports_missing_xml(tmp_path: Path) -> None:
    """验证不完整的开发副本会返回可定位错误，而不是误判为其他格式。"""

    dataset_root = tmp_path / "VOC2012"
    _write_voc_segmentation_sample(dataset_root)
    (dataset_root / "Annotations" / "sample-1.xml").unlink()
    service, session_factory = _build_service(tmp_path)
    try:
        with pytest.raises(InvalidRequestError) as error_info:
            service._parse_voc_instance_segmentation(
                dataset_root=dataset_root,
                split_strategy=None,
                requested_class_map={},
            )
    finally:
        session_factory.engine.dispose()

    issues = error_info.value.details["issues"]
    assert issues[0]["code"] == "VOC_SEGMENTATION_FILE_MISSING"
    assert issues[0]["file"].endswith("Annotations/sample-1.xml")


def test_voc_instance_segmentation_format_is_registered_for_round_trip() -> None:
    """验证注册表开放 VOC instance segmentation 的完整导入导出。"""

    specification = get_dataset_format_specification(
        VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT
    )
    assert specification is not None
    assert specification.import_enabled is True
    assert specification.export_enabled is True
    assert (
        resolve_dataset_format_id(
            family="voc",
            task_type="segmentation",
            require_import=True,
        )
        == VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT
    )


def test_voc_instance_segmentation_export_round_trip(tmp_path: Path) -> None:
    """验证 canonical RLE 可导出 indexed PNG，并由 VOC 导入器无损读回。"""

    session_factory, dataset_storage, _queue_backend = create_test_runtime(
        tmp_path / "round-trip-runtime",
        database_name="voc-segmentation-round-trip.db",
    )
    binary_mask = np.zeros((5, 6), dtype=np.uint8)
    binary_mask[1:3, 1:4] = 1
    encoded = coco_mask.encode(np.asfortranarray(binary_mask))
    counts = encoded["counts"]
    assert isinstance(counts, bytes)
    dataset_version = DatasetVersion(
        dataset_version_id="dataset-version-voc-seg-round-trip",
        dataset_id="dataset-voc-seg-round-trip",
        project_id="project-1",
        task_type="segmentation",
        categories=(DatasetCategory(category_id=0, name="aeroplane"),),
        samples=(
            DatasetSample(
                sample_id="sample-voc-seg-round-trip",
                image_id=1,
                file_name="source.jpg",
                width=6,
                height=5,
                split="train",
                annotations=(
                    InstanceSegmentationAnnotation(
                        annotation_id="annotation-1",
                        category_id=0,
                        bbox_xywh=(1.0, 1.0, 3.0, 2.0),
                        segmentation={
                            "size": [5, 6],
                            "counts": counts.decode("ascii"),
                        },
                        area=6.0,
                    ),
                ),
                metadata={
                    "image_object_key": (
                        "images/train/sample-voc-seg-round-trip/source.jpg"
                    )
                },
            ),
        ),
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.datasets.save_dataset_version(dataset_version)
        unit_of_work.commit()
    finally:
        unit_of_work.close()
    dataset_storage.write_bytes(
        (
            "projects/project-1/datasets/dataset-voc-seg-round-trip/versions/"
            "dataset-version-voc-seg-round-trip/images/train/"
            "sample-voc-seg-round-trip/source.jpg"
        ),
        _build_jpeg_bytes(width=6, height=5),
    )
    exporter = SqlAlchemyDatasetExporter(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    try:
        result = exporter.export_dataset(
            DatasetExportRequest(
                project_id="project-1",
                dataset_id="dataset-voc-seg-round-trip",
                dataset_version_id="dataset-version-voc-seg-round-trip",
                format_id=VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT,
            )
        )
        assert result.export_path is not None
        export_root = dataset_storage.resolve(result.export_path)
        with Image.open(
            export_root / "SegmentationClass" / "sample-voc-seg-round-trip.png"
        ) as class_image:
            assert class_image.mode == "P"
            assert set(np.asarray(class_image).reshape(-1)) == {0, 1}
        with Image.open(
            export_root / "SegmentationObject" / "sample-voc-seg-round-trip.png"
        ) as object_image:
            assert set(np.asarray(object_image).reshape(-1)) == {0, 1}

        importer = SqlAlchemyDatasetImportService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )
        parsed = importer._parse_voc_instance_segmentation(
            dataset_root=export_root,
            split_strategy=None,
            requested_class_map={},
        )
        parsed_annotation = parsed.samples[0].sample.annotations[0]
        assert isinstance(parsed_annotation, InstanceSegmentationAnnotation)
        assert parsed_annotation.bbox_xywh == (1.0, 1.0, 3.0, 2.0)
        assert parsed_annotation.area == 6.0
    finally:
        session_factory.engine.dispose()


def test_voc_instance_segmentation_preparation_is_safe_and_idempotent(
    tmp_path: Path,
) -> None:
    """验证开发副本仅补齐 XML，且重复执行不会继续写入。"""

    source_root = tmp_path / "source" / "VOC2012"
    target_root = tmp_path / "target" / "voc2012"
    _write_voc_segmentation_sample(source_root)
    for relative_path in (
        "JPEGImages",
        "SegmentationClass",
        "SegmentationObject",
        "ImageSets",
    ):
        shutil.copytree(source_root / relative_path, target_root / relative_path)

    preview = prepare_voc_instance_segmentation_dataset(
        source_root=source_root,
        target_root=target_root,
        apply=False,
    )
    assert preview.copied_annotation_count == 1
    assert not (target_root / "Annotations" / "sample-1.xml").exists()

    applied = prepare_voc_instance_segmentation_dataset(
        source_root=source_root,
        target_root=target_root,
        apply=True,
    )
    assert applied.copied_annotation_count == 1
    assert applied.annotation_count == 1
    assert applied.warning_count == 0

    repeated = prepare_voc_instance_segmentation_dataset(
        source_root=source_root,
        target_root=target_root,
        apply=True,
    )
    assert repeated.copied_annotation_count == 0
    assert repeated.verified_existing_file_count == 4


def test_voc_instance_segmentation_preparation_derives_independent_test_split(
    tmp_path: Path,
) -> None:
    """验证官方 val 被稳定拆为互斥 val/test，且官方 train 不进入 test。"""

    source_root = tmp_path / "source" / "VOC2012"
    target_root = tmp_path / "target" / "voc2012"
    _write_voc_segmentation_sample(source_root)
    val_stems = ("sample-2", "sample-3", "sample-4", "sample-5")
    for stem in val_stems:
        _clone_voc_segmentation_sample(source_root, stem=stem)
    split_root = source_root / "ImageSets" / "Segmentation"
    split_root.joinpath("val.txt").write_text(
        "".join(f"{stem}\n" for stem in val_stems),
        encoding="utf-8",
    )
    split_root.joinpath("trainval.txt").write_text(
        "sample-1\n" + "".join(f"{stem}\n" for stem in val_stems),
        encoding="utf-8",
    )
    for relative_path in (
        "JPEGImages",
        "SegmentationClass",
        "SegmentationObject",
        "ImageSets",
    ):
        shutil.copytree(source_root / relative_path, target_root / relative_path)

    result = prepare_voc_instance_segmentation_dataset(
        source_root=source_root,
        target_root=target_root,
        apply=True,
    )

    target_splits = target_root / "ImageSets" / "Segmentation"
    train = _read_split_members(target_splits / "train.txt")
    validation = _read_split_members(target_splits / "val.txt")
    test = _read_split_members(target_splits / "test.txt")
    official_val = _read_split_members(target_splits / "official-val.txt")
    trainval = _read_split_members(target_splits / "trainval.txt")
    assert train == {"sample-1"}
    assert len(validation) == 2
    assert len(test) == 2
    assert validation.isdisjoint(test)
    assert validation | test == set(val_stems)
    assert official_val == set(val_stems)
    assert train.isdisjoint(test)
    assert trainval == train | validation
    assert result.split_counts == {"train": 1, "val": 2, "test": 2}
    assert result.split_derivation is not None
    assert result.split_derivation["official_train_used_for_test"] is False


def _build_service(
    tmp_path: Path,
) -> tuple[SqlAlchemyDatasetImportService, SessionFactory]:
    """创建只使用本地临时存储的导入服务。"""

    session_factory, dataset_storage, _queue_backend = create_test_runtime(
        tmp_path / "runtime",
        database_name="voc-segmentation.db",
    )
    return (
        SqlAlchemyDatasetImportService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        ),
        session_factory,
    )


def _build_jpeg_bytes(*, width: int, height: int) -> bytes:
    """生成测试 DatasetVersion 使用的合法 JPEG。"""

    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(120, 80, 40)).save(
        buffer,
        format="JPEG",
    )
    return buffer.getvalue()


def _write_voc_segmentation_sample(dataset_root: Path) -> None:
    """写入一个带官方类别索引和完整 XML 的最小 VOC 样本。"""

    for relative_path in (
        "Annotations",
        "JPEGImages",
        "SegmentationClass",
        "SegmentationObject",
        "ImageSets/Segmentation",
    ):
        (dataset_root / relative_path).mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (6, 5), color=(120, 80, 40)).save(
        dataset_root / "JPEGImages" / "sample-1.jpg",
        format="JPEG",
    )
    class_mask = np.zeros((5, 6), dtype=np.uint8)
    object_mask = np.zeros((5, 6), dtype=np.uint8)
    class_mask[1:3, 1:4] = 1
    object_mask[1:3, 1:4] = 1
    Image.fromarray(class_mask, mode="L").save(
        dataset_root / "SegmentationClass" / "sample-1.png",
        format="PNG",
    )
    Image.fromarray(object_mask, mode="L").save(
        dataset_root / "SegmentationObject" / "sample-1.png",
        format="PNG",
    )
    (dataset_root / "ImageSets" / "Segmentation" / "train.txt").write_text(
        "sample-1\n",
        encoding="utf-8",
    )
    (dataset_root / "ImageSets" / "Segmentation" / "val.txt").write_text(
        "",
        encoding="utf-8",
    )
    (dataset_root / "ImageSets" / "Segmentation" / "trainval.txt").write_text(
        "sample-1\n",
        encoding="utf-8",
    )
    (dataset_root / "Annotations" / "sample-1.xml").write_text(
        """<annotation>
  <filename>sample-1.jpg</filename>
  <size><width>6</width><height>5</height><depth>3</depth></size>
  <object>
    <name>aeroplane</name><pose>Left</pose><truncated>0</truncated><difficult>1</difficult>
    <bndbox><xmin>1</xmin><ymin>1</ymin><xmax>4</xmax><ymax>3</ymax></bndbox>
  </object>
</annotation>
""",
        encoding="utf-8",
    )


def _clone_voc_segmentation_sample(dataset_root: Path, *, stem: str) -> None:
    """复制最小样本并修正 XML 文件名，供 split 派生测试使用。"""

    for relative_directory, suffix in (
        ("JPEGImages", ".jpg"),
        ("SegmentationClass", ".png"),
        ("SegmentationObject", ".png"),
    ):
        shutil.copy2(
            dataset_root / relative_directory / f"sample-1{suffix}",
            dataset_root / relative_directory / f"{stem}{suffix}",
        )
    xml_payload = (
        dataset_root / "Annotations" / "sample-1.xml"
    ).read_text(encoding="utf-8")
    (dataset_root / "Annotations" / f"{stem}.xml").write_text(
        xml_payload.replace("sample-1.jpg", f"{stem}.jpg"),
        encoding="utf-8",
    )


def _read_split_members(path: Path) -> set[str]:
    """读取测试目录中的 split 清单。"""

    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
