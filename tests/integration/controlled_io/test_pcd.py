"""PCD 头部、完整性、COUNT 布局和源字段往返回归。"""

from io import BytesIO
import struct

import lzf
import numpy as np
import pytest
from pypcd4 import Encoding, MetaData, PointCloud
from pypcd4.pypcd4 import read_pcd_header


LIMITS = dict(
    max_header_bytes=4096,
    max_decoded_bytes=100_000,
    max_working_bytes=400_000,
    chunk_rows=3,
    chunk_bytes=256,
)


def source(body=b"1 2 3\n", count=1, encoding="ascii"):
    return (
        f"VERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH {count}\n"
        f"HEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {count}\nDATA {encoding}\n"
    ).encode() + body


def read(data, **overrides):
    return PointCloud.from_fileobj(BytesIO(data), **(LIMITS | overrides))


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
        (b"VERSION 0.7", b"VERSION 0.8"),
        (b"WIDTH 1", b"WIDTH 1 extra"),
        (b"DATA ascii\n", b""),
        (b"FIELDS x y z", b"FIELDS x x z"),
        (b"SIZE 4 4 4", b"SIZE 4 4"),
        (b"SIZE 4 4 4", b"SIZE 3 4 4"),
        (b"COUNT 1 1 1", b"COUNT 1 0 1"),
        (b"POINTS 1", b"POINTS 2"),
        (b"WIDTH 1", b"WIDTH -1"),
        (b"WIDTH 1", b"WIDTH 1\nWIDTH 1"),
        (b"WIDTH 1", b"BOGUS 1"),
        (b"VIEWPOINT 0 0 0 1 0 0 0", b"VIEWPOINT nan 0 0 1 0 0 0"),
        (b"VIEWPOINT 0 0 0 1 0 0 0", b"VIEWPOINT 0 0 0 0 0 0 0"),
        (b"FIELDS x y z", b"FIELDS x x__0000 z\n"),
        (b"DATA ascii", b"DATA binaryscompressed"),
    ],
)
def test_bad_header(old, new):
    with pytest.raises(ValueError):
        read(source().replace(old, new))


def test_count_collision_and_metadata_invariants():
    with pytest.raises(ValueError, match="collision"):
        MetaData(
            fields=("a", "a__0000"),
            size=(4, 4),
            type=("F", "F"),
            count=(2, 1),
            width=1,
            points=1,
        )
    pc = read(source())
    with pytest.raises(ValueError):
        pc.metadata.derive(width=2)
    with pytest.raises(ValueError):
        PointCloud(pc.metadata, pc.pc_data[:0])


def test_source_layout_position_and_standard_optional_entries():
    payload = (
        source()
        .replace(b"COUNT 1 1 1\n", b"")
        .replace(b"VIEWPOINT 0 0 0 1 0 0 0\n", b"")
    )
    stream = BytesIO(payload)
    metadata, offset = read_pcd_header(stream, max_header_bytes=4096)
    assert metadata.count == (1, 1, 1)
    assert metadata.field_columns == (("x",), ("y",), ("z",))
    assert payload[offset:] == b"1 2 3\n"
    stream.seek(0)
    pc = PointCloud.from_fileobj(stream, **LIMITS)
    assert stream.tell() == len(payload)
    assert tuple(pc.pc_data[0]) == (1, 2, 3)


def test_binary_short_extra_and_empty():
    payload = source(struct.pack("<fff", 1, 2, 3), encoding="binary")
    assert tuple(read(payload).pc_data[0]) == (1, 2, 3)
    for bad in (
        payload[:-1],
        payload[:-12],
        payload + b"x",
        source(b"", encoding="binary"),
    ):
        with pytest.raises(ValueError, match="length"):
            read(bad)
    assert len(read(source(b"", count=0, encoding="binary")).pc_data) == 0


