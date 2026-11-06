"""标量文件必须保持像素类型/顺序，坏文件不能降级成普通显示图片。"""

from io import BytesIO

import cv2
import numpy as np
import pytest
from PIL import Image

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from custom_nodes.metrology3d_nodes.shared.io.raster_file import borrow_raster_file
from tests.point_cloud_support import policy
from tests.test_metrology3d_raster_conversion import specification


def encode(array, kind):
    """使用独立成熟写出器构造真值文件，不手写格式解析或伪造读出结果。"""
    if kind == "npy":
        stream = BytesIO()
        np.save(stream, array, allow_pickle=True)
        return stream.getvalue()
    ok, result = cv2.imencode(
        "." + kind, array, [cv2.IMWRITE_TIFF_COMPRESSION, 1] if kind == "tiff" else []
    )
    assert ok
    return result.tobytes()


def decode(content, kind, spec, p=None, cancel=lambda: None):
    """实际读取并在上下文退出后核对输入容量归还。"""
    p = p or policy(max_header_bytes=8192)
    budget = CloudArrayBudget(p.max_live_array_bytes)
    with BytesIO(content) as stream:
        try:
            with borrow_raster_file(
                stream, kind, spec, policy=p, budget=budget, cancel=cancel
            ) as result:
                assert not result.flags.writeable
                assert budget.used == result.nbytes
                return result.copy()
        finally:
            assert not stream.closed
            assert budget.used == 0


@pytest.mark.parametrize(
    "dtype", ["uint8", "uint16", "int16", "uint32", "int32", "float32", "float64"]
)
@pytest.mark.parametrize("order", ["C", "F"])
@pytest.mark.parametrize("endian", ["<", ">"])
def test_npy_precision_byte_order_and_pixel_order(dtype, order, endian):
    a = np.array(
        np.arange(12).reshape(3, 4),
        dtype=np.dtype(dtype).newbyteorder(endian),
        order=order,
    )
    actual = decode(encode(a, "npy"), "npy", specification(dtype=dtype))
    np.testing.assert_array_equal(actual, a)
    assert actual.dtype == np.dtype(dtype).newbyteorder("<")
    assert actual.flags.c_contiguous


@pytest.mark.parametrize(
    "kind,dtype",
    [
        ("png", "uint8"),
        ("png", "uint16"),
        *[("tiff", d) for d in ("uint8", "uint16", "int16", "int32", "float32")],
    ],
)
def test_lossless_scalar_images(kind, dtype):
    a = np.arange(12, dtype=dtype).reshape(3, 4)
    if dtype.startswith("int"):
        a -= 6
    if dtype == "float32":
        a *= 0.125
        a[0, 0], a[0, 1] = np.nan, np.inf
    np.testing.assert_array_equal(
        decode(encode(a, kind), kind, specification(dtype=dtype)), a
    )


