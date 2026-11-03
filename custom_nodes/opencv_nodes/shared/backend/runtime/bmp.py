"""显式读取未压缩 BGR24 BMP；短期映射文件，不保留文件句柄或额外编码副本。"""

import mmap
from pathlib import Path
import struct

import numpy as np

from backend.service.application.errors import InvalidRequestError


def decode_bgr24_bmp(content: object) -> np.ndarray:
    """从已有编码缓冲区解码同一 BMP 格式，输出不引用输入缓冲区。"""
    try:
        offset, width, height, stride, required = _layout(content)
        if required > len(content):
            raise ValueError("BMP 像素数据不完整")
        rows = np.ndarray(
            (abs(height), width, 3),
            np.uint8,
            buffer=content,
            offset=offset,
            strides=(stride, 3, 1),
        )
        try:
            return (rows[::-1] if height > 0 else rows).copy(order="C")
        finally:
            del rows
    except (ValueError, OverflowError, TypeError) as error:
        raise InvalidRequestError(
            "BGR24 BMP 解码失败：要求完整的未压缩 24 位 BMP 数据"
        ) from error


def _layout(header: object) -> tuple[int, int, int, int, int]:
    """验证文件头，返回像素偏移、宽高、行跨度和所需长度。"""
    if len(header) < 54 or bytes(header[:2]) != b"BM":
        raise ValueError("BMP 文件头无效")
    offset = struct.unpack_from("<I", header, 10)[0]
    dib, width, height, planes, bits, compression = struct.unpack_from(
        "<IiiHHI", header, 14
    )
    if dib != 40 or planes != 1 or bits != 24 or compression != 0:
        raise ValueError("要求 BITMAPINFOHEADER / BI_RGB / BGR24")
    if width <= 0 or height == 0 or offset < 54:
        raise ValueError("BMP 尺寸或像素偏移无效")
    stride = (width * 3 + 3) // 4 * 4
    return offset, width, height, stride, offset + stride * abs(height)


def read_bgr24_bmp(path: Path) -> np.ndarray:
    """读取 BITMAPINFOHEADER 的 BI_RGB / 24 位 BMP，返回独立连续 BGR 数组。

    支持正向、倒向行和四字节行对齐。其他格式明确报错，由调用者选择普通
    OpenCV 解码。复制完成即关闭映射，输出的修改和释放均与源文件无关。
    """
    try:
        with path.open("rb") as stream:
            *_, required = _layout(stream.read(54))
            stream.seek(0, 2)
            if required > stream.tell():
                raise ValueError("BMP 像素数据不完整")
            with mmap.mmap(
                stream.fileno(), required, access=mmap.ACCESS_READ
            ) as mapping:
                return decode_bgr24_bmp(mapping)
    except (OSError, ValueError, OverflowError) as error:
        raise InvalidRequestError(
            "BGR24 BMP 读取失败：要求完整的未压缩 24 位 BMP 文件"
        ) from error
