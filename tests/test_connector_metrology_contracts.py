"""S01：契约、异常与显示适配边界，独立于图像提取算法。"""

import json

from jsonschema import Draft202012Validator
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.metrology import (
    FeatureObservations,
    GeometricFeature,
    ImageIdentity,
    LimitRule,
    NumericItem,
    NumericTable,
    PlanarCalibration,
    PoseObservation,
    ResourceReference,
)
from backend.nodes.core_nodes.support.measurement import (
    check_limits,
    numeric_table_to_value,
)
from custom_nodes.connector_nodes.shared.contracts import (
    PinLayout,
    PinObservations,
    MeasurementDefinition,
)


def identity(**changes):
    """构造同一帧的声明身份。"""
    return ImageIdentity(
        run_id="run-1",
        image_id="image-1",
        width=1280,
        height=800,
        dtype="uint8",
        **changes,
    )


def value(item_id="width", value=0.64, unit="millimeter", valid=True, reason=None):
    """构造普通数值项，不依赖 PIN 身份。"""
    return NumericItem(
        item_id=item_id, value=value, unit=unit, valid=valid, reason=reason
    )


@pytest.mark.parametrize(
    "raw", [float("nan"), float("inf"), float("-inf"), True, "0.64"]
)
def test_numeric_values_reject_nonfinite_and_implicit_coercion(raw):
    """非有限、布尔和文本不能成为测量数值。"""
    with pytest.raises(ValidationError):
        value(value=raw)


def test_numeric_validity_roundtrip_and_schema():
    """混合长度/角度逐项单位、无效 null 和 JSON Schema 保持一致。"""
    table = NumericTable(
        observation_id="o1",
        items=(
            value(),
            value("angle", 89.9999999, "degrees"),
            value("missing", None, valid=False, reason="pin_not_found"),
        ),
    )
    payload = table.model_dump(mode="json")
    Draft202012Validator(NumericTable.model_json_schema()).validate(payload)
    assert NumericTable.model_validate_json(json.dumps(payload)) == table
    bad = table.items[0].model_dump(mode="json") | {"valid": False}
    assert not Draft202012Validator(NumericItem.model_json_schema()).is_valid(bad)
    with pytest.raises(ValidationError):
        NumericItem.model_validate(bad)
    converted = numeric_table_to_value(table)
    assert converted["values"]["missing"] is None
    assert converted["values"]["angle"] == 89.9999999


def test_limits_boundaries_missing_units_and_non_connector_reuse():
    """毫米、温度、重量共用规则，闭区间不舍入，缺测与错单位不能放行。"""
    rules = (LimitRule(item_id="width", unit="millimeter", lower=0.59, upper=0.69),)
    for number, passed in (
        (0.69, True),
        (0.69000001, False),
        (0.59, True),
        (0.5899999, False),
    ):
        assert (
            check_limits(
                NumericTable(observation_id="o1", items=(value(value=number),)), rules
            )["passed"]
            is passed
        )
    for items in (
        (),
        (value(unit="pixel"),),
        (value(value=None, valid=False, reason="pin_not_found"),),
    ):
        assert not check_limits(NumericTable(observation_id="o1", items=items), rules)[
            "passed"
        ]
    table = NumericTable(
        observation_id="o1",
        items=(value("temperature", 37.5, "celsius"), value("weight", 150.0, "gram")),
    )
    assert check_limits(
        table,
        (
            LimitRule(item_id="temperature", unit="celsius", upper=40.0),
            LimitRule(item_id="weight", unit="gram", lower=140.0),
        ),
    )["passed"]
    assert not check_limits(table, ())["passed"]
    assert not check_limits(
        table, (LimitRule(item_id="weight", unit="gram", lower=140.0, enabled=False),)
    )["passed"]
    with pytest.raises(ValueError):
        check_limits(table, rules + rules)


