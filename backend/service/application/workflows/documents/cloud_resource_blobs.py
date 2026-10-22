"""计量资源服务的点云 blob 流式操作；不建立第二个资源服务。"""

from dataclasses import dataclass
from hashlib import sha256
from typing import BinaryIO, Callable

from backend.contracts.workflows.point_cloud_assets import ArrayCloudAsset, CloudBlob
from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True, kw_only=True)
class CloudAssetPolicy:
    """管理面显式大小与工作块预算；没有生产缺省值。"""

    max_asset_bytes: int
    max_archive_bytes: int
    chunk_bytes: int

    def __post_init__(self):
        """拒绝布尔、无限容量和大于预算的读取块。"""
        values = (self.max_asset_bytes, self.max_archive_bytes, self.chunk_bytes)
        if any(type(v) is not int or v <= 0 for v in values) or self.chunk_bytes > min(
            values[:2]
        ):
            raise ValueError("点云资产策略必须是显式正整数且读取块不能超过容量")


class CheckedBlobStream:
    """将长度、摘要和取消校验放在同一次有界 ObjectStore 读取中。"""

    def __init__(
        self, source: BinaryIO, blob: CloudBlob, cancel: Callable[[], None], asset=None
    ):
        """借用调用者流，既不 seek 也不接管调用者关闭责任。"""
        self.source, self.blob, self.cancel = source, blob, cancel
        self.digest, self.count, self.complete = sha256(), 0, False
        self.validator = (
            _ArrayBytes(asset, blob) if isinstance(asset, ArrayCloudAsset) else None
        )

    def read(self, size: int) -> bytes:
        """EOF 前不能返回成功，额外字节和短流都拒绝。"""
        self.cancel()
        data = self.source.read(min(size, self.blob.content_length - self.count + 1))
        if not isinstance(data, bytes):
            raise InvalidRequestError("点云数据流必须返回 bytes")
        self.count += len(data)
        if self.count > self.blob.content_length:
            raise InvalidRequestError("点云数据块超过声明长度")
        self.digest.update(data)
        if self.validator is not None:
            self.validator.check(data, self.count - len(data))
        if not data:
            if (
                self.count != self.blob.content_length
                or self.digest.hexdigest() != self.blob.sha256
            ):
                raise InvalidRequestError("点云数据块长度或摘要不匹配")
            self.complete = True
        return data


def cloud_blob_key(service, reference, blob: CloudBlob) -> str:
    """只从已校验资源身份与内容摘要构造对象键。"""
    return (
        service.version_key(reference).rsplit("/", 1)[0]
        + f"/immutable/sha256-{blob.sha256}/content.bin"
    )


def verify_cloud_blobs(service, document, *, policy: CloudAssetPolicy, cancel):
    """读回全量字节验证，不将存储 manifest 当成数据已验证的证明。"""
    cloud = document.content.point_cloud
    if sum(b.content_length for b in cloud.blobs) > policy.max_asset_bytes:
        raise InvalidRequestError("点云资产超过显式容量")
    for blob in cloud.blobs:
        with service.storage.open_read_snapshot(
            cloud_blob_key(service, document.reference, blob)
        ) as snapshot:
            stream = CheckedBlobStream(snapshot.stream, blob, cancel, cloud)
            while stream.read(policy.chunk_bytes):
                pass


class _ArrayBytes:
    """已知二进制布局的值域校验，不是外部文件格式解析器。"""

    def __init__(self, asset, blob):
        self.asset, self.blob, self.tail = asset, blob, b""
        self.ranges = []
        if blob.role == "data":
            cursor = 0
            for field in asset.fields:
                if field.offset_bytes > cursor:
                    self.ranges.append((cursor, field.offset_bytes, 0))
                cursor = field.offset_bytes + field.byte_length
                if field.name in ("validity", "sample_origin"):
                    self.ranges.append(
                        (
                            field.offset_bytes,
                            cursor,
                            1 if field.name == "validity" else 2,
                        )
                    )

    def check(self, data, offset):
        """分块处理掩码、对齐和无符号索引，保留跨块不足一个整数的尾部。"""
        import numpy as np

        if self.blob.role == "indices":
            dtype = np.dtype(self.asset.indices.dtype).newbyteorder("<")
            joined = self.tail + data
            end = len(joined) // dtype.itemsize * dtype.itemsize
            if np.any(
                np.frombuffer(joined[:end], dtype=dtype)
                >= self.asset.indices.source_point_count
            ):
                raise InvalidRequestError("点云源索引越界")
            self.tail = joined[end:]
            if not data and self.tail:
                raise InvalidRequestError("点云源索引截断")
        else:
            for start, stop, maximum in self.ranges:
                first, last = max(offset, start), min(offset + len(data), stop)
                if first < last and np.any(
                    np.frombuffer(
                        data, dtype=np.uint8, count=last - first, offset=first - offset
                    )
                    > maximum
                ):
                    raise InvalidRequestError("点云有效性、来源或对齐字节无效")
