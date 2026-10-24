"""完整现场输入经过发布、Trigger 和真实节点；人工 ROI 不作尺寸真值。"""

import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.test_boundary_extraction import extract_parameters
from tests.integration.metrology3d.test_published_runtime import (
    published_full_sample_lifecycle,
)
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import spatial
from tests.test_metrology3d_boundary_contracts import (
    circle_parameters,
    evaluation,
    line_parameters,
)


def sample_boundary_documents(cloud, path):
    """只读完整数组确定与既有内核验收一致的测试 ROI，不裁小输入。"""
    points = np.memmap(path, mode="r", dtype="<f4", shape=(cloud.point_count, 3))
    try:
        counts = [
            int(np.isfinite(points[start : start + 65536]).all(axis=1).sum())
            for start in range(0, cloud.point_count, 65536)
        ]
        remaining = sum(counts) // 2
        for block, count in enumerate(counts):
            if remaining < count:
                start = block * 65536
                valid = np.flatnonzero(
                    np.isfinite(points[start : start + 65536]).all(axis=1)
                )
                center = points[start + valid[remaining]].astype(float).tolist()
                break
            remaining -= count
        else:
            raise AssertionError("完整样本没有有效位置")
    finally:
        points._mmap.close()
    region = dict(
        roi_id="test-window",
        rois=[
            dict(
                roi_id="test-window",
                kind="cylinder",
                frame_id="fixture",
                length_unit="mm",
                geometry=dict(center=center, axis=[0, 0, 1], radius=0.3, length=1),
            )
        ],
    )
    common = dict(
        evaluation=evaluation(origin=center),
        region=region,
        surface=dict(
            alpha_radius=0.08,
            max_edge_length=0.15,
            max_normal_step=0.1,
            min_projected_area=1e-8,
        ),
    )
    projection = extract_parameters(
        **common,
        feature_id="projection",
        targets=[
            dict(segment_id="window-edge", region=region, closed=True, role="unknown")
        ],
    )
    section = extract_parameters(
        **common,
        feature_id="section",
        method=dict(
            kind="section", origin=center, normal=[1, 0, 0], numeric_tolerance=1e-9
        ),
        targets=[dict(segment_id="section", region=region, closed=False, role="open")],
    )
    line = line_parameters(
        selection=dict(feature_id="section", segment_ids=["section"]),
        evaluation=evaluation(
            origin=center, rotation=[[0, 0, 1], [1, 0, 0], [0, 1, 0]]
        ),
        positive_direction=[0, 1, 0],
    )
    circle = circle_parameters(
        selection=dict(feature_id="projection", segment_ids=["window-edge"]),
        evaluation=evaluation(origin=center),
    )
    template, app = cloud_documents()
    graph = template.model_dump(mode="json")
    for label, extract, fit, kind in (
        ("projection", projection, circle, "circle"),
        ("section", section, line, "line"),
    ):
        graph["nodes"].extend(
            [
                dict(
                    node_id=label,
                    node_type_id="custom.metrology3d.extract-boundary",
                    parameters=dict(settings=extract.model_dump(mode="json")),
                ),
                dict(
                    node_id=kind,
                    node_type_id="custom.metrology3d.fit-" + kind,
                    parameters=dict(settings=fit.model_dump(mode="json")),
                ),
            ]
        )
        for source, source_port, target, target_port in (
            ("filter", "cloud", label, "cloud"),
            (label, "features", kind, "features"),
            (label, "features", "preview", "features"),
            (kind, "features", "preview", "features"),
        ):
            graph["edges"].append(
                dict(
                    edge_id=f"{source}-{target}",
                    source_node_id=source,
                    source_port=source_port,
                    target_node_id=target,
                    target_port=target_port,
                )
            )
    return cloud.model_copy(update={"spatial": spatial()}), (
        WorkflowGraphTemplate.model_validate(graph),
        app,
    )


def check_sample_boundaries(body):
    """核对完整链路与已有全样本内核证据，质量不合格不能显示有效候选。"""
    features = {item["feature_id"]: item for item in body["geometry"]["curves"]}
    assert set(features) == {"projection", "section", "edge", "circle"}
    for name, count, vertex_kind in (
        ("projection", 44, "source"),
        ("section", 20, "generated"),
    ):
        feature = features[name]
        assert feature["valid"] and feature["support_point_count"] == count
        assert feature["vertex_kind"] == vertex_kind
    line = features["edge"]
    assert not line["valid"] and line["geometry"] is None and not line["intervals"]
    metrics = {item["item_id"]: item for item in line["quality"]["metrics"]["items"]}
    assert metrics["rms"]["value"] == pytest.approx(0.015525559422087208, abs=1e-10)
    for name in ("edge", "circle"):
        feature = features[name]
        assert feature["valid"] == feature["quality"]["usable"]
        assert (feature["geometry"] is not None) == feature["valid"]
        assert not feature["valid"], "当前人工窗口不满足原测试质量，不得放宽门禁"


def test_boundary_published_full_sample_and_lifecycle(tmp_path, request):
    """Windows .NET、Ubuntu 协议客户端各按支持范围覆盖同一正式运行链。"""
    published_full_sample_lifecycle(
        tmp_path,
        request,
        prepare=sample_boundary_documents,
        check_body=check_sample_boundaries,
        report_name="boundary-",
        # 原总显示预算 1000 点不变，为完整曲线证据留出容量。
        point_limits=(500, 250),
    )
