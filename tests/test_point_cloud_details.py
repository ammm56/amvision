"""空间显示索引使用独立逐行真值，不以抽样显示证明完整性。"""

import numpy as np
import pytest
import json

from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.application.workflows.point_cloud.detail_index import (
    prepare_index,
    read_index,
    read_block,
    index_root,
)
from backend.service.application.workflows.point_cloud.execution_policy import (
    PointCloudExecutionPolicy,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from tests.point_cloud_support import policy, create_resource_service
from tests.test_metrology3d_preprocess import make_cloud


def detail_policy():
    """小块强制多叶；不是生产默认值。"""
    return PointCloudExecutionPolicy(
        io=policy(),
        preview=dict(
            max_points=2,
            max_data_bytes=512,
            max_body_bytes=16384,
            max_working_bytes=4096,
        ),
        max_asset_bytes=8192,
        max_archive_bytes=16384,
        max_export_bytes=8192,
    )


@pytest.fixture
def saved(tmp_path):
    """包含重复位置、无效点和不可经 JSON 浮点往返的字段。"""
    points = np.array(
        [[0, 0, 0], [1, 2, 3], [1, 2, 3], [1, 2, 3], [np.nan, 0, 0], [4, 5, 6]],
        dtype="f8",
    )
    serial = np.arange(6, dtype="u8") + np.uint64(2**63)
    scope, runtime, source = make_cloud(
        coordinates=points, attributes=[("serial", serial, None)]
    )
    service, p = create_resource_service(tmp_path), detail_policy()
    reference = save_cloud(
        runtime,
        source,
        service=service,
        project_id="test",
        name="source",
        mode="derived",
        write_identity="a" * 64,
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
    try:
        yield runtime, source, cloud, service, p, points, serial
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def build(saved, cancel=lambda: None):
    """显式准备一次。"""
    runtime, _, cloud, service, p, *_ = saved
    return prepare_index(
        runtime, cloud, service=service, project_id="test", policy=p, cancel=cancel
    )


def test_complete_exact_fields_and_delete(saved):
    runtime, _, cloud, service, p, points, serial = saved
    index = build(saved)
    assert index.valid_count == 5 and index.excluded_count == 1
    assert index.point_count == index.source_point_count == 6
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
            dtype="<u8",
            buffer=raw,
            offset=index.logical_offset,
            strides=(index.row_bytes,),
        )
        positions = np.ndarray(
            (block.count, 3), dtype="<f8", buffer=raw, strides=(index.row_bytes, 8)
        )
        identifiers = np.ndarray(
            (block.count,),
            dtype="<u8",
            buffer=raw,
            offset=24,
            strides=(index.row_bytes,),
        )
        np.testing.assert_array_equal(positions, points[rows])
        np.testing.assert_array_equal(identifiers, serial[rows])
        seen.extend(rows.tolist())
    assert sorted(seen) == [0, 1, 2, 3, 5]
    service.delete(index.source, project_id="test")
    assert not service.storage.resolve(index_root(service, index.source)).exists()
    with pytest.raises(ResourceNotFoundError):
        read_index(service, index.source, project_id="test", policy=p.preview)


def test_cancel_preserves_committed_index_and_releases_budget(saved):
    runtime, _, cloud, service, p, *_ = saved
    first = build(saved)
    before = runtime.budget.used
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 7:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        build(saved, cancel)
    assert runtime.budget.used == before
    assert (
        read_index(service, first.source, project_id="test", policy=p.preview) == first
    )
    second = build(saved)
    assert second.generation != first.generation
    with pytest.raises(InvalidRequestError, match="更新"):
        read_block(
            service,
            first.source,
            0,
            generation=first.generation,
            project_id="test",
            policy=p.preview,
        )
    assert (
        len(list(service.storage.resolve(index_root(service, first.source)).iterdir()))
        == 2
    )


def test_no_implicit_persistence_or_unbounded_gather(saved):
    runtime, source, cloud, service, p, *_ = saved
    with pytest.raises(InvalidRequestError, match="完整点云资产"):
        prepare_index(
            runtime,
            source,
            service=service,
            project_id="test",
            policy=p,
            cancel=lambda: None,
        )
    with runtime.borrow(cloud) as view:
        for rows in (np.array([-1]), np.array([6]), np.array([0, 1, 2])):
            with pytest.raises(InvalidRequestError):
                view.gather(rows)


def test_reject_corruption_and_foreign_project(saved):
    """缓存不能绕过来源权限；坏字节不能当成完整细节发出。"""
    _, _, _, service, p, *_ = saved
    index = build(saved)
    with pytest.raises((InvalidRequestError, ResourceNotFoundError)):
        read_index(service, index.source, project_id="other", policy=p.preview)
    block = index.blocks[0]
    key = (
        index_root(service, index.source)
        + f"/{index.generation}/immutable/sha256-{block.sha256}/content.bin"
    )
    path = service.storage.resolve(key)
    content = path.read_bytes()
    path.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    with pytest.raises(InvalidRequestError, match="摘要"):
        read_block(
            service,
            index.source,
            0,
            generation=index.generation,
            project_id="test",
            policy=p.preview,
        )
    path.write_bytes(content[:-1])
    with pytest.raises(InvalidRequestError, match="长度"):
        read_block(
            service,
            index.source,
            0,
            generation=index.generation,
            project_id="test",
            policy=p.preview,
        )
    service.storage.write_json(
        index_root(service, index.source) + "/index.json", {"broken": True}
    )
    with pytest.raises(InvalidRequestError, match="损坏"):
        read_index(service, index.source, project_id="test", policy=p.preview)


def test_index_capacity_rejection_is_transactional(saved):
    """描述预算不足时不留下半成品，也不替换当前索引。"""
    runtime, _, cloud, service, p, *_ = saved
    index = build(saved)
    before = runtime.budget.used
    compact_bytes = len(json.dumps(index.model_dump(mode="json")).encode("utf-8"))
    limited = p.model_copy(
        update={
            "preview": p.preview.model_copy(update={"max_body_bytes": compact_bytes})
        }
    )
    with pytest.raises(InvalidRequestError, match="描述预算"):
        prepare_index(
            runtime,
            cloud,
            service=service,
            project_id="test",
            policy=limited,
            cancel=lambda: None,
        )
    assert runtime.budget.used == before
    assert (
        read_index(service, index.source, project_id="test", policy=p.preview) == index
    )
    assert (
        len(list(service.storage.resolve(index_root(service, index.source)).iterdir()))
        == 2
    )


def test_generated_vertices_do_not_gain_fake_source_rows(tmp_path):
    """保存恢复生成点后仍为顶点身份，原始来源仍在源资产内。"""
    from tests.test_point_cloud_runtime import root_cloud
    from tests.test_point_cloud_lineage import generated
    from backend.service.application.runtime.resource_scope import ResourceScope
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )

    p = detail_policy()
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="generated", policy=p.io)
    service = create_resource_service(tmp_path)
    try:
        root, _ = root_cloud(runtime)
        cloud = generated(runtime, root)
        reference = save_cloud(
            runtime,
            cloud,
            service=service,
            project_id="test",
            name="generated",
            mode="derived",
            write_identity="b" * 64,
            policy=p.assets(),
            cancel=lambda: None,
        )
        restored = read_asset(
            runtime,
            reference,
            service=service,
            project_id="test",
            policy=p.assets(),
            cancel=lambda: None,
        )
        index = prepare_index(
            runtime,
            restored,
            service=service,
            project_id="test",
            policy=p,
            cancel=lambda: None,
        )
        assert index.vertex_kind == "generated" and index.source_point_count == 6
        assert index.point_count == 2
        block = index.blocks[0]
        raw = read_block(
            service,
            reference,
            0,
            generation=index.generation,
            project_id="test",
            policy=p.preview,
        )
        logical = np.ndarray(
            (block.count,),
            dtype="<u8",
            buffer=raw,
            offset=index.logical_offset,
            strides=(index.row_bytes,),
        )
        identity = np.ndarray(
            (block.count,),
            dtype="<u8",
            buffer=raw,
            offset=index.identity_offset,
            strides=(index.row_bytes,),
        )
        np.testing.assert_array_equal(identity, logical)
    finally:
        assert not scope.close() and runtime.budget.used == 0
