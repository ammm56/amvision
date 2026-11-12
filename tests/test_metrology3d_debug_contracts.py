"""I2 捕获不改变测量参数；运行引用与有界显示严格分离。"""

import pytest
from pydantic import ValidationError

from backend.contracts.workflows.edge_extraction import BoundaryExtractionNodeParameters
from backend.contracts.workflows.boundary3d_debug import (
    DebugBinary,
    BoundaryDebugReference,
)
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from tests.integration.metrology3d.test_boundary_extraction import extract_parameters


def test_capture_is_strict_off_by_default_and_outside_method():
    """不隐式启用、不接受字符串 bool，不把显示开关写入方法摘要。"""
    settings = extract_parameters()
    disabled = BoundaryExtractionNodeParameters(settings=settings)
    enabled = BoundaryExtractionNodeParameters(settings=settings, capture_debug=True)
    assert disabled.capture_debug is False
    assert parameter_digest(disabled.settings) == parameter_digest(enabled.settings)
    with pytest.raises(ValidationError):
        BoundaryExtractionNodeParameters(settings=settings, capture_debug="true")


def test_reference_requires_call_identity():
    """只有 feature_id 不够定位本次附件。"""
    fields = dict(
        capture_id="c",
        run_id="r",
        node_id="n",
        invocation_id="i",
        observation_id="o",
        feature_id="f",
        parameters_sha256="a" * 64,
    )
    ref = BoundaryDebugReference(**fields)
    assert ref == BoundaryDebugReference.model_validate_json(ref.model_dump_json())
    for field in fields:
        with pytest.raises(ValidationError):
            BoundaryDebugReference(**{k: v for k, v in fields.items() if k != field})


def test_binary_layout_rejects_truncation_overlap_and_duplicate_fields():
    """严格布局与内容摘要分阶段校验，不能允许错位描述符进入浏览器。"""
    field = dict(
        name="counts", dtype="uint64", components=1, count=1, offset=0, byte_length=8
    )
    data = dict(
        checksum="a" * 64, content_length=8, content="AAAAAAAAAAA=", fields=[field]
    )
    assert DebugBinary(**data).content_length == 8
    for changed in (
        {"content": "AAAA"},
        {"content_length": 9},
        {"fields": [field, field]},
        {"fields": [{**field, "offset": 1}]},
        {"fields": [{**field, "count": 2}]},
    ):
        with pytest.raises(ValidationError):
            DebugBinary(**{**data, **changed})
