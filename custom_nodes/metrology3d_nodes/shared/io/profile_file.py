"""NumPy NPZ 轮廓入口；标准 ZIP/NPY 解析器负责语法，平台限定结构和容量。"""

from contextlib import contextmanager
from types import MappingProxyType
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED, ZIP_STORED

import numpy as np

from backend.contracts.workflows.point_cloud import MAX_POINT_CLOUD_INPUT_BYTES
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.profile_conversion import (
    validate_profile_arrays,
)


class _ReadCancelled(Exception):
    """避免 ZIP 将回调的 InterruptedError 当作损坏文件的 OSError 吞掉。"""

    def __init__(self, error):
        self.error = error


def _cancel_read(cancel):
    """保留调用方取消类型；解析器边界之外仍抛原异常。"""
    try:
        cancel()
    except BaseException as error:
        raise _ReadCancelled(error) from error


class _ArchiveReader:
    """限制标准 ZIP 解析器的中央目录分配；文件快照仍由调用者关闭。"""

    def __init__(self, stream, maximum, cancel):
        self.stream, self.maximum, self.cancel = stream, maximum, cancel

    def read(self, size=-1):
        """拒绝超预算整段读取，不截短 ZIP 元数据让损坏文件蒙混通过。"""
        _cancel_read(self.cancel)
        if size < 0:
            position = self.stream.tell()
            self.stream.seek(0, 2)
            size = self.stream.tell() - position
            self.stream.seek(position)
        if size > self.maximum:
            raise InvalidRequestError("NPZ 元数据读取超过工作预算")
        return self.stream.read(size)

    def seek(self, offset, whence=0):
        """定位不可变快照，不拥有其关闭权限。"""
        return self.stream.seek(offset, whence)

    def tell(self):
        """向标准 ZIP 读取器返回实际文件偏移。"""
        return self.stream.tell()

    def seekable(self):
        """此入口只接现有可寻址文件快照，不接实时流。"""
        return True


class _MemberReader:
    """NumPy 可接受短读；每块检查取消，头部阶段另计总量。"""

    def __init__(self, stream, policy, cancel):
        self.stream, self.policy, self.cancel = stream, policy, cancel
        self.header = True
        self.used = 0

    def read(self, size=-1):
        _cancel_read(self.cancel)
        if size < 0:
            raise InvalidRequestError("NPY 不允许无界成员读取")
        size = min(size, self.policy.chunk_bytes)
        if self.header and size > self.policy.max_header_bytes - self.used:
            raise InvalidRequestError("NPY 头部超过显式预算")
        result = self.stream.read(size)
        self.used += len(result)
        return result


def _inspect_member(reader, member, dtype, shape, policy):
    """使用 NumPy 官方头部读取，拒绝对象、结构类型、错误尺寸及额外记录。"""
    version = np.lib.format.read_magic(reader)
    if version not in ((1, 0), (2, 0)):
        raise InvalidRequestError("轮廓 NPZ 仅接受 NPY 1.0/2.0 数值成员")
    header = (
        np.lib.format.read_array_header_1_0
        if version == (1, 0)
        else np.lib.format.read_array_header_2_0
    )
    actual_shape, _, actual_dtype = header(
        reader, max_header_size=policy.max_header_bytes
    )
    if (
        tuple(actual_shape) != shape
        or actual_dtype.hasobject
        or actual_dtype.fields
        or actual_dtype.subdtype
        or actual_dtype.name != dtype
    ):
        raise InvalidRequestError("轮廓 NPZ 字段形状或精度与声明不一致")
    count = shape[0] * (shape[1] if len(shape) == 2 else 1)
    if reader.used + count * actual_dtype.itemsize != member.file_size:
        raise InvalidRequestError("轮廓 NPZ 成员截断或包含额外记录")


