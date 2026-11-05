"""位姿代数独立真值、运行权限、持久来源与资源释放。"""

import numpy as np
from dataclasses import replace
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.geometry3d_observations import Pose3d
from backend.contracts.workflows.measurement3d_query import (
    QueryPoseEvidence,
    pose_query_line,
)
from backend.contracts.workflows.pose3d_operations import PoseOperationSettings
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.build_frame import build_frame
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes.metrology3d_nodes.shared.pose_operations import operate_pose
from custom_nodes.metrology3d_nodes.shared.transform_cloud import transform_cloud
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from tests.test_metrology3d_transform import transform_source, cloud_pose
from tests.test_metrology3d_frame import frame_parameters
from tests.test_metrology3d_plane import plane_parameters
from tests.test_point_cloud_assets import POLICY
from tests.point_cloud_support import create_resource_service
from tests.point_cloud_support import policy
from tests.test_metrology3d_preprocess import make_cloud

ASSET_POLICY = replace(POLICY, chunk_bytes=4096)


def operation(runtime, first, second=None, *, name="result", cancel=lambda: None):
    """测试明确输入次序与输出身份。"""
    return operate_pose(
        runtime,
        first,
        second,
        PoseOperationSettings(pose_id=name),
        inverse=second is None,
        cancel=cancel,
    )


@pytest.fixture
def scene():
    """两级非交换刚性坐标，源字段含 uint64 大整数。"""
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array([[1, 2, 3], [2, 2, 3], [1, 3, 3], [2, 3, 3]], dtype="f8"),
        attributes=(
            ("normals", np.tile([1.0, 0.0, 0.0], (4, 1)), "1"),
            ("label", np.arange(4, dtype="u8") + 2**53 + 1, "1"),
        ),
        runtime_policy=policy(chunk_rows=8, chunk_bytes=4096),
    )
    features, first = cloud_pose(runtime, cloud)
    forward = transform_cloud(runtime, cloud, first, cancel=lambda: None)
    planes = fit_plane(
        runtime, forward, plane_parameters(feature_id="primary"), cancel=lambda: None
    )
    second = build_frame(
        runtime,
        [planes],
        frame_parameters(
            pose_id="second",
            target_frame_id="tool",
            origin=dict(kind="anchor-projection", anchor=[2, 1, 5]),
            x_axis=dict(kind="direction", direction=[1, 0, 0]),
        ),
        cancel=lambda: None,
    )
    try:
        yield runtime, cloud, features, first, forward, second
    finally:
        assert scope.close() == ()
        assert runtime.budget.used == 0


def test_compose_inverse_truth_fields_rows_and_no_allocation(scene):
    runtime, cloud, _, first, forward, second = scene
    before = runtime.budget.used
    combined = operation(runtime, first, second)
    inverse = operation(runtime, combined, name="inverse")
    identity = operation(runtime, combined, inverse, name="identity")
    assert runtime.budget.used == before
    expected = np.array([[0, 1, 0, -4], [-1, 0, 0, 0], [0, 0, 1, -3], [0, 0, 0, 1]])
    np.testing.assert_allclose(combined.transform.matrix, expected, atol=1e-12)
    np.testing.assert_allclose(
        inverse.transform.matrix, np.linalg.inv(expected), atol=1e-12
    )
    np.testing.assert_allclose(identity.transform.matrix, np.eye(4), atol=1e-12)
    assert (
        identity.source_frame_id == identity.target_frame_id == cloud.spatial.frame_id
    )
    assert combined.support == (*first.support, *second.support)
    assert inverse.support == (*second.support, *first.support)
    assert all(s.inverse for s in inverse.method.steps)
    assert Pose3d.model_validate_json(combined.model_dump_json()) == combined
    sequential = transform_cloud(runtime, forward, second, cancel=lambda: None)
    actual = transform_cloud(runtime, cloud, combined, cancel=lambda: None)
    restored = transform_cloud(runtime, actual, inverse, cancel=lambda: None)
    for left, right in ((sequential, actual), (cloud, restored)):
        assert left.fields == right.fields
        with runtime.borrow(left) as a, runtime.borrow(right) as b:
            np.testing.assert_array_equal(
                a.source_indices(0, 4), b.source_indices(0, 4)
            )
            for key, value in a.chunk(0, 4).items():
                np.testing.assert_array_equal(value, b.chunk(0, 4)[key])
        assert runtime.source_point_count(right) == 4


def test_save_read_and_query(scene, tmp_path):
    runtime, cloud, _, first, _, second = scene
    pose = operation(runtime, first, second)
    result = transform_cloud(runtime, cloud, pose, cancel=lambda: None)
    service = create_resource_service(tmp_path)
    asset = save_cloud(
        runtime,
        result,
        service=service,
        project_id="test",
        name="pose-chain",
        mode="derived",
        write_identity="a" * 64,
        policy=ASSET_POLICY,
        cancel=lambda: None,
    )
    restored = read_asset(
        runtime,
        asset,
        service=service,
        project_id="test",
        policy=ASSET_POLICY,
        cancel=lambda: None,
    )
    stored = service.read(asset, project_id="test").content.point_cloud
    assert stored.provenance.method.parameters.transform == pose.transform
    with runtime.borrow(result) as a, runtime.borrow(restored) as b:
        for key, value in a.chunk(0, 4).items():
            np.testing.assert_array_equal(value, b.chunk(0, 4)[key])
    evidence = QueryPoseEvidence.model_validate(
        pose.model_dump(include=set(QueryPoseEvidence.model_fields))
    )
    assert QueryPoseEvidence.model_validate_json(evidence.model_dump_json()) == evidence
    # 目标点 (2,3,0) 在源中是 (-3,6,3)；方向为源 +Z。
    line = pose_query_line(pose.transform, (2, 3))
    np.testing.assert_allclose(line.query_position, [-3, 6, 3])
    np.testing.assert_allclose(line.direction, [0, 0, 1])


