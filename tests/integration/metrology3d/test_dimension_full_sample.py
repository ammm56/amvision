"""完整现场样本的尺寸证据与真实发布生命周期；不伪造实体孔或槽真值。"""

from copy import deepcopy

from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.test_boundary_published_full_sample import (
    sample_boundary_documents,
    check_sample_boundaries,
)
from tests.integration.metrology3d.test_published_runtime import (
    published_full_sample_lifecycle,
    POINTS,
)
from tests.test_metrology3d_boundary_contracts import evaluation
from tests.test_metrology3d_dimension_contracts import extent_parameters
from tests.test_metrology3d_dimension_runtime import hole_parameters
from tests.test_metrology3d_edge_pair import pair_parameters


def sample_dimension_documents(cloud, path):
    """延用已核对的完整样本测试 ROI 与原质量门槛。"""
    cloud, (template, app) = sample_boundary_documents(cloud, path)
    graph = template.model_dump(mode="json")
    projection = next(n for n in graph["nodes"] if n["node_id"] == "projection")[
        "parameters"
    ]["settings"]
    line = next(n for n in graph["nodes"] if n["node_id"] == "line")
    second = deepcopy(line)
    second["node_id"] = "line-b"
    second["parameters"]["settings"]["feature_id"] = "edge-b"
    graph["nodes"].append(second)
    # 第二个失败拟合仅验证多角色失败传播，不将同一条边当成实际可测边对。
    e = evaluation(
        **{k: v for k, v in projection["evaluation"].items() if k not in {"format_id"}}
    )
    p_extent = extent_parameters(
        source=dict(
            kind="boundary",
            selection=dict(feature_id="projection", segment_ids=["window-edge"]),
        ),
        evaluation=e,
    )
    p_hole = hole_parameters(evaluation=e)
    p_pair = pair_parameters().model_copy(
        update={
            "evaluation": evaluation(**line["parameters"]["settings"]["evaluation"]),
            "query_position": e.origin,
            "direction": (0, 1, 0),
            "reference_feature_id": "edge",
            "target_feature_id": "edge-b",
        }
    )
    for key, kind, p in (
        ("extents", "measure-extents", p_extent),
        ("hole", "measure-hole", p_hole),
        ("pair", "measure-edge-pair", p_pair),
    ):
        graph["nodes"].append(
            dict(
                node_id=key,
                node_type_id="custom.metrology3d." + kind,
                parameters=dict(settings=p.model_dump(mode="json")),
            )
        )
    for a, b, c, d in (
        ("section", "features", "line-b", "features"),
        ("projection", "features", "extents", "features"),
        ("circle", "features", "hole", "features"),
        ("line", "features", "pair", "features"),
        ("line-b", "features", "pair", "features"),
        *(
            (key, "evidence", "preview", "evidence")
            for key in ("extents", "pair", "hole")
        ),
    ):
        graph["edges"].append(
            dict(
                edge_id=f"dimension-{len(graph['edges'])}",
                source_node_id=a,
                source_port=b,
                target_node_id=c,
                target_port=d,
            )
        )
    return cloud, (WorkflowGraphTemplate.model_validate(graph), app)


def check_sample_dimensions(body):
    """完整来源、几何质量和缺测保留；人工 ROI 不声称实体精度。"""
    check_sample_boundaries(body)
    evidence = MeasurementEvidence3d.model_validate(body["measurements"])
    assert len(evidence.items) == 7
    for item in evidence.items:
        assert all(s.source_point_count == POINTS for s in item.support)
        if item.kind == "measure-extents":
            assert (
                item.valid
                and 0 < item.value < 0.61
                and item.support[0].point_count == 44
            )
            assert all(c.source_index < POINTS for c in item.geometry.contacts)
        else:
            assert not item.valid and item.value is None and item.geometry is None
            assert item.reason == "insufficient_quality"


def test_dimensions_complete_sample_published_lifecycle(tmp_path, request):
    published_full_sample_lifecycle(
        tmp_path,
        request,
        prepare=sample_dimension_documents,
        check_body=check_sample_dimensions,
        report_name="dimensions-",
        point_limits=(500, 250),
    )