def test_duplicate_and_invalid_limits_are_configuration_errors():
    """不允许重复数值 ID、无上下限、倒序或空开区间。"""
    with pytest.raises(ValueError):
        NumericTable(observation_id="o1", items=(value(), value()))
    for limits in (
        {},
        {"lower": 2.0, "upper": 1.0},
        {"lower": 1.0, "upper": 1.0, "include_upper": False},
    ):
        with pytest.raises(ValueError):
            LimitRule(item_id="a", unit="pixel", **limits)


def test_pose_cannot_absorb_scale_or_reuse_invalid_matrix():
    """缩放/镜像不是定位位姿；失败不能返回单位阵或上次矩阵。"""
    base = dict(image=identity(), reference_id="reference", reason=None, state="found")
    PoseObservation(
        **base,
        image_from_reference=((0.0, -1.0, 123.0), (1.0, 0.0, 42.0), (0.0, 0.0, 1.0)),
    )
    for matrix in (
        ((2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 1.0)),
        ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    ):
        with pytest.raises(ValueError):
            PoseObservation(**base, image_from_reference=matrix)
    with pytest.raises(ValueError):
        PoseObservation(
            **(base | {"state": "not_found", "reason": "low_score"}),
            image_from_reference=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        )


def test_pin_identity_empty_positions_and_observation_pairing():
    """缺首/末 PIN 不重排编号，设计留空允许记录占用，并拒绝错帧接线。"""
    pins = PinObservations(
        observation_id="o1",
        image=identity(),
        reference_id="reference",
        pins=[
            dict(
                pin_id="P01",
                row_id="R1",
                pin_type="normal",
                expected_present=True,
                nominal_image_point=(10.0, 10.0),
                state="not_found",
                center_image_point=None,
                reason="edge_not_found",
            ),
            dict(
                pin_id="P02",
                row_id="R1",
                pin_type="normal",
                expected_present=False,
                nominal_image_point=(30.0, 10.0),
                state="found",
                center_image_point=(30.0, 10.0),
                feature_ids=("p2.center",),
                reason=None,
            ),
            dict(
                pin_id="P03",
                row_id="R1",
                pin_type="normal",
                expected_present=True,
                nominal_image_point=(50.0, 10.0),
                state="not_found",
                center_image_point=None,
                reason="edge_not_found",
            ),
        ],
    )
    features = FeatureObservations(
        observation_id="o1",
        image=identity(),
        reference_id="reference",
        features=(
            GeometricFeature(
                feature_id="p2.center", kind="point", points=((30.0, 10.0),)
            ),
        ),
    )
    pins.require_matching_features(features)
    assert [p.pin_id for p in pins.pins] == ["P01", "P02", "P03"]
    for changed in (
        {"observation_id": "o2"},
        {"image": identity().model_copy(update={"image_id": "image-2"})},
        {"reference_id": "other"},
        {"features": ()},
    ):
        with pytest.raises(ValueError):
            pins.require_matching_features(features.model_copy(update=changed))


def test_layout_budgets_and_feature_coverage_contract():
    """越界配置不静默裁剪，边特征必须有有限观测范围。"""
    base = dict(
        reference_id="reference",
        pins=[dict(pin_id="P01", row_id="R1", pin_type="normal", center=(5.0, 5.0))],
        types=[dict(type_id="normal")],
    )
    PinLayout.model_validate(base)
    with pytest.raises(ValueError):
        PinLayout.model_validate(base | {"pins": base["pins"] * 2})
    with pytest.raises(ValueError):
        PinLayout.model_validate(base | {"types": [dict(type_id="other")]})
    with pytest.raises(ValueError):
        GeometricFeature(
            feature_id="line", kind="edge", points=((1.0, 1.0), (1.0, 1.0))
        )
    with pytest.raises(ValueError):
        MeasurementDefinition(item_id="width", kind="width", pin_a="P01")


