"""真实目标行、格支持与四侧估计的分辨率审计，不能替代实体准确度。"""

import numpy as np
import pytest

from backend.contracts.workflows.envelope3d import RobustProfileSpans
from backend.contracts.workflows.evaluation3d import EvaluationPlane3d
from tests.integration.metrology3d.profile_stage_audit import audit_profile_stages
from tests.integration.metrology3d.test_metric_envelope import metric_settings


def rectangle_audit(*, mixed=False):
    """独立连续矩形四边为 3.2/6.8/3.4/8.6；仅有实测顶点，不伪造低侧。"""
    x, y = np.meshgrid(np.arange(3.225, 6.8, 0.05), np.arange(3.425, 8.6, 0.05))
    points = np.column_stack((x.ravel(), y.ravel(), np.ones(x.size)))
    if mixed:
        points = np.vstack((points, [4.25, 5.25, -1]))
    config = metric_settings(0.071, profiles=dict(min_observed_length=1))
    evaluation = EvaluationPlane3d(
        frame_id="fixture", length_unit="mm", origin=[0, 0, 0], rotation=np.eye(3)
    )
    mode = RobustProfileSpans(
        kind="robust-profile-spans",
        lower_quantile=0.02,
        upper_quantile=0.98,
        quantile_method="linear",
    )
    return audit_profile_stages(
        points,
        evaluation,
        config,
        mode,
        32_000_000,
        sources=np.arange(len(points), dtype=np.uint64) * 3 + 14745099,
    )


def test_true_rows_are_not_all_points_in_selected_cells():
    """低侧点落在同格不属于正高度目标，诊断不得误标为目标源行。"""
    report = rectangle_audit(mixed=True)
    assert len({r["target_source_sha256"] for r in report}) == 1
    for row in report:
        assert row["selected_cell_points"] == row["target_source_count"] + 1


def test_continuous_rectangle_resolution_and_missing_neighbor_evidence():
    """仅格边估计时误差受格宽约束，但不宣称缺测真实边已被恢复。"""
    for row in rectangle_audit():
        sides = row["actual"]["sides"]
        for side, truth in zip(sides, (3.2, 6.8, 3.4, 8.6)):
            assert abs(side["limit"] - truth) <= row["step"]
            assert side["method_counts"]["2"] == side["station_count"]
            for endpoint in side["endpoints"]:
                assert endpoint["neighbor_count"] == 0
                assert endpoint["neighbor_height"] is None
                assert endpoint["source_second_cell"] == endpoint["cell"]
                assert endpoint["adjacent_cell"] != endpoint["cell"]
        assert row["actual"]["width"] == pytest.approx(
            sides[1]["limit"] - sides[0]["limit"]
        )