@contextmanager
def borrow_profile_file(stream, spec, *, has_validity, policy, budget, cancel):
    """借用调用方不可变快照；退出释放数组，完整行表包括空轮廓。"""
    cancel()
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    decoded = spec.input_bytes(has_validity=has_validity)
    if (
        not 0 < size <= MAX_POINT_CLOUD_INPUT_BYTES
        or decoded > policy.max_decoded_bytes
    ):
        raise InvalidRequestError("轮廓 NPZ 文件或数组超过输入/解码预算")
    if budget.limit != policy.max_live_array_bytes:
        raise ValueError("轮廓文件预算与运行策略不一致")
    # 标准 ZIP 会先读取中央目录；容量与 NumPy 解码/规范化副本一起预留。
    metadata = min(size, max(policy.max_header_bytes, 65558))
    scratch = (
        metadata * 32 + min(decoded, np.lib.format.BUFFER_SIZE) * 2 + policy.chunk_bytes
    )
    if scratch > policy.max_working_bytes:
        raise InvalidRequestError("轮廓 NPZ 元数据工作预算不足")
    reservation = budget.reserve(decoded * 2 + scratch)
    arrays, value, exposed = {}, None, None
    try:
        reader = _ArchiveReader(stream, metadata, cancel)
        with ZipFile(reader) as archive:
            layout = spec.input_layout(has_validity=has_validity)
            members = archive.infolist()
            expected = {f"{name}.npy" for name, _, _ in layout}
            if (
                len(members) != len(expected)
                or {m.filename for m in members} != expected
                or any(
                    m.is_dir()
                    or m.flag_bits & 1
                    or m.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                    for m in members
                )
            ):
                raise InvalidRequestError("轮廓 NPZ 成员重复、缺失或包含未声明内容")
            if (
                sum(
                    len(m.filename.encode("utf-8")) + len(m.extra) + len(m.comment) + 46
                    for m in members
                )
                > policy.max_header_bytes
            ):
                raise InvalidRequestError("轮廓 NPZ 中央目录超过头部预算")
            # 中央目录已完整校验；成员正文允许使用已预留的 chunk_bytes，
            # 不能继续受目录上限限制而拒绝合法的大数组。
            reader.maximum = max(metadata, policy.chunk_bytes)
            for name, dtype, shape in layout:
                cancel()
                member = archive.getinfo(f"{name}.npy")
                with archive.open(member) as handle:
                    _inspect_member(
                        _MemberReader(handle, policy, cancel),
                        member,
                        dtype,
                        shape,
                        policy,
                    )
                with archive.open(member) as handle:
                    checked = _MemberReader(handle, policy, cancel)
                    # 头部已完成预检；read_array 仍由 NumPy 校验，正文按块读取并核对 CRC。
                    checked.header = False
                    value = np.lib.format.read_array(
                        checked,
                        allow_pickle=False,
                        max_header_size=policy.max_header_bytes,
                    )
                    if handle.read(1):
                        raise InvalidRequestError("轮廓 NPZ 成员包含额外尾部")
                value = np.ascontiguousarray(
                    value, dtype=np.dtype(dtype).newbyteorder("<")
                )
                value.setflags(write=False)
                arrays[name] = value
                value = None
        validate_profile_arrays(
            arrays, spec, has_validity=has_validity, policy=policy, cancel=cancel
        )
        reservation.shrink(decoded)
        exposed = MappingProxyType(arrays)
        yield exposed
    except _ReadCancelled as error:
        release_exception_frames(error)
        raise error.error from None
    except (InvalidRequestError, InterruptedError) as error:
        release_exception_frames(error)
        raise
    except (
        BadZipFile,
        OSError,
        EOFError,
        ValueError,
        KeyError,
        NotImplementedError,
    ) as error:
        release_exception_frames(error)
        if exposed is not None:
            raise
        raise InvalidRequestError("轮廓 NPZ 损坏或不是声明的数值数组文件") from error
    except BaseException as error:
        release_exception_frames(error)
        raise
    finally:
        value = exposed = None
        arrays.clear()
        reservation.close()
