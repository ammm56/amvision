"""同线多基准复用单项内核，逐项质量、来源与持久证据等价。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.measurement3d_multi_reference import (
    MultiReferenceStepParameters,
)
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.measure_step import measure_step
from custom_nodes.metrology3d_nodes.shared.measure_step_node import measure_step_node
from tests.test_metrology3d_measurement_contracts import (
    step_parameters,
    measurement_policy,
)
from tests.test_metrology3d_pose_query import tilted_fixture, query


def parameters():
    """两项共享几何，第二项故意使用不同且不通过的独立质量条件。"""
    p = step_parameters(query=query()).model_dump(mode="json")
    m = p["mode"]
    row = {
        k: v for k, v in m.items() if k not in {"kind", "query", "target_feature_id"}
    }
    return dict(
        frame_id=p["frame_id"],
        length_unit=p["length_unit"],
        mode=dict(
            kind="directional-references",
            query=m["query"],
            target_feature_id=m["target_feature_id"],
            items=[
                dict(item_id="H", **row),
                dict(
                    item_id="Z",
                    **{
                        **row,
                        "quality_policy": measurement_policy(
                            target_count={"lower": 9999}
                        ),
                    },
                ),
            ],
        ),
    )


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_same_line_preserves_each_result_and_serialized_evidence(dtype):
    scope, runtime, cloud, groups, pose, *_ = tilted_fixture(dtype)
    try:
        p = MultiReferenceStepParameters.model_validate(parameters())
        expected = [
            measure_step(
                runtime, item, groups=groups, pose=pose, cancel=lambda: None
            ).items[0]
            for item in p.measurements()
        ]
        result = measure_step_node(
            runtime, p, groups=groups, pose=pose, cancel=lambda: None
        )
        assert result.items == tuple(expected)
        assert result.items[0].valid and result.items[0].value == pytest.approx(
            5.05, abs=3e-6
        )
        assert not result.items[1].valid and result.items[1].value is None
        assert (
            MeasurementEvidence3d.model_validate_json(result.model_dump_json())
            == result
        )
        assert [i.item_id for i in result.numeric_table().items] == ["H", "Z"]
        assert "cloud_id" not in result.model_dump_json()
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize(
    "failure", ["duplicate", "same_feature", "missing_quality", "empty", "extra"]
)
def test_rejects_incomplete_or_conflicting_items(failure):
    p = parameters()
    if failure == "duplicate":
        p["mode"]["items"][1]["item_id"] = "H"
    if failure == "same_feature":
        p["mode"]["items"][1]["reference_feature_id"] = "target"
    if failure == "missing_quality":
        p["mode"]["items"][1]["quality_policy"]["rules"] = []
    if failure == "empty":
        p["mode"]["items"] = []
    if failure == "extra":
        p["item_id"] = "hidden"
    with pytest.raises(ValidationError):
        MultiReferenceStepParameters.model_validate(p)


def test_preflights_all_sources_and_rejects_hidden_ports(monkeypatch):
    import custom_nodes.metrology3d_nodes.shared.measure_step_node as module

    scope, runtime, cloud, groups, pose, *_ = tilted_fixture()
    before = runtime.budget.used
    p = parameters()
    p["mode"]["items"][1]["reference_feature_id"] = "missing"
    called = []
    monkeypatch.setattr(
        module, "measure_step", lambda *args, **kwargs: called.append(True)
    )
    try:
        with pytest.raises(InvalidRequestError, match="不存在"):
            measure_step_node(
                runtime,
                MultiReferenceStepParameters.model_validate(p),
                groups=groups,
                pose=pose,
                cancel=lambda: None,
            )
        assert not called and runtime.budget.used == before
        with pytest.raises(InvalidRequestError, match="统计点云"):
            measure_step_node(
                runtime,
                MultiReferenceStepParameters.model_validate(parameters()),
                groups=groups,
                reference=cloud,
                pose=pose,
                cancel=lambda: None,
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_cancel_after_first_measurement_does_not_return_partial_rows(monkeypatch):
    import custom_nodes.metrology3d_nodes.shared.measure_step_node as module

    scope, runtime, cloud, groups, pose, *_ = tilted_fixture()
    finished = []
    original = module.measure_step

    def measured(*args, **kwargs):
        result = original(*args, **kwargs)
        finished.append(result)
        return result

    def cancel():
        if finished:
            raise InterruptedError("cancel")

    monkeypatch.setattr(module, "measure_step", measured)
    try:
        with pytest.raises(InterruptedError):
            measure_step_node(
                runtime,
                MultiReferenceStepParameters.model_validate(parameters()),
                groups=groups,
                pose=pose,
                cancel=cancel,
            )
        assert len(finished) == 1
        with runtime.borrow(cloud):
            pass
    finally:
        assert not scope.close() and runtime.budget.used == 0