def test_compressed_group_layout_independent_fixture():
    # 由手工字节构成 PCL FIELDS 分组，不使用被测 writer 生成。
    raw = struct.pack("<6h", 1, 2, 3, 4, 5, 6) + struct.pack("<3I", 7, 8, 9)
    compressed = lzf.compress(raw, len(raw) * 2)
    header = (
        b"VERSION 0.7\nFIELDS vector rgba\nSIZE 2 4\nTYPE I U\nCOUNT 2 1\nWIDTH 3\n"
        b"HEIGHT 1\nVIEWPOINT 1 2 3 1 0 0 0\nPOINTS 3\nDATA binary_compressed\n"
    )
    pc = read(header + struct.pack("<II", len(compressed), len(raw)) + compressed)
    assert pc.metadata.field_columns == (("vector__0000", "vector__0001"), ("rgba",))
    np.testing.assert_array_equal(pc.pc_data["vector__0000"], [1, 3, 5])
    np.testing.assert_array_equal(pc.pc_data["vector__0001"], [2, 4, 6])
    np.testing.assert_array_equal(pc.pc_data["rgba"], [7, 8, 9])
    assert pc.metadata.viewpoint == (1, 2, 3, 1, 0, 0, 0)


@pytest.mark.parametrize(
    "variant", ["prefix", "short", "tail", "decoded", "corrupt", "zero"]
)
def test_bad_compressed(variant):
    raw = bytes(12)
    compressed = lzf.compress(raw)
    body = struct.pack("<II", len(compressed), len(raw)) + compressed
    if variant == "prefix":
        body = body[:7]
    if variant == "short":
        body = body[:-1]
    if variant == "tail":
        body += b"x"
    if variant == "decoded":
        body = struct.pack("<II", len(compressed), 11) + compressed
    if variant == "corrupt":
        body = struct.pack("<II", 1, 12) + b"\xff"
    if variant == "zero":
        body = struct.pack("<II", 0, 12)
    with pytest.raises((ValueError, RuntimeError)):
        read(source(body, encoding="binary_compressed"))


@pytest.mark.parametrize("encoding", list(Encoding))
def test_writer_source_precision_organized_count(encoding):
    metadata = MetaData(
        fields=("vector", "id", "small", "precise", "rgba"),
        size=(2, 8, 4, 8, 4),
        type=("I", "U", "F", "F", "U"),
        count=(2, 1, 1, 1, 1),
        width=4,
        height=8,
        points=32,
        viewpoint=(1, 2, 3, 1, 0, 0, 0),
    )
    data = np.zeros(metadata.points, dtype=metadata.build_dtype())
    data["vector__0000"] = 1
    data["vector__0001"] = 2
    data["id"] = 2**64 - 1
    data["small"] = np.float32(1e-20)
    data["precise"] = np.nextafter(1.0, 2.0)
    data["rgba"] = 0xFF123456
    output = BytesIO()
    PointCloud(metadata, data).save(
        output, encoding, chunk_rows=3, max_working_bytes=100_000
    )
    actual = read(output.getvalue())
    assert actual.metadata == metadata.derive(data=encoding)
    assert actual.pc_data.dtype == data.dtype
    np.testing.assert_array_equal(actual.pc_data, data)


def test_compression_failure_never_changes_encoding(monkeypatch):
    pc = read(source())
    monkeypatch.setattr(lzf, "compress", lambda data: None)
    output = BytesIO()
    with pytest.raises(ValueError, match="encoding was not changed"):
        pc.save(
            output, Encoding.BINARY_COMPRESSED, chunk_rows=2, max_working_bytes=10_000
        )
    assert b"DATA binary_compressed\n" in output.getvalue()


@pytest.mark.parametrize("encoding", list(Encoding))
def test_empty_writer(encoding):
    pc = read(source(b"", count=0))
    output = BytesIO()
    pc.save(output, encoding, chunk_rows=2, max_working_bytes=10_000)
    assert len(read(output.getvalue()).pc_data) == 0


def test_limits_and_cancel():
    with pytest.raises(ValueError, match="budget"):
        read(source(), max_decoded_bytes=1)
    with pytest.raises(ValueError, match="budget"):
        read(source(), max_header_bytes=10)

    def cancel():
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        read(source(), cancel=cancel)
    compressed = lzf.compress(bytes(12))
    with pytest.raises(ValueError, match="budget"):
        read(
            source(
                struct.pack("<II", len(compressed), 12) + compressed,
                encoding="binary_compressed",
            ),
            max_working_bytes=1,
        )


@pytest.mark.parametrize("failure", ["short", "flush"])
def test_writer_failure(failure):
    class Failed(BytesIO):
        def write(self, data):
            return len(data) - 1 if failure == "short" else super().write(data)

        def flush(self):
            raise OSError("flush")

    with pytest.raises(OSError):
        read(source()).save(
            Failed(), Encoding.ASCII, chunk_rows=2, max_working_bytes=10_000
        )
