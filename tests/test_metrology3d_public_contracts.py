"""M2 公开嵌套契约与持久变换证据，不接受旧字段或悬空访问引用。"""

from copy import deepcopy
from hashlib import sha256

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.geometry3d_methods import RigidTransform3d
from backend.contracts.workflows.geometry3d_observations import Features3d, Pose3d
from backend.service.application.errors import InvalidRequestError
from backend.contracts.workflows.point_cloud_runtime import PlaneSupportMethod
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent
from custom_nodes.metrology3d_nodes.shared.build_frame import build_frame
from custom_nodes.metrology3d_nodes.shared.transform_cloud import transform_cloud
from tests.test_metrology3d_frame import datum_cloud, frame_parameters
from tests.test_metrology3d_plane import plane_parameters


@pytest.fixture
def observation():
    """独立解析基准，关闭 Scope 后所有数组计费归零。"""
    scope, runtime, cloud, groups = datum_cloud()
    try:
        pose = build_frame(runtime, groups, frame_parameters(), cancel=lambda: None)
        yield runtime, cloud, groups, pose
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_public_methods_and_transform_round_trip(observation):
    """公开输入仅接受嵌套方法；质量策略只有一个规范位置。"""
    _, _, groups, pose = observation
    features = Features3d.model_validate_json(groups[0].model_dump_json())
    assert features == groups[0]
    assert Pose3d.model_validate_json(pose.model_dump_json()) == pose
    method = features.items[0].method.model_dump(mode="json")
    assert "quality_policy" in method and "quality_policy" not in method["parameters"]
    transform = RigidTransform3d.model_validate_json(pose.transform.model_dump_json())
    assert transform.format_id == "amvision.transform3d.v1"
    assert transform.provenance.parents[0].geometry == groups[0].items[0].geometry
    assert transform.provenance.parents[0].method == groups[0].items[0].method
    assert transform.provenance.source_retained is False


@pytest.mark.parametrize(
    "field", ["parameters", "parameters_sha256", "method_id", "method_version"]
)
def test_old_flat_fields_rejected(observation, field):
    """尚未发布的内部形状直接替换，不添加兼容分支。"""
    _, _, groups, pose = observation
    raw = groups[0].model_dump(mode="json")
    raw["items"][0][field] = raw["items"][0]["method"].pop(field)
    with pytest.raises(ValidationError):
        Features3d.model_validate(raw)
    raw = pose.model_dump(mode="json")
    raw[field] = raw["method"].pop(field)
    with pytest.raises(ValidationError):
        Pose3d.model_validate(raw)


@pytest.mark.parametrize(
    "change",
    ["hash", "observation", "frame", "policy", "old-matrix", "retained", "bool"],
)
def test_transform_trace_mismatch_rejected(observation, change):
    """证据不能只换参数、坐标或状态就伪装成另一变换。"""
    _, _, _, pose = observation
    raw = pose.transform.model_dump(mode="json")
    parent = raw["provenance"]["parents"][0]
    if change == "hash":
        parent["method"]["parameters"]["positive_normal"] = [0, 0, -1]
    elif change == "observation":
        parent["observation_id"] = "another"
    elif change == "frame":
        parent["frame_id"] = "another"
    elif change == "policy":
        parent["method"]["quality_policy"]["rules"][0]["lower"] = 1000
    elif change == "old-matrix":
        raw["target_from_source"] = raw.pop("matrix")
    else:
        raw["provenance"]["source_retained"] = True if change == "retained" else 0
    with pytest.raises(ValidationError):
        RigidTransform3d.model_validate(raw)


def test_pose_rejects_different_valid_method_snapshot(observation):
    """两份单独合法的证据也不能在同一个位姿中互相矛盾。"""
    runtime, _, groups, pose = observation
    other = build_frame(
        runtime,
        groups,
        frame_parameters(origin=dict(kind="anchor-projection", anchor=[0, 0, 0])),
        cancel=lambda: None,
    )
    raw = pose.model_dump(mode="json")
    raw["transform"] = other.transform.model_dump(mode="json")
    with pytest.raises(ValidationError, match="生成证据"):
        Pose3d.model_validate(raw)


def test_transform_checks_real_support_descriptor(observation):
    """摘要正确格式不等于实际支持资源相同。"""
    runtime, cloud, _, pose = observation
    raw = deepcopy(pose.model_dump(mode="json"))
    raw["transform"]["provenance"]["parents"][0]["support_content_sha256"] = "a" * 64
    supplied = Pose3d.model_validate(raw)
    before = runtime.budget.used
    with pytest.raises(InvalidRequestError, match="当前支持"):
        transform_cloud(runtime, cloud, supplied, cancel=lambda: None)
    assert runtime.budget.used == before


def test_persistent_transform_has_no_runtime_access_references(observation):
    """只保留观测标识和完整几何方法证据，不泄漏运行云访问身份。"""
    _, _, _, pose = observation

    def check(value):
        if isinstance(value, dict):
            assert (
                not {"run_id", "cloud_id", "resource_id", "writer_token", "support"}
                & value.keys()
            )
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(pose.transform.model_dump(mode="json"))


def test_consumer_rechecks_forged_passed_flags(observation):
    """数值与摘要一起篡改也不能绕过同一份限值比较器。"""
    runtime, _, groups, _ = observation
    raw = groups[0].model_dump(mode="json")
    quality = raw["items"][0]["quality"]
    for metric in quality["metrics"]["items"]:
        if metric["item_id"] in {"rms", "max_residual"}:
            metric["value"] = 5
    for check in quality["checks"]:
        if check["item_id"] in {"rms", "max_residual"}:
            check["value"] = 5
    supplied = Features3d.model_validate(raw)
    with pytest.raises(InvalidRequestError, match="限值计算"):
        build_frame(runtime, [supplied], frame_parameters(), cancel=lambda: None)


@pytest.mark.parametrize(
    "metric,value", [("rms", -1), ("inlier_ratio", 1.1), ("inlier_count", 3.5)]
)
def test_physical_quality_ranges_rejected(observation, metric, value):
    """计数、比例和残差范围是结构约束，不依赖生产公差。"""
    _, _, groups, _ = observation
    raw = groups[0].model_dump(mode="json")
    quality = raw["items"][0]["quality"]
    for item in quality["metrics"]["items"]:
        if item["item_id"] == metric:
            item["value"] = value
    for item in quality["checks"]:
        if item["item_id"] == metric:
            item["value"] = value
    with pytest.raises(ValidationError):
        Features3d.model_validate(raw)


def test_equal_count_supports_have_distinct_persistent_identity(observation):
    """相同父云、方法与点数不能合并不同原始行号的支持证据。"""
    runtime, cloud, _, _ = observation
    parameters = plane_parameters()
    identities = []
    for rows in ([0, 1, 2], [1, 2, 3], []):
        indices = np.asarray(rows, dtype="<u4").reshape(-1, 1)
        digest = sha256(indices).hexdigest()
        owner = OwnedCloudArrays(
            {"indices": indices}, runtime.budget.reserve(indices.nbytes)
        )
        runtime.storage_scope.register(
            ("test-support", digest), owner, lambda x: x.close()
        )
        support = runtime.register_subset(
            parent=cloud,
            indices=owner,
            method=PlaneSupportMethod(
                method_id="fit-plane-support",
                method_version=1,
                parameters=parameters,
                parameters_sha256=parameter_digest(parameters),
                indices_sha256=digest,
            ),
            cancel=lambda: None,
        )
        identities.append(freeze_cloud_parent(runtime, support)["content_sha256"])
    assert len(set(identities)) == 3
