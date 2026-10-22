"""受控 trimesh 点云 profile 的独立字段及损坏输入回归。"""

from dataclasses import FrozenInstanceError
from io import BytesIO
import struct

import numpy as np
import pytest
from trimesh.exchange import ply


def source(
    body=b"1 2 3\n",
    count=1,
    fields="property float x\nproperty float y\nproperty float z",
    encoding="ascii",
):
    """生成可手工核对的记录，不用被测 writer 制造期望。"""
    return (
        f"ply\nformat {encoding} 1.0\nelement vertex {count}\n{fields}\nend_header\n".encode()
        + body
    )


def read(data, **overrides):
    """测试预算显式设置，不作为生产默认。"""
    stream = BytesIO(data)
    header = ply.read_ply_header(stream, max_header_bytes=4096)
    args = dict(max_decoded_bytes=4096, chunk_rows=2, chunk_bytes=256)
    args.update(overrides)
    return header, ply.read_ply_data(stream, header, **args)


def test_source_layout_and_float32():
    header, data = read(source())
    assert header.elements[0].properties[0].dtype == "<f4"
    assert data.dtype == np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4")])
    assert tuple(data[0]) == (1, 2, 3)
    with pytest.raises(FrozenInstanceError):
        header.encoding = "binary_little_endian"


@pytest.mark.parametrize(
    "body,count",
    [
        (b"", 1),
        (b"1 2\n", 1),
        (b"1 2 3 4\n", 1),
        (b"1 2 3\n", 2),
        (b"1 2 3\n4 5 6\n", 1),
        (b"1 2 3\n\n", 1),
        (b"\n", 1),
        (b"1oops 2 3\n", 1),
        (b"1 2 3 # comment\n", 1),
        (b"1e999 2 3\n", 1),
        (b"1e39 2 3\n", 1),
        (b"1e-999 2 3\n", 1),
    ],
)
def test_bad_ascii(body, count):
    with pytest.raises(ValueError):
        read(source(body, count))


@pytest.mark.parametrize(
    "old,new",
    [
        (b"ply\n", b"notply\n"),
        (b"ascii 1.0", b"ascii 2.0"),
        (b"ascii 1.0", b"ascii 1.0 extra"),
        (b"end_header\n", b""),
        (b"end_header", b"end_header extra"),
        (b"vertex 1", b"vertex -1"),
        (b"property float x", b"property float x\nproperty float x"),
        (b"property float x", b"property nonsense x"),
        (b"property float x", b"property float x extra"),
        (b"element vertex 1", b"element vertex 1\nelement vertex 1"),
        (b"end_header", b"unknown\nend_header"),
    ],
)
def test_bad_header(old, new):
    with pytest.raises(ValueError):
        read(source().replace(old, new))


@pytest.mark.parametrize("token", [b"256", b"-1", b"1.1", b"1e1"])
def test_integer_range_and_syntax(token):
    with pytest.raises(ValueError):
        read(source(token + b"\n", fields="property uchar id"))


def test_all_scalar_fields_exact():
    fields = "property uint64 id\nproperty int64 signed\nproperty double x\nproperty float y\nproperty uchar red"
    _, data = read(
        source(
            b"18446744073709551615 -9223372036854775808 1.0000000000000002 1e-20 255\n",
            fields=fields,
        )
    )
    assert int(data["id"][0]) == 2**64 - 1
    assert int(data["signed"][0]) == -(2**63)
    assert data["x"][0] == np.nextafter(1.0, 2.0)
    assert data["y"][0] == np.float32(1e-20)
    assert data.dtype.names == ("id", "signed", "x", "y", "red")


@pytest.mark.parametrize(
    "encoding,order", [("binary_little_endian", "<"), ("binary_big_endian", ">")]
)
def test_binary_independent_bytes(encoding, order):
    body = struct.pack(order + "Qd", 2**64 - 1, np.nextafter(1.0, 2.0))
    payload = source(
        body, fields="property uint64 id\nproperty double x", encoding=encoding
    )
    _, data = read(payload)
    assert int(data["id"][0]) == 2**64 - 1
    assert data["x"][0] == np.nextafter(1.0, 2.0)
    for bad in (payload[:-1], payload[:-16], payload + b"x"):
        with pytest.raises(ValueError, match="length"):
            read(bad)


