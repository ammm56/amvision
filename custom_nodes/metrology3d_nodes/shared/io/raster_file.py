"""成熟 NumPy/Pillow 解析器的严格标量入口；不解析自定义文件语法。"""

from contextlib import contextmanager
from dataclasses import dataclass
import warnings

import numpy as np
from PIL import Image

from backend.contracts.workflows.point_cloud import MAX_POINT_CLOUD_INPUT_BYTES
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)


class _HeaderReader:
    """限制成熟解析器的头部读取总量，不替代解析器，原流由快照所有者关闭。"""

    def __init__(self, stream, limit, cancel):
        self.stream, self.limit, self.cancel = stream, limit, cancel
        self.used = 0
        position = stream.tell()
        stream.seek(0, 2)
        self.length = stream.tell()
        stream.seek(position)

    def read(self, size=-1):
        """按实际可读长度计费；原生解码器常按大块读取到文件末尾。"""
        self.cancel()
        remaining = max(0, self.length - self.stream.tell())
        size = remaining if size < 0 else min(size, remaining)
        if size > self.limit - self.used:
            raise InvalidRequestError("标量文件头部超过显式预算")
        data = self.stream.read(size)
        self.used += len(data)
        return data

    def seek(self, offset, whence=0):
        """只读定位复用原快照，不能扩大允许的头部读取量。"""
        return self.stream.seek(offset, whence)

    def tell(self):
        """提供当前偏移给原生格式读取器。"""
        return self.stream.tell()

    def close(self):
        """解析器关闭包装器不关闭调用方的不可变快照。"""


@dataclass(frozen=True)
class RasterFileInfo:
    """预检结果，实际解码必须再次核对尺寸和类型。"""

    format: str
    shape: tuple[int, int]
    dtype: np.dtype
    content_length: int


def inspect_raster(stream, file_format, spec, policy, cancel):
    """分配前验证格式、大小、完整结构与声明，不按扩展名猜标定。"""
    cancel()
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    if not 0 < size <= MAX_POINT_CLOUD_INPUT_BYTES:
        raise InvalidRequestError("标量文件为空或超过 1 GB")
    reader = _HeaderReader(stream, policy.max_header_bytes, cancel)
    try:
        if file_format == "npy":
            version = np.lib.format.read_magic(reader)
            if version not in ((1, 0), (2, 0)):
                raise InvalidRequestError("NPY 标量入口仅支持 1.0/2.0 数值格式")
            header = (
                np.lib.format.read_array_header_1_0
                if version == (1, 0)
                else np.lib.format.read_array_header_2_0
            )
            shape, _, dtype = header(reader, max_header_size=policy.max_header_bytes)
            if (
                dtype.hasobject
                or dtype.fields
                or dtype.subdtype
                or dtype.name != spec.dtype
            ):
                raise InvalidRequestError("NPY 必须为声明类型的无对象单标量数组")
            if (
                tuple(shape) != (spec.height, spec.width)
                or stream.tell() + spec.point_count() * dtype.itemsize != size
            ):
                raise InvalidRequestError("NPY 尺寸、记录长度或尾部与声明不一致")
        elif file_format in ("png", "tiff"):
            with warnings.catch_warnings():
                warnings.simplefilter("error", UserWarning)
                im = Image.open(reader, formats=[file_format.upper()])
                try:
                    if (
                        im.format.lower() != file_format
                        or im.size != (spec.width, spec.height)
                        or getattr(im, "n_frames", 1) != 1
                    ):
                        raise InvalidRequestError("标量图片格式、尺寸或帧数不符合声明")
                    if file_format == "png":
                        allowed = {"L": "uint8", "I;16": "uint16", "I;16B": "uint16"}
                        dtype = np.dtype(allowed.get(im.mode, "object"))
                    else:
                        tags = im.tag_v2
                        bits = tuple(tags.get(258, ()))
                        sample_format = tuple(tags.get(339, (1,)))
                        allowed = {
                            (8, 1): "uint8",
                            (16, 1): "uint16",
                            (16, 2): "int16",
                            (32, 2): "int32",
                            (32, 3): "float32",
                        }
                        dtype = (
                            np.dtype(allowed.get((bits[0], sample_format[0]), "object"))
                            if len(bits) == len(sample_format) == 1
                            else np.dtype("object")
                        )
                        if (
                            tags.get(277, 1) != 1
                            or tags.get(262, 1) != 1
                            or tags.get(274, 1) != 1
                            or tags.get(259, 1) not in (1, 5, 8, 32946, 32773)
                            or 330 in tags
                            or 338 in tags
                        ):
                            raise InvalidRequestError(
                                "TIFF 必须为无损、单通道、原方向标量页"
                            )
                        offsets, lengths = (
                            (tags.get(324), tags.get(325))
                            if 324 in tags
                            else (tags.get(273), tags.get(279))
                        )
                        if (
                            not offsets
                            or not lengths
                            or len(offsets) != len(lengths)
                            or any(
                                type(a) is not int
                                or type(n) is not int
                                or a < 0
                                or n <= 0
                                or a + n > size
                                for a, n in zip(offsets, lengths)
                            )
                        ):
                            raise InvalidRequestError("TIFF 像素块缺失或截断")
                finally:
                    im.close()
            shape = (spec.height, spec.width)
            if dtype.name != spec.dtype:
                raise InvalidRequestError(
                    "标量图片类型不受支持或与声明不一致，不自动降精度"
                )
        else:
            raise InvalidRequestError("未知标量文件格式")
        return RasterFileInfo(file_format, tuple(shape), dtype, size)
    except (InvalidRequestError, InterruptedError):
        raise
    except (
        OSError,
        ValueError,
        EOFError,
        SyntaxError,
        Image.DecompressionBombError,
        UserWarning,
    ) as error:
        raise InvalidRequestError(
            "标量文件头部损坏或不是受支持的单通道数值格式"
        ) from error
    finally:
        stream.seek(0)


