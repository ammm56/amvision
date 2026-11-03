"""严格三维字段、布局、显式预算与所有权边界。"""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.point_cloud import (
    CloudBufferDescriptor,
    CloudField,
    CloudFileOptions,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from tests.point_cloud_support import options, policy, spatial


def descriptor():
    """两个 float32 XYZ 点的完整布局。"""
    return {
        "format_id": "amvision.point-cloud-buffer.v1",
        "point_count": 2,
        "content_length": 24,
        "fields": [
            {
                "name": "positions",
                "semantic": "position",
                "dtype": "float32",
                "components": 3,
                "unit": None,
                "count": 2,
                "offset_bytes": 0,
                "byte_length": 24,
            }
        ],
        "spatial": spatial().model_dump(mode="json"),
    }


def test_descriptor_and_json_roundtrip():
    value = CloudBufferDescriptor.model_validate(descriptor())
    assert CloudBufferDescriptor.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize(
    "key,value",
    [
        ("point_count", True),
        ("content_length", 25),
        ("content_length", 1_000_000_001),
        ("point_count", 0),
        ("point_count", 2.0),
        ("run_id", "forged"),
    ],
)
def test_descriptor_rejects_invalid_envelope(key, value):
    data = descriptor()
    data[key] = value
    with pytest.raises(ValidationError):
        CloudBufferDescriptor.model_validate(data)


@pytest.mark.parametrize(
    "key,value",
    [
        ("dtype", "float64"),
        ("components", 2),
        ("unit", "mm"),
        ("count", 1),
        ("offset_bytes", 1),
        ("byte_length", 20),
        ("name", "other"),
        ("semantic", "scalar"),
    ],
)
def test_descriptor_rejects_inconsistent_fields(key, value):
    data = descriptor()
    data["fields"][0][key] = value
    with pytest.raises(ValidationError):
        CloudBufferDescriptor.model_validate(data)


def test_mapping_cannot_drop_precision_or_duplicate_source():
    data = options().model_dump(mode="json")
    data["profile_version"] = True
    with pytest.raises(ValidationError):
        CloudFileOptions.model_validate(data)
    data["profile_version"] = 1
    data["field_mapping"][0]["source_names"] = ["x", "x", "z"]
    with pytest.raises(ValidationError):
        CloudFileOptions.model_validate(data)


def test_unknown_units_and_axes_are_consistent():
    data = spatial().model_dump(mode="json")
    data["length_unit"] = None
    with pytest.raises(ValidationError):
        type(spatial()).model_validate(data)
    data["unit_source"] = "unknown"
    assert type(spatial()).model_validate(data).length_unit is None


def test_reserved_fields_and_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        CloudField(
            name="positions",
            semantic="scalar",
            dtype="float32",
            components=1,
            unit=None,
        )
    with pytest.raises(ValidationError):
        policy(extra_limit=1)
    with pytest.raises(ValidationError):
        policy(max_live_array_bytes=2)


def test_budget_rejection_does_not_leak_and_close_is_idempotent():
    budget = CloudArrayBudget(32)
    token = budget.reserve(24)
    with pytest.raises(InvalidRequestError):
        budget.reserve(9)
    assert budget.used == 24
    token.shrink(12)
    assert budget.used == 12
    token.close()
    token.close()
    assert budget.used == 0
    with pytest.raises(RuntimeError):
        token.shrink(0)


def test_parallel_reservations_cannot_over_admit():
    budget = CloudArrayBudget(24)

    def allocate(_index):
        try:
            return budget.reserve(24)
        except InvalidRequestError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        tokens = list(pool.map(allocate, range(10)))
    assert sum(token is not None for token in tokens) == 1
    for token in tokens:
        if token:
            token.close()
    assert budget.used == 0


def test_scope_owns_arrays_and_active_borrow_prevents_premature_release():
    budget = CloudArrayBudget(24)
    owner = OwnedCloudArrays(
        {"positions": np.zeros((2, 3), dtype="float32")}, budget.reserve(24)
    )
    scope = ResourceScope(kind="workflow")
    scope.register("cloud", owner, lambda value: value.close())
    with owner.borrow() as arrays:
        with pytest.raises(ValueError):
            arrays["positions"][0, 0] = 1
        with pytest.raises(RuntimeError):
            owner.close()
        assert budget.used == 24
    assert scope.close() == ()
    assert owner.closed and budget.used == 0
    assert scope.close() == ()
    with pytest.raises(RuntimeError):
        with owner.borrow():
            pass


def test_padding_and_organization_contract():
    data = descriptor()
    data["fields"].insert(
        0,
        {
            "name": "validity",
            "semantic": "validity",
            "dtype": "uint8",
            "components": 1,
            "unit": "1",
            "count": 2,
            "offset_bytes": 0,
            "byte_length": 2,
        },
    )
    data["fields"][1]["offset_bytes"] = 4
    data["content_length"] = 28
    CloudBufferDescriptor.model_validate(data)
    broken = deepcopy(data)
    broken["fields"][1]["offset_bytes"] = 8
    with pytest.raises(ValidationError):
        CloudBufferDescriptor.model_validate(broken)
