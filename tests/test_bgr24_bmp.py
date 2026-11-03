"""文件解码优化必须保持像素、颜色、方向和句柄生命周期。"""

import struct

import cv2
import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.shared.backend.runtime.bmp import (
    decode_bgr24_bmp,
    read_bgr24_bmp,
)


@pytest.mark.parametrize("width", [1, 2, 3, 4, 13])
@pytest.mark.parametrize("top_down", [False, True])
def test_bmp_pixels_padding_orientation_and_close(tmp_path, width, top_down):
    """中文文件名、行填充和两个行方向都与 OpenCV 逐像素相同。"""
    matrix = np.arange(5 * width * 3, dtype=np.uint8).reshape(5, width, 3)
    encoded = bytearray(cv2.imencode(".bmp", matrix)[1])
    if top_down:
        stride = (width * 3 + 3) // 4 * 4
        offset = struct.unpack_from("<I", encoded, 10)[0]
        pixels = encoded[offset:]
        encoded[offset:] = b"".join(
            pixels[i * stride : (i + 1) * stride] for i in reversed(range(5))
        )
        struct.pack_into("<i", encoded, 22, -5)
    path = tmp_path / "中文图片.bmp"
    path.write_bytes(encoded)
    view = memoryview(encoded)
    decoded = decode_bgr24_bmp(view)
    view.release()
    np.testing.assert_array_equal(decoded, matrix)
    for _ in range(20):
        actual = read_bgr24_bmp(path)
        np.testing.assert_array_equal(actual, matrix)
        assert actual.flags.c_contiguous and actual.flags.owndata
    path.unlink()  # Windows 上映射未关闭时删除会失败。
    np.testing.assert_array_equal(actual, matrix)


@pytest.mark.parametrize(
    "change",
    [
        "short",
        "png",
        "compressed",
        "bits",
        "width",
        "height",
        "offset",
        "truncated",
        "huge",
    ],
)
def test_bad_bmp_is_explicitly_rejected_and_closed(tmp_path, change):
    """不支持的格式和损坏文件不能静默回退、越界映射或生成错误图片。"""
    data = bytearray(cv2.imencode(".bmp", np.zeros((4, 5, 3), np.uint8))[1])
    mutations = {
        "compressed": (30, "I", 1),
        "bits": (28, "H", 32),
        "width": (18, "i", -5),
        "height": (22, "i", 0),
        "offset": (10, "I", 20),
        "huge": (18, "i", 2147483647),
    }
    if change in mutations:
        offset, kind, value = mutations[change]
        struct.pack_into("<" + kind, data, offset, value)
    elif change == "short":
        data = data[:10]
    elif change == "png":
        data[:2] = b"PN"
    else:
        data = data[:-1]
    path = tmp_path / "invalid.bmp"
    path.write_bytes(data)
    with pytest.raises(InvalidRequestError, match="BGR24 BMP"):
        decode_bgr24_bmp(memoryview(data))
    with pytest.raises(InvalidRequestError, match="BGR24 BMP"):
        read_bgr24_bmp(path)
    path.unlink()
