"""工业二维视觉共享 payload 契约回归测试。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import (
    require_camera_calibration_payload,
    require_localizations_payload,
    require_points_payload,
    require_stereo_calibration_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.transforms import (
    require_planar_transform_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.validators import require_number
from custom_nodes.opencv_nodes.shared.workflow.payload_contracts import (
    load_shared_opencv_payload_contracts_payload,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "industrial_vision_payloads.v1.fixture.json"
)
PAYLOAD_REQUIRE_FUNCTIONS = {
    "points.v1": require_points_payload,
    "localizations.v1": require_localizations_payload,
    "camera-calibration.v1": require_camera_calibration_payload,
    "stereo-calibration.v1": require_stereo_calibration_payload,
}


def _load_fixture() -> dict[str, object]:
    """读取工业视觉 payload fixture。"""

    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _load_contract_schemas() -> dict[str, dict[str, object]]:
    """按 payload_type_id 索引共享 JSON Schema。"""

    return {
        str(item["payload_type_id"]): item["json_schema"]
        for item in load_shared_opencv_payload_contracts_payload()
    }


def test_industrial_payload_contracts_accept_frozen_valid_fixtures() -> None:
    """验证四类新 payload 同时通过 JSON Schema 与运行时语义校验。"""

    fixture = _load_fixture()
    schemas = _load_contract_schemas()
    valid_payloads = fixture["valid"]
    assert isinstance(valid_payloads, dict)

    for payload_type_id, require_function in PAYLOAD_REQUIRE_FUNCTIONS.items():
        schema = schemas[payload_type_id]
        Draft202012Validator.check_schema(schema)
        payload = valid_payloads[payload_type_id]
        Draft202012Validator(schema).validate(payload)
        assert require_function(payload) == payload


def test_industrial_payload_contracts_reject_frozen_invalid_fixtures() -> None:
    """验证每类契约至少有一个固定的负向 Schema fixture。"""

    fixture = _load_fixture()
    schemas = _load_contract_schemas()
    invalid_payloads = fixture["invalid"]
    assert isinstance(invalid_payloads, dict)

    for payload_type_id, invalid_cases in invalid_payloads.items():
        assert isinstance(invalid_cases, list) and invalid_cases
        validator = Draft202012Validator(schemas[payload_type_id])
        for invalid_case in invalid_cases:
            with pytest.raises(ValidationError):
                validator.validate(invalid_case["payload"])


def test_runtime_validators_reject_cross_field_and_non_finite_values() -> None:
    """验证 JSON Schema 无法表达的 count、坐标方向和有限数值约束。"""

    fixture = _load_fixture()
    valid_payloads = fixture["valid"]
    assert isinstance(valid_payloads, dict)

    invalid_points = copy.deepcopy(valid_payloads["points.v1"])
    invalid_points["count"] = 99
    with pytest.raises(InvalidRequestError, match="count"):
        require_points_payload(invalid_points)

    invalid_localizations = copy.deepcopy(valid_payloads["localizations.v1"])
    invalid_localizations["items"][0]["transform"]["target_coordinate_space"] = (
        "different-space"
    )
    with pytest.raises(InvalidRequestError, match="target_coordinate_space"):
        require_localizations_payload(invalid_localizations)

    with pytest.raises(InvalidRequestError, match="有限数值"):
        require_number(float("nan"), field_name="value")
    with pytest.raises(InvalidRequestError, match="有限数值"):
        require_number(float("inf"), field_name="value")


def test_planar_transform_requires_explicit_source_and_target_spaces() -> None:
    """验证 planar-transform 不再允许省略变换方向。"""

    fixture = _load_fixture()
    localization = fixture["valid"]["localizations.v1"]["items"][0]
    transform = copy.deepcopy(localization["transform"])
    normalized = require_planar_transform_payload(transform)
    assert normalized["source_coordinate_space"] == "reference-image-pixels"
    assert normalized["target_coordinate_space"] == "source-image-pixels"

    transform.pop("source_coordinate_space")
    with pytest.raises(InvalidRequestError, match="source_coordinate_space"):
        require_planar_transform_payload(transform)