@pytest.mark.parametrize(
    "encoding", ["ascii", "binary_little_endian", "binary_big_endian"]
)
def test_writer_preserves_values(encoding):
    data = np.array(
        [(2**64 - 1, -(2**63), 1e-20, np.nextafter(1.0, 2.0)), (1, 2, -0.0, -0.0)],
        dtype=[("id", "u8"), ("signed", "i8"), ("x", "f4"), ("nx", "f8")],
    )
    stream = BytesIO()
    ply.write_ply_points(stream, data, encoding=encoding, chunk_rows=1)
    _, actual = read(stream.getvalue())
    for name in data.dtype.names:
        np.testing.assert_array_equal(actual[name], data[name])
        assert actual.dtype[name].itemsize == data.dtype[name].itemsize
    assert np.signbit(actual["x"][1])


def test_limits_and_cancel():
    with pytest.raises(ValueError, match="budget"):
        read(source(), max_decoded_bytes=1)
    with pytest.raises(ValueError, match="budget"):
        read(source(), chunk_bytes=2)
    with pytest.raises(ValueError):
        ply.read_ply_header(BytesIO(source()), max_header_bytes=5)

    def cancel():
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        read(source(), cancel=cancel)


def test_lists_and_extra_elements_are_visible_then_rejected():
    payload = source(fields="property list uchar float samples")
    stream = BytesIO(payload)
    header = ply.read_ply_header(stream, max_header_bytes=4096)
    assert header.elements[0].properties[0].count_dtype == "<u1"
    with pytest.raises(ValueError, match="list"):
        ply.read_ply_data(
            stream, header, max_decoded_bytes=4096, chunk_rows=2, chunk_bytes=256
        )
    with pytest.raises(ValueError, match="one vertex"):
        read(
            source().replace(
                b"end_header", b"element face 0\nproperty int index\nend_header"
            )
        )


def test_special_float_and_empty_derived_cloud():
    _, data = read(source(b"nan inf -inf\n"))
    assert (
        np.isnan(data["x"][0])
        and np.isposinf(data["y"][0])
        and np.isneginf(data["z"][0])
    )
    assert len(read(source(b"", 0))[1]) == 0


@pytest.mark.parametrize("dtype", ["<f2", ">f2", "c8", "O", "U4"])
def test_writer_rejects_unsupported_types_before_output(dtype):
    output = BytesIO()
    data = np.empty(0, dtype=[("x", dtype)])
    with pytest.raises(ValueError, match="dtype"):
        ply.write_ply_points(output, data, encoding="ascii", chunk_rows=1)
    assert output.getvalue() == b""


@pytest.mark.parametrize(
    "dtype", ["i1", "u1", "i2", "u2", "i4", "u4", "i8", "u8", "f4", "f8"]
)
def test_each_scalar_dtype_ascii_and_binary(dtype):
    dt = np.dtype(dtype)
    if dt.kind == "f":
        values = [np.finfo(dt).max, np.finfo(dt).smallest_subnormal, -0.0]
    else:
        info = np.iinfo(dt)
        values = [info.min, info.max, 0]
    data = np.empty(3, dtype=[("attribute", dt)])
    data["attribute"] = values
    for encoding in ("ascii", "binary_little_endian", "binary_big_endian"):
        output = BytesIO()
        ply.write_ply_points(output, data, encoding=encoding, chunk_rows=2)
        actual = read(output.getvalue())[1]
        np.testing.assert_array_equal(actual["attribute"], data["attribute"])


@pytest.mark.parametrize("failure", ["short", "flush"])
def test_writer_io_failure(failure):
    class Failed(BytesIO):
        def write(self, data):
            return len(data) - 1 if failure == "short" else super().write(data)

        def flush(self):
            raise OSError("flush")

    with pytest.raises(OSError):
        ply.write_ply_points(
            Failed(), read(source())[1], encoding="ascii", chunk_rows=2
        )
