"""同次完整证据、真实资源归属、容量与取消；不以显示结果生成真值。"""

import base64
from hashlib import sha256

import numpy as np
import pytest

from backend.contracts.workflows.boundary3d_observations import BoundaryEvidence
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.execution_policy import (
    CloudPreviewPolicy,
)
from custom_nodes.metrology3d_nodes.shared.boundary_debug import (
    BoundaryCapture,
    capture_display,
)
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes.metrology3d_nodes.shared.boundary_assets import (
    freeze_boundary,
    restore_boundary,
)
from tests.integration.metrology3d.test_envelope_runtime import (
    fixture,
    extract,
    extents,
)
from tests.integration.metrology3d.test_boundary_extraction import (
    extract as extract_array,
    extract_parameters,
)


def preview_policy(**changes):
    """测试容量独立显式配置，不写入生产默认。"""
    return CloudPreviewPolicy(
        **{
            **dict(
                max_points=10000,
                max_data_bytes=2_000_000,
                max_body_bytes=8_000_000,
                max_working_bytes=16_000_000,
            ),
            **changes,
        }
    )


def make_capture(values, p, path, **changes):
    """真实 Runtime/Scope，临时正文写入本用例目录。"""
    _, runtime, cloud, *_ = values
    return BoundaryCapture(
        runtime,
        cloud,
        p,
        policy=preview_policy(**changes),
        directory=path,
        node_id="extract",
        invocation_id="call",
        cancel=lambda: None,
    )


def captured(values, p, measured, capture):
    """沿正式提取入口，不替换内核和基准来源。"""
    _, runtime, cloud, groups, pose, *_ = values
    return extract_boundary(
        runtime,
        cloud,
        p,
        contour_plane=groups[0].items[0],
        pose=pose,
        measurement=measured,
        measurement_planes=tuple(g.items[0] for g in groups),
        cancel=lambda: None,
        capture=capture,
    )


def arrays(display):
    """独立解码描述符，核对冻结字节与摘要。"""
    raw = base64.b64decode(display.data.content, validate=True)
    assert sha256(raw).hexdigest() == display.data.checksum
    return {
        f.name: np.frombuffer(
            raw,
            dtype=np.dtype(f.dtype).newbyteorder("<"),
            count=f.count * f.components,
            offset=f.offset,
        ).reshape(f.count, f.components)
        for f in display.data.fields
    }


@pytest.mark.parametrize("partition", ["grid-connected", "distance-connected"])
def test_complete_grid_matches_independent_truth_and_does_not_change_measurement(
    tmp_path, partition
):
    values, p, measured = fixture(partition)
    scope, runtime, *_ = values
    try:
        before = extract(values, p, measured)
        capture = make_capture(values, p, tmp_path)
        after = captured(values, p, measured, capture)
        left, right = before.items[0], after.items[0]
        assert BoundaryEvidence.model_validate(
            left.model_dump(exclude={"support"})
        ) == BoundaryEvidence.model_validate(
            right.model_dump(exclude={"support", "debug_capture"})
        )
        assert extents(runtime, before) == extents(runtime, after)
        display = capture_display(
            runtime, right, max_bytes=8_000_000, cancel=lambda: None
        )
        data = arrays(display)
        assert display.selection_complete and display.state == "ready"
        assert data["counts"].shape == (120, 1)
        np.testing.assert_array_equal(data["counts"], 1)
        expected = np.asarray(
            [3 <= i < 7 and 3 <= j < 9 for i in range(10) for j in range(12)]
        )
        np.testing.assert_array_equal(data["selected"][:, 0], expected)
        np.testing.assert_array_equal(data["foreground"][:, 0], expected)
        assert set(data["input_source_indices"][:, 0]) == set(range(162, 282))
        assert len(data["profile_offsets"]) == 5
        assert freeze_boundary(right.support, after, "derived") == freeze_boundary(
            left.support, before, "derived"
        )
        restored = restore_boundary(
            right.support, freeze_boundary(right.support, after, "derived")
        )
        assert restored.items[0].debug_capture is None
        assert capture._stream is not None
    finally:
        scope.close()
    assert runtime.budget.used == 0 and capture._quota.used == 0
    assert not list(tmp_path.iterdir())
    with pytest.raises((InvalidRequestError, RuntimeError)):
        capture_display(runtime, right, max_bytes=8_000_000, cancel=lambda: None)


