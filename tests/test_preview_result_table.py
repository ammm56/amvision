"""真实合成图片的结果表闭环及错帧拒绝；不依赖浏览器和部署服务。"""

from copy import deepcopy
import pytest

from backend.nodes import ExecutionImageRegistry
from backend.nodes.runtime_support import register_image_matrix
from backend.nodes.core_nodes.support.preview_results import validate_result_image
from backend.nodes.core_nodes.io.preview.value_preview import CORE_NODE_SPEC as PREVIEW
from backend.nodes.core_nodes.logic.rules.check_limits import CORE_NODE_SPEC as LIMITS
from backend.service.application.errors import InvalidRequestError
from tests.test_connector_nodes import source, request, dimensions, locate, measure


def test_missing_pin_table_keeps_values_limits_and_expected_geometry():
    """缺针无实测宽度，关联位置必须为名义点；表格使用本次公差原值。"""
    image, layout, _, _ = source("single10_front", "missing_middle")
    registry = ExecutionImageRegistry()
    payload = register_image_matrix(request(registry), image_matrix=image)
    found = locate(request(registry, {"layout":layout,"pose_mode":"fixed"}, {"image":payload}))
    measured = measure(request(registry, {"items":dimensions(layout)}, {"pins":found["pins"],"features":found["features"]}))
    rules = [dict(item_id=item["item_id"],unit=item["unit"],lower=0.,upper=40.00000000000001) for item in measured["measurements"]["items"]]
    checked = LIMITS.handler(request(registry, {"rules":rules}, {"table":measured["measurements"]}))
    table = PREVIEW.handler(request(registry, {"display_mode":"table","path":"items"}, {"value":checked["summary"],"geometry":measured["result_geometry"]}))["body"]
    assert table["type"] == "table-preview"
    assert all(row["upper"] == 40.00000000000001 for row in table["rows"])
    failed = [row for row in table["rows"] if not row["valid"]]
    assert failed and all(row["value"] is None and row["reason"] == "pin_not_found" for row in failed)
    shapes = {item["item_id"]:item for item in table["result_geometry"]["items"]}
    assert all(shapes[row["item_id"]]["kind"] == "expected-point" for row in failed)
    # 配对第二对象缺失时，不能把缺失位置标到仍然存在的第一对象。
    missing = next(pin for pin in found["pins"]["pins"] if pin["state"] != "found")
    present = next(pin for pin in found["pins"]["pins"] if pin["state"] == "found")
    paired = measure(request(registry, {"items":[{"item_id":"pair", "kind":"pitch", "pin_a":present["pin_id"], "pin_b":missing["pin_id"]}]}, {"pins":found["pins"], "features":found["features"]}))
    assert paired["result_geometry"]["value"]["items"][0]["points"] == [missing["nominal_image_point"]]
    assert validate_result_image(table, request(registry), payload) is table
    wrong_run = request(registry)
    wrong_run.execution_metadata["workflow_run_id"] = "another-run"
    with pytest.raises(InvalidRequestError,match="不匹配"):
        validate_result_image(table, wrong_run, payload)
    with pytest.raises(InvalidRequestError,match="不匹配"):
        validate_result_image(table, request(registry), {**payload,"image_handle":"other-image"})
    duplicate = deepcopy(table)
    duplicate["rows"].append(duplicate["rows"][0])
    with pytest.raises(InvalidRequestError):
        validate_result_image(duplicate, request(registry), payload)
    old = deepcopy(measured["result_geometry"])
    old["value"]["observation_id"] = "old-observation"
    with pytest.raises(InvalidRequestError,match="同一次"):
        PREVIEW.handler(request(registry, {"display_mode":"table","path":"items"}, {"value":checked["summary"],"geometry":old}))


def test_generic_table_supports_temperature_and_weight_without_geometry():
    """普通行业无关对象数组可选择列；JSON 模式和错误路径行为保持。"""
    registry = ExecutionImageRegistry()
    value = {"value":{"items":[{"name":"temperature","value":-12.123456789},{"name":"weight","value":None}]}}
    result = PREVIEW.handler(request(registry,{"display_mode":"table","path":"items","columns":[{"key":"value","label":"Value"}]},{"value":value}))["body"]
    assert result["rows"] == value["value"]["items"]
    assert result["columns"] == [{"key":"value","label":"Value"}]
    assert "result_geometry" not in result
    assert PREVIEW.handler(request(registry,{}, {"value":value}))["body"]["value"] == value["value"]
    missing = PREVIEW.handler(request(registry,{"display_mode":"table","path":"absent"},{"value":value}))["body"]
    assert missing["rows"] == [] and missing["missing_path"]
    for bad in ({"value":2}, {"value":[1]}, {"value":[{}]*8193}):
        with pytest.raises(InvalidRequestError):
            PREVIEW.handler(request(registry,{"display_mode":"table"},{"value":bad}))
    with pytest.raises(InvalidRequestError,match="Columns"):
        PREVIEW.handler(request(registry,{"display_mode":"table","path":"items","columns":[{"key":"value","label":"V"}]*2},{"value":value}))


def test_explicit_column_formats_preserve_values_and_reject_unknown_formats():
    """列语义只影响显示，原始数值和普通布尔值均不转换。"""
    registry = ExecutionImageRegistry()
    value = {"value": [{"passed": True, "value": .6900000000000001}]}
    columns = [{"key": "passed", "label": "Result", "format": "result"}]
    body = PREVIEW.handler(request(registry, {"display_mode": "table", "columns": columns}, {"value": value}))["body"]
    assert body["columns"] == columns and body["rows"] == value["value"]
    with pytest.raises(InvalidRequestError, match="Format"):
        PREVIEW.handler(request(registry, {"display_mode": "table", "columns": [{**columns[0], "format": "custom-script"}]}, {"value": value}))
