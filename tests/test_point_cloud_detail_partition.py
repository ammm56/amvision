"""有界空间显示索引：独立逐行真值、最坏分布和事务故障。"""

from contextlib import contextmanager
import errno

import numpy as np
import pytest

from backend.contracts.workflows.point_cloud_detail import (
    CloudDetailIndex,
    detail_index_dtype,
)
from backend.service.application.errors import (
    InvalidRequestError,
    PersistenceOperationError,
)
from backend.service.application.workflows.point_cloud import detail_builder
from backend.service.application.workflows.point_cloud.detail_index import (
    index_root,
    prepare_index,
    read_block,
    read_index,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import read_asset, save_cloud
from tests.point_cloud_support import create_resource_service, policy
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_point_cloud_details import detail_policy


@contextmanager
def asset(tmp_path, coordinates, attributes=(), source_rows=None):
    """真实保存/读取，计算块只允许 2048 行，不能整云复制。"""
    p = detail_policy().model_copy(
        update={
            "io": policy(
                chunk_rows=2048,
                max_decoded_bytes=8_000_000,
                max_working_bytes=4_000_000,
                max_live_array_bytes=8_000_000,
            ),
            "preview": detail_policy().preview.model_copy(
                update={
                    "max_points": 2048,
                    "max_data_bytes": 256_000,
                    "max_body_bytes": 1_000_000,
                    "max_working_bytes": 1_000_000,
                }
            ),
            "max_asset_bytes": 8_000_000,
        }
    )
    scope, runtime, source = make_cloud(
        coordinates=coordinates,
        attributes=attributes,
        runtime_policy=p.io,
    )
    service = create_resource_service(tmp_path)
    try:
        if source_rows is not None:
            from tests.test_point_cloud_runtime import method, own

            source = runtime.register_subset(
                parent=source,
                method=method(),
                cancel=lambda: None,
                indices=own(
                    runtime, {"indices": np.asarray(source_rows, dtype="u4")[:, None]}
                ),
            )
        reference = save_cloud(
            runtime,
            source,
            service=service,
            project_id="test",
            name="source",
            mode="derived",
            write_identity="d" * 64,
            policy=p.assets(),
            cancel=lambda: None,
        )
        cloud = read_asset(
            runtime,
            reference,
            service=service,
            project_id="test",
            policy=p.assets(),
            cancel=lambda: None,
        )
        yield runtime, cloud, service, p
    finally:
        assert not scope.close() and runtime.budget.used == 0


def prepare(context, cancel=lambda: None):
    """调用正式索引入口，所有状态仍由原资产服务管理。"""
    runtime, cloud, service, p = context
    return prepare_index(
        runtime, cloud, service=service, project_id="test", policy=p, cancel=cancel
    )


def check_rows(context, index, coordinates, identities):
    """直接按行解码全部块；不使用构建器算期望值。"""
    _, _, service, p = context
    seen = []
    for block in index.blocks:
        raw = read_block(
            service,
            index.source,
            block.block_id,
            generation=index.generation,
            project_id="test",
            policy=p.preview,
        )
        rows = np.ndarray(
            (block.count,),
            dtype=np.dtype(index.logical_dtype).newbyteorder("<"),
            buffer=raw,
            offset=index.logical_offset,
            strides=(index.row_bytes,),
        )
        source = np.ndarray(
            (block.count,),
            dtype=np.dtype(index.identity_dtype).newbyteorder("<"),
            buffer=raw,
            offset=index.identity_offset,
            strides=(index.row_bytes,),
        )
        xyz = np.ndarray(
            (block.count, 3),
            dtype=coordinates.dtype.newbyteorder("<"),
            buffer=raw,
            strides=(index.row_bytes, coordinates.dtype.itemsize),
        )
        np.testing.assert_array_equal(xyz, coordinates[rows])
        np.testing.assert_array_equal(source, identities[rows])
        seen.extend(rows.tolist())
    assert sorted(seen) == list(range(len(coordinates)))
    assert not list(
        service.storage.resolve(index_root(service, index.source)).rglob("*.rows")
    )


def test_tree_is_bounded_with_all_rows_and_small_working_budget(tmp_path, monkeypatch):
    points = np.random.default_rng(41).normal(size=(100_000, 3)).astype("f4")
    calls = []
    native = detail_builder.KDTree

    def bounded(points, **kwargs):
        calls.append(len(points))
        assert len(points) <= 2048
        return native(points, **kwargs)

    # 保留 KDTree.innernode 的正式类型判别。
    bounded.innernode = native.innernode
    monkeypatch.setattr(detail_builder, "KDTree", bounded)
    with asset(tmp_path, points) as context:
        runtime = context[0]
        assert len(points) * 192 > runtime.policy.max_working_bytes
        used = runtime.budget.used
        index = prepare(context)
        assert runtime.budget.used == used
        assert calls and sum(calls) == len(points)
        assert index.row_bytes == 20
        check_rows(context, index, points, np.arange(len(points)))


@pytest.mark.parametrize("kind", ["duplicate", "line", "extreme", "adjacent"])
def test_degenerate_spatial_distributions_keep_every_point(tmp_path, kind):
    points = np.zeros((6000, 3), dtype="f8")
    if kind == "line":
        points[:, 1] = np.arange(len(points))
    elif kind == "extreme":
        points[-2:, 0] = [-1e300, 1e300]
    elif kind == "adjacent":
        points[:, 0] = 1.0
        points[-1, 0] = np.nextafter(1.0, 2.0)
    with asset(tmp_path, points) as context:
        index = prepare(context)
        check_rows(context, index, points, np.arange(len(points)))


def test_subset_identity_still_refers_to_original_rows(tmp_path):
    points = np.arange(9000, dtype="f4").reshape(-1, 3)
    chosen = np.arange(1, len(points), 3)
    with asset(tmp_path, points, source_rows=chosen) as context:
        index = prepare(context)
        assert index.source_point_count == len(points)
        check_rows(context, index, points[chosen], chosen)


def test_single_point_leaves_include_tree_wrappers_and_descriptions(tmp_path):
    points = np.random.default_rng(71).normal(size=(128, 3)).astype("f4")
    with asset(tmp_path, points) as context:
        runtime, cloud, service, p = context
        small = p.model_copy(
            update={"preview": p.preview.model_copy(update={"max_points": 1})}
        )
        before = runtime.budget.used
        index = prepare((runtime, cloud, service, small))
        assert len(index.blocks) == len(points)
        assert runtime.budget.used == before
        check_rows(context, index, points, np.arange(len(points)))


@pytest.mark.parametrize("stage", ["write", "partition", "commit"])
def test_failure_preserves_previous_generation_and_releases_handles(
    tmp_path, monkeypatch, stage
):
    points = np.random.default_rng(9).normal(size=(5000, 3)).astype("f4")
    with asset(tmp_path, points) as context:
        runtime, _, service, p = context
        first = prepare(context)
        before = runtime.budget.used
        from backend.service.application.workflows.point_cloud import detail_partition

        def fail(*args, **kwargs):
            raise OSError(errno.ENOSPC, "injected disk write failure")

        with monkeypatch.context() as patch:
            if stage == "write":
                patch.setattr(service.storage, "write_immutable_stream", fail)
            elif stage == "commit":
                patch.setattr(service.storage, "write_json", fail)
            else:
                original = detail_partition.split_partition

                def after_split(*args, **kwargs):
                    original(*args, **kwargs)
                    fail()

                patch.setattr(detail_partition, "split_partition", after_split)
            with pytest.raises(PersistenceOperationError) as failure:
                prepare(context)
            assert failure.value.details["errno"] == errno.ENOSPC
        assert runtime.budget.used == before
        assert (
            read_index(service, first.source, project_id="test", policy=p.preview)
            == first
        )
        assert (
            len(
                list(
                    service.storage.resolve(index_root(service, first.source)).iterdir()
                )
            )
            == 2
        )
        second = prepare(context)
        check_rows(context, second, points, np.arange(len(points)))


def test_row_width_boundaries_and_missing_layout_rejected(tmp_path):
    assert detail_index_dtype(2**32) == "uint32"
    assert detail_index_dtype(2**32 + 1) == "uint64"
    with asset(tmp_path, np.zeros((2, 3), dtype="f4")) as context:
        data = prepare(context).model_dump(mode="json")
        del data["logical_dtype"]
        with pytest.raises(ValueError):
            CloudDetailIndex.model_validate(data)
        data["logical_dtype"] = "uint32"
        data["source_point_count"] = 2**32 + 1
        with pytest.raises(ValueError, match="行号宽度"):
            CloudDetailIndex.model_validate(data)
        data.update(identity_dtype="uint64", row_bytes=24)
        for block in data["blocks"]:
            block["byte_length"] = block["count"] * 24
        assert CloudDetailIndex.model_validate(data).identity_dtype == "uint64"


def test_asset_limit_applies_to_exact_compact_records(tmp_path):
    points = np.arange(30, dtype="f4").reshape(-1, 3)
    with asset(tmp_path, points) as context:
        runtime, cloud, service, p = context
        exact = p.model_copy(update={"max_asset_bytes": 200})
        index = prepare((runtime, cloud, service, exact))
        assert sum(block.byte_length for block in index.blocks) == 200
        with pytest.raises(InvalidRequestError, match="资产预算"):
            prepare(
                (runtime, cloud, service, p.model_copy(update={"max_asset_bytes": 199}))
            )