def test_capture_capacity_and_wrong_identity_do_not_hide_measurement(tmp_path):
    values, p, measured = fixture()
    scope, runtime, *_ = values
    try:
        capture = make_capture(values, p, tmp_path, max_data_bytes=32)
        result = captured(values, p, measured, capture)
        item = result.items[0]
        assert item.valid
        display = capture_display(
            runtime, item, max_bytes=8_000_000, cancel=lambda: None
        )
        assert display.state == "unavailable" and display.reason == "debug_size_limit"
        assert capture._stream is None and capture._quota.used == 0
        changed = item.model_copy(
            update={
                "debug_capture": item.debug_capture.model_copy(
                    update={"invocation_id": "other"}
                )
            }
        )
        with pytest.raises(InvalidRequestError, match="身份"):
            capture_display(runtime, changed, max_bytes=8_000_000, cancel=lambda: None)
    finally:
        scope.close()


def test_candidates_include_unselected_and_early_selection_is_not_complete(tmp_path):
    values, _, _ = fixture()
    scope, runtime, cloud, *_ = values
    p = extract_parameters()
    capture = make_capture(values, p, tmp_path)
    capture.evaluation, capture.working_limit = p.evaluation, 2_000_000
    points = np.asarray(
        [
            (x + shift, y, 0)
            for shift in (0, 10, 20)
            for x in range(3)
            for y in range(3)
        ],
        dtype=np.float32,
    )
    capture.source_rows = np.arange(len(points), dtype="<u8")
    try:
        before = extract_array(points, p)
        after = extract_array(points, p, capture=capture)
        assert before.reason == after.reason == "target_ambiguous"
        capture.finish(after.reason)
        display = capture.display(max_bytes=8_000_000, cancel=lambda: None)
        data = arrays(display)
        assert display.state == "ready" and not display.selection_complete
        assert len(data["candidate_closed"]) == 3
        assert len(data["candidate_positions"]) == 24
        assert set(data["input_source_indices"][:, 0]) == set(range(27)) - {4, 13, 22}
        assert len(data["selection_events"]) == 2
        assert after.positions is None and after.topology is None
    finally:
        scope.close()
    assert not list(tmp_path.iterdir())


def test_cancel_during_capture_releases_file_and_quota(tmp_path):
    values, p, measured = fixture()
    scope, runtime, *_ = values
    capture = make_capture(values, p, tmp_path)

    def cancelled():
        raise InterruptedError("cancelled")

    capture.cancel = cancelled
    try:
        with pytest.raises(InterruptedError):
            captured(values, p, measured, capture)
        assert capture._closed and capture._quota.used == 0
        assert not list(tmp_path.iterdir())
    finally:
        scope.close()
    assert runtime.budget.used == 0


def test_missing_cells_closing_and_profile_gaps_are_captured_without_filling(tmp_path):
    """缺失整列的独立格阵：连接格有标签但没有观测，剖面跨缺口断开。"""
    from tests.test_metrology3d_envelope import points, settings, extract as kernel
    from backend.contracts.workflows.evaluation3d import EvaluationPlane3d

    values, p, _ = fixture()
    scope = values[0]
    capture = make_capture(values, p, tmp_path)
    capture.working_limit = 2_000_000
    capture.evaluation = EvaluationPlane3d(
        frame_id="fixture",
        length_unit="mm",
        origin=[0, 0, 0],
        rotation=np.eye(3).tolist(),
    )
    original = points()
    rows = np.flatnonzero(original[:, 1] != 5.5)
    try:
        capture.put("input_source_indices", rows, dtype="uint64")
        result = kernel(
            original[rows],
            settings(selection=dict(closing_radius_cells=1)),
            capture=capture,
        )
        capture.finish(result.reason)
        data = arrays(capture.display(max_bytes=8_000_000, cancel=lambda: None))
        missing = np.arange(5, 120, 12)
        assert not data["counts"][missing].any()
        assert not data["selected"][missing].any()
        assert data["grouped"][4 * 12 + 5, 0] == 1
        assert data["profile_breaks"][2, 0] == 1
        np.testing.assert_array_equal(data["input_source_indices"][:, 0], rows)
    finally:
        scope.close()