@pytest.mark.parametrize("kind", ["npy", "png", "tiff"])
def test_truncation_wrong_dimensions_and_dtype(kind):
    content = encode(np.arange(12, dtype="uint16").reshape(3, 4), kind)
    for damaged in (b"", content[:12], content[: len(content) // 2], content[:-9]):
        with pytest.raises(InvalidRequestError):
            decode(damaged, kind, specification(dtype="uint16"))
    for change in ({"width": 3}, {"dtype": "float32"}):
        with pytest.raises(InvalidRequestError):
            decode(content, kind, specification(**{"dtype": "uint16", **change}))


def test_npy_forbids_objects_fields_and_trailing_data():
    for a in (
        np.full((3, 4), "no-pickle", dtype=object),
        np.zeros((3, 4), dtype=[("x", "f4")]),
    ):
        with pytest.raises(InvalidRequestError):
            decode(encode(a, "npy"), "npy", specification())
    content = encode(np.ones((3, 4), dtype="float32"), "npy")
    with pytest.raises(InvalidRequestError):
        decode(content + b"trailing", "npy", specification())


def test_color_and_float64_tiff_do_not_silently_reduce_precision():
    for kind in ("png", "tiff"):
        content = encode(np.zeros((3, 4, 3), dtype="uint8"), kind)
        with pytest.raises(InvalidRequestError):
            decode(content, kind, specification(dtype="uint8"))
    content = encode(np.ones((3, 4), dtype="float64"), "tiff")
    with pytest.raises(InvalidRequestError):
        decode(content, "tiff", specification(dtype="float64"))


def test_budget_and_cancellation_release_input():
    content = encode(np.ones((3, 4), dtype="float32"), "npy")
    for p in (
        policy(max_header_bytes=8),
        policy(max_decoded_bytes=16),
        policy(max_live_array_bytes=48, max_decoded_bytes=48),
    ):
        with pytest.raises(InvalidRequestError):
            decode(content, "npy", specification(), p)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 6:
            raise InterruptedError("input cancelled")

    with pytest.raises(InterruptedError):
        decode(content, "npy", specification(), cancel=cancel)


@pytest.mark.parametrize("compression", [1, 5, 8, 32946, 32773])
@pytest.mark.parametrize("dtype", ["uint8", "uint16", "int16", "int32", "float32"])
def test_tiff_lossless_compressions(compression, dtype):
    a = (np.arange(600).reshape(20, 30) % 121 - 60).astype(dtype)
    if dtype == "float32":
        a *= 0.125
    ok, data = cv2.imencode(".tiff", a, [cv2.IMWRITE_TIFF_COMPRESSION, compression])
    assert ok
    actual = decode(
        data.tobytes(),
        "tiff",
        specification(width=30, height=20, dtype=dtype),
        policy(
            max_header_bytes=16384, max_decoded_bytes=65536, max_live_array_bytes=131072
        ),
    )
    assert actual.tobytes() == a.tobytes()


@pytest.mark.parametrize("kind", ["npy", "tiff"])
def test_nonfinite_bits_and_signed_zero_preserved(kind):
    bits = np.array(
        [
            0x7FC00001,
            0xFFC00002,
            0x7F800000,
            0xFF800000,
            0x80000000,
            0,
            1,
            0x80000001,
            0x3F800001,
            0x3F800000,
            2,
            3,
        ],
        dtype="<u4",
    )
    a = bits.view("<f4").reshape(3, 4)
    assert decode(encode(a, kind), kind, specification()).tobytes() == a.tobytes()


def test_damaged_compressed_tiff_body_rejected():
    a = np.arange(600, dtype="uint16").reshape(20, 30)
    ok, data = cv2.imencode(".tiff", a, [cv2.IMWRITE_TIFF_COMPRESSION, 8])
    assert ok
    damaged = bytearray(data)
    with Image.open(BytesIO(damaged)) as image:
        offset, length = image.tag_v2[273][0], image.tag_v2[279][0]
    # 原标签/长度完整，只有压缩正文损坏；不能只依赖头部尺寸检查。
    damaged[offset : offset + length] = bytes(length)
    with pytest.raises(InvalidRequestError, match="正文"):
        decode(
            damaged,
            "tiff",
            specification(width=30, height=20, dtype="uint16"),
            policy(
                max_header_bytes=16384,
                max_decoded_bytes=65536,
                max_live_array_bytes=131072,
            ),
        )


def test_tiff_orientation_multiframe_and_png_crc_rejected():
    a = np.arange(12, dtype="uint16").reshape(3, 4)
    for kwargs in (
        dict(tiffinfo={274: 2}),
        dict(save_all=True, append_images=[Image.fromarray(a)]),
    ):
        stream = BytesIO()
        Image.fromarray(a).save(stream, format="TIFF", **kwargs)
        with pytest.raises(InvalidRequestError):
            decode(stream.getvalue(), "tiff", specification(dtype="uint16"))
    data = bytearray(encode(a, "png"))
    data[29] ^= 1  # 已知 PNG 首个头块 CRC，不能进入成功解码。
    with pytest.raises(InvalidRequestError):
        decode(data, "png", specification(dtype="uint16"))


def test_file_consumer_exception_is_not_mislabeled_as_input_error():
    p = policy()
    budget = CloudArrayBudget(p.max_live_array_bytes)
    with pytest.raises(ValueError, match="consumer"):
        with borrow_raster_file(
            BytesIO(encode(np.ones((3, 4), dtype="f4"), "npy")),
            "npy",
            specification(),
            policy=p,
            budget=budget,
            cancel=lambda: None,
        ):
            raise ValueError("consumer")
    assert budget.used == 0
