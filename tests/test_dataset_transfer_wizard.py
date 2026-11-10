"""导入向导草稿归属、上传恢复和导出映射回归。"""

from dataclasses import replace
from io import BytesIO
from uuid import UUID

import pytest

from backend.service.application.datasets.exports.contracts import DatasetExportRequest
from backend.service.application.datasets.exports.transfer_options import (
    apply_category_order,
    validate_options,
)
from backend.service.application.datasets.imports.upload_draft import (
    DatasetUploadDrafts,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
    DetectionAnnotation,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_upload_draft_owner_retry_and_one_time_consumption(tmp_path):
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    drafts = DatasetUploadDrafts(storage, "project", "owner")
    token = UUID(drafts.upload("sample.zip", BytesIO(b"zip bytes")).draft_id)
    for project, user in (("project", "other"), ("other", "owner")):
        with (
            pytest.raises(ResourceNotFoundError),
            DatasetUploadDrafts(storage, project, user).consume(token),
        ):
            pytest.fail("不能使用其他主体或项目的草稿")
    with pytest.raises(ValueError), drafts.consume(token):
        raise ValueError("提交前校验失败")
    with drafts.consume(token) as (name, stream):
        assert name == "sample.zip" and stream.read() == b"zip bytes"
        with pytest.raises(ResourceNotFoundError), drafts.consume(token):
            pytest.fail("重复提交不能同时领取文件")
    drafts.discard(token)
    with pytest.raises(ResourceNotFoundError), drafts.consume(token):
        pytest.fail("已提交草稿不能再次使用")


def test_export_class_order_validates_and_preserves_source():
    version = DatasetVersion(
        dataset_version_id="v",
        dataset_id="d",
        project_id="p",
        task_type="detection",
        categories=(DatasetCategory(10, "bolt"), DatasetCategory(20, "nut")),
        samples=(
            DatasetSample(
                "s",
                1,
                "part.png",
                20,
                20,
                "train",
                (
                    DetectionAnnotation("a", 10, (1, 1, 3, 4)),
                    DetectionAnnotation("b", 20, (3, 1, 4, 4)),
                ),
            ),
        ),
    )
    request = DatasetExportRequest(
        "p",
        "d",
        "v",
        source_category_ids=(20,),
        category_names=("fastener",),
        included_splits=("train",),
        package_name="工件.zip",
    )
    validate_options(request, version)
    result = apply_category_order(
        version, request.source_category_ids, request.category_names
    )
    assert result.categories == (DatasetCategory(0, "fastener"),)
    assert [
        (a.annotation_id, a.category_id) for a in result.samples[0].annotations
    ] == [("b", 0)]
    assert version.samples[0].annotations[1].category_id == 20
    for change in (
        {"source_category_ids": (20, 20)},
        {"source_category_ids": (3,)},
        {"included_splits": ()},
        {"package_name": "../part.zip"},
    ):
        with pytest.raises(InvalidRequestError):
            validate_options(replace(request, **change), version)
