"""字段视图的预算、不可写别名、精度和生命周期验证。"""

import weakref
from types import SimpleNamespace

import numpy as np
import pytest

from custom_nodes.metrology3d_nodes.shared.io.normalization import (
    can_view_field,
    field_view,
    readonly_records,
)
from tests.integration.metrology3d.test_file_read import context, ply, run
from tests.point_cloud_support import options

__all__ = ["context"]


@pytest.mark.parametrize("names", [("x", "y", "z"), ("z", "y", "x"), ("y",)])
@pytest.mark.parametrize("dtype", ["float32", "float64"])
def test_uniform_layout_is_readonly_view_with_original_precision(names, dtype):
    """含未对齐 uint8 和 uint64 的行仍共享完整 backing，字段值不转换。"""
    source = np.zeros(
        4,
        dtype=[
            ("flag", "u1"),
            ("x", dtype),
            ("y", dtype),
            ("z", dtype),
            ("serial", "u8"),
        ],
    )
    source["x"] = np.nextafter(np.array(1, dtype=dtype), np.array(2, dtype=dtype))
    source["y"] = -0.0
    source["z"] = np.inf
    mapping = SimpleNamespace(dtype=dtype, source_names=names)
    assert can_view_field(source.dtype, mapping)
    records = readonly_records(source)
    result = field_view(records, mapping)
    assert np.shares_memory(result, source)
    assert result.dtype == np.dtype(dtype).newbyteorder("<")
    for column, name in enumerate(names):
        assert result[:, column].tobytes() == source[name].tobytes()
    with pytest.raises(ValueError):
        result.setflags(write=True)
    reference = weakref.ref(source)
    del source, records
    assert reference() is not None
    del result
    assert reference() is None


def test_nonuniform_and_big_endian_require_copy():
    """类型相同但偏移非等差不能伪称零复制，字节序也不能直接重解释。"""
    source = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4")])
    mapping = SimpleNamespace(dtype="float32", source_names=("x", "z", "y"))
    assert not can_view_field(source, mapping)
    mapping.source_names = ("x", "y", "z")
    assert not can_view_field(source.newbyteorder(">"), mapping)


def test_mixed_shared_and_reordered_fields_charge_live_backing_once(context):
    """positions 需要重排时，其余视图仍持有整份解码 backing，不能少计费。"""
    fields = (
        "property float x\nproperty float y\nproperty float z\nproperty uint serial\n"
    )
    extra = dict(
        source_names=["serial"],
        target_name="serial",
        semantic="scalar",
        dtype="uint32",
        components=1,
        unit=None,
    )
    opts = options(extra=(extra,))
    payload = opts.model_dump()
    payload["field_mapping"][0]["source_names"] = ["x", "z", "y"]
    result = run(
        context,
        ply(b"1 2 3 4294967295\n4 5 6 7\n", fields=fields),
        type(opts).model_validate(payload),
    )
    assert context[2].used == 32 + 24
    with result.arrays.borrow() as values:
        np.testing.assert_array_equal(values["positions"], [[1, 3, 2], [4, 6, 5]])
        assert values["serial"][0, 0] == 2**32 - 1
    result.arrays.close()
    assert context[2].used == 0