@pytest.mark.parametrize(
    "field,value",
    [("run_id", "old"), ("observation_id", "other"), ("length_unit", "m")],
)
def test_identity_rejected_without_allocation(scene, field, value):
    runtime, _, _, first, _, second = scene
    before = runtime.budget.used
    with pytest.raises(InvalidRequestError):
        operation(runtime, first, second.model_copy(update={field: value}))
    assert runtime.budget.used == before


def test_reversed_order_and_matrix_tamper_rejected(scene):
    runtime, _, _, first, _, second = scene
    with pytest.raises(InvalidRequestError, match="first"):
        operation(runtime, second, first)
    pose = operation(runtime, first, second)
    raw = pose.model_dump(mode="json")
    raw["transform"]["matrix"][0][3] += 1
    with pytest.raises(ValidationError, match="派生矩阵"):
        Pose3d.model_validate(raw)
    raw = operation(
        runtime, pose, operation(runtime, pose), name="identity"
    ).model_dump(mode="json")
    raw["transform"]["matrix"][0][3] = 1
    with pytest.raises(ValidationError):
        Pose3d.model_validate(raw)


def test_invalid_pose_propagates_no_stale_matrix(scene):
    runtime, _, features, _, _, _ = scene
    invalid = build_frame(
        runtime,
        [features],
        frame_parameters(x_axis=dict(kind="direction", direction=[0, 0, 1])),
        cancel=lambda: None,
    )
    before = runtime.budget.used
    result = operation(runtime, invalid)
    assert result.state == invalid.state and result.reason == invalid.reason
    assert result.transform is None and runtime.budget.used == before


def test_stale_support_rejected():
    scope, runtime, cloud = transform_source(np.float64)
    _, pose = cloud_pose(runtime, cloud)
    inverse = operation(runtime, pose)
    assert scope.close() == ()
    with pytest.raises(RuntimeError, match="资源不可用"):
        operation(runtime, inverse)
    assert runtime.budget.used == 0


def test_derived_pose_uv_and_compact_schema():
    """双求逆保留斜面同线高度；标准 JSON Schema 引用仍验证嵌套矩阵。"""
    from tests.test_metrology3d_pose_query import tilted_fixture, query
    from tests.test_metrology3d_measurement_contracts import step_parameters
    from custom_nodes.metrology3d_nodes.shared.measure_step import measure_step
    from custom_nodes.metrology3d_nodes.workflow.catalog_builder import (
        build_custom_node_catalog_document,
    )
    from jsonschema import Draft202012Validator

    scope, runtime, _, groups, pose, _, _, _ = tilted_fixture()
    try:
        restored = operation(runtime, operation(runtime, pose), name="datum")
        result = measure_step(
            runtime,
            step_parameters(query=query()),
            groups=groups,
            pose=restored,
            cancel=lambda: None,
        )
        assert result.items[0].valid
        assert result.items[0].value == pytest.approx(5.05, abs=1e-10)
        catalog = build_custom_node_catalog_document()
        schema = next(
            p.json_schema
            for p in catalog.payload_contracts
            if p.payload_type_id == "pose3d.v1"
        )
        assert "$defs" in schema
        validator = Draft202012Validator(schema)
        validator.validate(restored.model_dump(mode="json"))
        bad = restored.model_dump(mode="json")
        bad["transform"]["matrix"][0][0] = "not-a-number"
        assert list(validator.iter_errors(bad))
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_derived_frame_cannot_impersonate_contour_datum():
    """坐标虽相同，派生代数并不重新定义动态等高的物理主基准。"""
    from tests.test_metrology3d_dynamic_contour import fixture, extract

    values, parameters, measurement = fixture()
    scope, runtime, _, _, pose, *_ = values
    try:
        derived = operation(runtime, operation(runtime, pose), name=pose.pose_id)
        supplied = (*values[:4], derived, *values[5:])
        with pytest.raises(InvalidRequestError, match="Build Frame"):
            extract(supplied, parameters, measurement)
    finally:
        assert scope.close() == () and runtime.budget.used == 0


@pytest.mark.parametrize("at", range(1, 14))
def test_cancel_has_no_new_owners(scene, at):
    runtime, _, _, first, _, second = scene
    before, count = runtime.budget.used, 0

    def cancel():
        nonlocal count
        count += 1
        if count == at:
            raise RuntimeError("cancelled")

    try:
        operation(runtime, first, second, cancel=cancel)
    except RuntimeError as error:
        assert str(error) == "cancelled"
    assert runtime.budget.used == before
