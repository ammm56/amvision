"""尺寸证据的独立解析矩形；配置只用于测试，不是生产默认。"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.contracts.workflows.dimension3d_parameters import MeasureExtentsParameters
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from custom_nodes._metrology3d_nodes.shared.geometry_quality import geometry_quality
from tests.test_metrology3d_boundary_contracts import evaluation


def dimension_policy():
    """几何可用性不可跳过，其余条件由独立场景显式配置。"""
    return dict(
        policy_id="dimension-test",
        policy_version=1,
        rules=[dict(item_id="geometry_usable", unit="1", lower=1)],
    )


def extent_parameters(*, rectangle=False, **changes):
    """固定 XY 平面；矩形比较条件仅作用于测试。"""
    mode = (
        dict(
            kind="minimum-area-rectangle",
            area_abs_tolerance=1e-10,
            area_rel_tolerance=1e-12,
            dimension_abs_tolerance=1e-8,
            dimension_rel_tolerance=1e-10,
            orientation_tolerance_radians=1e-8,
        )
        if rectangle
        else dict(kind="axis-spans")
    )
    components = ("length", "width") if rectangle else ("u", "v")
    return MeasureExtentsParameters(
        **{
            "source": dict(kind="cloud"),
            "mode": mode,
            "evaluation": evaluation(),
            "outputs": [dict(component=c, item_id=c) for c in components],
            "quality_policy": dimension_policy(),
            **changes,
        }
    )


def extent_evidence():
    """4x2 的独立构造包络，源接触坐标不依赖被测算法。"""
    p = extent_parameters()
    support = dict(
        role="source",
        content_sha256="a" * 64,
        point_count=4,
        source_point_count=40,
        vertex_kind="source",
        sample_origin="measured",
        bounds=dict(min=(0, 0, 0), max=(4, 2, 0)),
        topology=None,
        feature=None,
    )
    points = [(0, 0, 0), (0, 0, 0), (4, 2, 0), (4, 2, 0)]
    geometry = dict(
        kind="projected-extents",
        origin=(0, 0, 0),
        axes=((1, 0, 0), (0, 1, 0)),
        limits=(0, 0, 4, 2),
        corners=((0, 0, 0), (4, 0, 0), (4, 2, 0), (0, 2, 0)),
        contacts=[
            dict(
                point=q,
                projected=q,
                vertex_index=i,
                source_index=i + 10,
                lineage=None,
                tied_count=2,
            )
            for i, q in enumerate(points)
        ],
        candidates=None,
    )
    quality = geometry_quality(
        "scan",
        {
            "geometry_usable": (1, "1"),
            "support_count": (4, "1"),
            "span_u": (4, "mm"),
            "span_v": (2, "mm"),
        },
        p.quality_policy,
        reason="missing",
    )
    common = dict(
        kind="measure-extents",
        valid=True,
        reason=None,
        sample_origin="measured",
        support=[support],
        geometry=geometry,
        diagnostic=None,
        quality=quality.model_dump(mode="json"),
        method=dict(
            method_id="measure-extents",
            method_version=1,
            parameters=p.model_dump(mode="json"),
            parameters_sha256=parameter_digest(p),
        ),
    )
    return dict(
        format_id="amvision.measurement-evidence3d.v2",
        observation_id="scan",
        frame_id="fixture",
        length_unit="mm",
        items=[
            {**deepcopy(common), "item_id": c, "component": c, "value": v}
            for c, v in (("u", 4), ("v", 2))
        ],
    )


def test_v2_roundtrip_and_numeric_table():
    result = MeasurementEvidence3d.model_validate(extent_evidence())
    assert MeasurementEvidence3d.model_validate_json(result.model_dump_json()) == result
    assert [i.value for i in result.numeric_table().items] == [4, 2]


@pytest.mark.parametrize(
    "case",
    [
        "v1",
        "missing-output",
        "value",
        "swapped-component",
        "digest",
        "source-index",
        "generated-no-lineage",
        "contact-projection",
        "axis-out-of-plane",
        "inconsistent-support",
        "false-usable",
    ],
)
def test_reject_tampered_evidence(case):
    raw = extent_evidence()
    item = raw["items"][0]
    if case == "v1":
        raw["format_id"] = "amvision.measurement-evidence3d.v1"
    elif case == "missing-output":
        raw["items"].pop()
    elif case == "value":
        item["value"] = 5
    elif case == "swapped-component":
        item["component"] = "length"
    elif case == "digest":
        item["method"]["parameters_sha256"] = "f" * 64
    elif case == "source-index":
        item["geometry"]["contacts"][0]["source_index"] = 40
    elif case == "generated-no-lineage":
        item["support"][0].update(vertex_kind="generated", sample_origin="interpolated")
    elif case == "contact-projection":
        item["geometry"]["contacts"][0]["projected"] = (0, 0, 1)
    elif case == "axis-out-of-plane":
        item["geometry"]["axes"] = ((0, 0, 1), (0, 1, 0))
    elif case == "inconsistent-support":
        item["support"][0]["content_sha256"] = "b" * 64
    elif case == "false-usable":
        item["quality"]["metrics"]["items"][0]["value"] = 0
    with pytest.raises(ValidationError):
        MeasurementEvidence3d.model_validate(raw)


def test_generated_contacts_keep_original_edge_not_fake_source_row():
    raw = extent_evidence()
    for item in raw["items"]:
        item["sample_origin"] = "interpolated"
        item["support"][0].update(
            vertex_kind="generated", sample_origin="interpolated", source_point_count=3
        )
        for contact in item["geometry"]["contacts"]:
            contact.update(
                source_index=None,
                lineage=dict(
                    source_edge=(0, 2),
                    weights=(0.5, 0.5),
                    source_face_count=1,
                    source_faces_sha256="c" * 64,
                ),
            )
    result = MeasurementEvidence3d.model_validate(raw)
    assert (
        result.items[0].support[0].point_count
        > result.items[0].support[0].source_point_count
    )


def test_parameters_reject_mode_output_and_optional_geometry_guard():
    with pytest.raises(ValidationError):
        extent_parameters(outputs=[dict(component="length", item_id="length")])
    policy = dimension_policy()
    policy["rules"][0]["required"] = False
    with pytest.raises(ValidationError):
        extent_parameters(quality_policy=policy)


@pytest.mark.parametrize("key,unit", [("unknown", "1"), ("span_u", "rad")])
def test_quality_identity_rejected_before_execution(key, unit):
    """未知指标或错误单位不能等执行结束才拒绝。"""
    policy = dimension_policy()
    policy["rules"].append(dict(item_id=key, unit=unit, lower=0))
    with pytest.raises(ValidationError, match="指标或错误单位"):
        extent_parameters(quality_policy=policy)


def test_persisted_metrics_cannot_disagree_with_geometry():
    """所有兄弟量同时篡改也必须由几何一致性检查拒绝。"""
    raw = extent_evidence()
    for item in raw["items"]:
        next(
            m for m in item["quality"]["metrics"]["items"] if m["item_id"] == "span_u"
        )["value"] = 9
    with pytest.raises(ValidationError, match="跨度指标"):
        MeasurementEvidence3d.model_validate(raw)