@contextmanager
def borrow_raster_file(stream, file_format, spec, *, policy, budget, cancel):
    """一次解码、一次借用，结束先解除数组再归还容量；禁止 pickle 和显示转换。"""
    info = inspect_raster(stream, file_format, spec, policy, cancel)
    decoded = spec.point_count() * info.dtype.itemsize
    if decoded > policy.max_decoded_bytes:
        raise InvalidRequestError("标量数组超过解码预算")
    # Pillow 的 int16 TIFF 以 int32 解码；计入原生图、数组桥接与规范化副本。
    reserve_bytes = (
        decoded * 2
        if file_format == "npy"
        else spec.point_count() * max(4, info.dtype.itemsize) * 4 + info.content_length
    )
    reservation = budget.reserve(reserve_bytes)
    data = image = values = None
    try:
        cancel()
        if file_format == "npy":
            data = np.lib.format.read_array(
                stream, allow_pickle=False, max_header_size=policy.max_header_bytes
            )
        else:
            if file_format == "png":
                reader = _HeaderReader(
                    stream,
                    max(policy.max_header_bytes, info.content_length * 2),
                    cancel,
                )
                with Image.open(reader, formats=["PNG"]) as image:
                    image.verify()
                stream.seek(0)
            reader = _HeaderReader(
                stream, info.content_length * 4 + policy.max_header_bytes, cancel
            )
            with warnings.catch_warnings():
                warnings.simplefilter("error", UserWarning)
                with Image.open(reader, formats=[file_format.upper()]) as image:
                    image.load()
                    data = np.array(image)
            image = None
        cancel()
        if data is None or data.shape != info.shape:
            raise InvalidRequestError("解码器返回的标量尺寸或精度与预检不一致")
        if data.dtype.name != spec.dtype:
            if file_format != "tiff" or spec.dtype != "int16" or data.dtype != np.int32:
                raise InvalidRequestError("解码器返回的标量精度与预检不一致")
            for start in range(
                0, spec.point_count(), min(policy.chunk_rows, policy.max_working_bytes)
            ):
                cancel()
                values = data.reshape(-1)[
                    start : start + min(policy.chunk_rows, policy.max_working_bytes)
                ]
                if np.any(values < -32768) or np.any(values > 32767):
                    raise InvalidRequestError("TIFF 有符号标量超出声明范围")
            values = None
        data = np.ascontiguousarray(data, dtype=np.dtype(spec.dtype).newbyteorder("<"))
        data.setflags(write=False)
        reservation.shrink(decoded)
    except (InvalidRequestError, InterruptedError) as error:
        data = image = values = None
        release_exception_frames(error)
        reservation.close()
        raise
    except (OSError, ValueError, EOFError, SyntaxError, UserWarning) as error:
        release_exception_frames(error)
        data = image = values = None
        reservation.close()
        raise InvalidRequestError("标量文件正文损坏或解码失败") from error
    except BaseException as error:
        data = image = values = None
        release_exception_frames(error)
        reservation.close()
        raise
    try:
        yield data
    except BaseException as error:
        release_exception_frames(error)
        raise
    finally:
        data = image = values = None
        reservation.close()