def test_calibration_identity_and_degenerate_maps():
    """物理标定的单位/覆盖/版本摘要显式存在。"""
    ResourceReference(
        project_id="project-1",
        resource_id="calibration-1",
        version=1,
        sha256="a" * 64,
        kind="planar-calibration",
    )
    config = dict(
        image_width=1280,
        image_height=800,
        model="affine",
        unit="millimeter",
        plane_id="plane-1",
        valid_polygon=((0.0, 0.0), (100.0, 0.0), (100.0, 100.0)),
        fit_rms=0.0,
        validation_max_error=0.0,
    )
    PlanarCalibration(
        **config, world_from_image=((0.1, 0.0, 0.0), (0.0, 0.2, 0.0), (0.0, 0.0, 1.0))
    )
    with pytest.raises(ValueError):
        PlanarCalibration(
            **config,
            world_from_image=((0.0, 0.0, 0.0), (0.0, 0.2, 0.0), (0.0, 0.0, 1.0)),
        )


def test_real_catalog_and_executor_numeric_table_to_display():
    """用真实 Catalog、执行器、规则、转换及 Value Display 验证端口链路。"""
    from backend.contracts.workflows.workflow_graph import (
        WorkflowGraphTemplate,
        validate_node_definition_catalog,
    )
    from backend.nodes.core_catalog import get_core_workflow_payload_contracts
    from backend.nodes.core_nodes.io.preview.value_display import (
        CORE_NODE_SPEC as display,
    )
    from backend.nodes.core_nodes.logic.rules.check_limits import (
        CORE_NODE_SPEC as limits,
    )
    from backend.nodes.core_nodes.logic.value.numeric_table_to_value import (
        CORE_NODE_SPEC as convert,
    )
    from backend.service.application.workflows.graph_executor import (
        WorkflowGraphExecutor,
        WorkflowNodeRuntimeRegistry,
    )

    specs = (limits, convert, display)
    validate_node_definition_catalog(
        node_definitions=tuple(s.node_definition for s in specs),
        payload_contracts=get_core_workflow_payload_contracts(),
    )
    registry = WorkflowNodeRuntimeRegistry()
    for spec in specs:
        spec.register_handler(registry)
    template = WorkflowGraphTemplate.model_validate(
        {
            "template_id": "numeric-table-contract",
            "template_version": "0.1.8",
            "display_name": "Contract",
            "nodes": [
                {
                    "node_id": "limits",
                    "node_type_id": limits.node_definition.node_type_id,
                    "parameters": {
                        "rules": [
                            dict(
                                item_id="width",
                                unit="millimeter",
                                lower=0.59,
                                upper=0.69,
                            )
                        ]
                    },
                },
                {
                    "node_id": "convert",
                    "node_type_id": convert.node_definition.node_type_id,
                },
                {
                    "node_id": "display",
                    "node_type_id": display.node_definition.node_type_id,
                    "parameters": {
                        "fields": [
                            {
                                "path": "values.width",
                                "label": "Width",
                                "format": "number",
                                "precision": 3,
                            }
                        ]
                    },
                },
            ],
            "edges": [
                {
                    "edge_id": "e1",
                    "source_node_id": "convert",
                    "source_port": "value",
                    "target_node_id": "display",
                    "target_port": "value",
                }
            ],
            "template_inputs": [
                dict(
                    input_id=n,
                    display_name=n,
                    payload_type_id="numeric-table.v1",
                    target_node_id=n,
                    target_port="table",
                )
                for n in ("limits", "convert")
            ],
            "template_outputs": [
                dict(
                    output_id="result",
                    display_name="Result",
                    payload_type_id="value.v1",
                    source_node_id="limits",
                    source_port="summary",
                ),
                dict(
                    output_id="display",
                    display_name="Display",
                    payload_type_id="response-body.v1",
                    source_node_id="display",
                    source_port="body",
                ),
            ],
        }
    )
    table = NumericTable(observation_id="o1", items=(value(),)).model_dump(mode="json")
    result = WorkflowGraphExecutor(registry=registry).execute(
        template=template, input_values={"limits": table, "convert": table}
    )
    assert result.outputs["result"]["value"]["passed"] is True
    assert result.outputs["display"]["fields"][0]["value"] == 0.64