def test_temp_body_corruption_is_not_reported_as_capacity_failure(tmp_path):
    """冻结后正文损坏明确拒绝，不吞为诊断容量不足。"""
    values, p, measured = fixture()
    try:
        capture = make_capture(values, p, tmp_path)
        captured(values, p, measured, capture)
        capture._stream.seek(0)
        capture._stream.write(b"broken")
        with pytest.raises(ValueError, match="摘要"):
            capture.display(max_bytes=8_000_000, cancel=lambda: None)
    finally:
        values[0].close()


def test_event_finalization_allocation_failure_is_attachment_only(
    tmp_path, monkeypatch
):
    """封口分配失败也释放文件和额度，不改变已经得到的测量结论。"""
    values, p, _ = fixture()
    try:
        capture = make_capture(values, p, tmp_path)
        capture.working_limit = 2_000_000
        capture.event(0, 0, 1, 10)

        def fail(*args, **kwargs):
            raise MemoryError()

        monkeypatch.setattr(np, "asarray", fail)
        assert capture.finish("target_ambiguous") == capture.identity
        display = capture.display(max_bytes=8_000_000, cancel=lambda: None)
        assert display.state == "unavailable"
        assert display.reason == "debug_allocation_failed"
        assert display.measurement_reason == "target_ambiguous"
        assert capture._quota.used == 0
        assert not list(tmp_path.iterdir())
    finally:
        values[0].close()


def test_roi_hit_rejected_by_closed_condition_is_not_marked_selected(tmp_path):
    """候选在 ROI 内，但闭合条件不符，记录拒绝而非命中。"""
    from custom_nodes.metrology3d_nodes.shared.boundary_targets import select_targets
    from custom_nodes.metrology3d_nodes.shared.boundary_topology import OrderedSegment

    values, _, _ = fixture()
    p = extract_parameters()
    capture = make_capture(values, p, tmp_path)
    capture.working_limit = 2_000_000
    try:
        reason, *_ = select_targets(
            np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
            [OrderedSegment(np.array([0, 1]), False)],
            p,
            max_working_bytes=2_000_000,
            cancel=lambda: None,
            capture=capture,
        )
        assert reason == "target_not_found"
        assert capture.events == [(0, 0, 2, 2)]
    finally:
        values[0].close()


def test_profile_capture_allocation_failure_releases_owner(tmp_path, monkeypatch):
    """剖面冻结附加分配失败只使附件不可用，原剖面不被修改。"""
    from custom_nodes.metrology3d_nodes.shared.boundary_debug import capture_profiles

    values, p, _ = fixture()
    capture = make_capture(values, p, tmp_path)
    capture.working_limit = 2_000_000
    points = np.array([[0.0, 0.0, 0.0]])
    original = points.copy()

    def fail(*args, **kwargs):
        raise MemoryError()

    try:
        monkeypatch.setattr(np, "zeros", fail)
        capture_profiles(
            capture,
            points,
            [dict(start=0, count=1, profile=dict(breaks=[]))],
            [(None, (0, 0), (0, 0), 0.0, 0)],
            1,
        )
        assert capture.reason == "debug_allocation_failed"
        assert capture._quota.used == 0
        assert not list(tmp_path.iterdir())
        np.testing.assert_array_equal(points, original)
    finally:
        values[0].close()
