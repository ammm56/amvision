"""Preview 文件输入的只读内存 ObjectStore，不把上传物化为临时文件。"""

from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4

from backend.service.application.errors import InvalidRequestError
from backend.service.application.ports.object_store import ObjectReadSnapshot, ObjectSnapshotMetadata
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class PreviewInputStore(LocalDatasetStorage):
    """既有持久对象仍由本地存储读取；本次上传的不可变对象仅存在于此实例。"""

    def __init__(self, storage, project_id, session_id):
        """复用既有根目录配置，构造时不创建任何目录。"""
        self.settings, self.root_dir = storage.settings, storage.root_dir
        self.prefix = f"projects/{project_id}/preview-inputs/{session_id}/"
        self.files = {}

    def register(self, content, *, media_type, file_name):
        """生成进程内只读引用，校验与节点读取使用同一份 identity。"""
        version = uuid4().hex
        key = self.prefix + version
        checksum = sha256(content).hexdigest()
        metadata = ObjectSnapshotMetadata(object_key=key, content_length=len(content), media_type=media_type,
                                          checksum_algorithm="sha256", checksum=checksum, immutable_version=version, is_immutable=True)
        self.files[key] = (metadata, content)
        return {"transport_kind": "storage", "storage_ref": "object-store", "object_key": key,
                "file_name": PurePosixPath(file_name.replace("\\", "/")).name or "input",
                "media_type": media_type, "content_length": len(content), "checksum_algorithm": "sha256",
                "checksum": checksum, "immutable_version": version}

    def resolve(self, relative_path):
        """内存对象无磁盘路径；依赖实际文件路径的节点必须显式保存后使用。"""
        if "/preview-inputs/" in str(relative_path):
            raise InvalidRequestError("Preview 临时文件只能通过 ObjectStore 读取，不能转换为磁盘路径")
        return super().resolve(relative_path)

    def stat_object(self, object_key):
        """内存对象直接读取登记元数据，不访问文件系统。"""
        item = self.files.get(object_key)
        return item[0] if item else super().stat_object(object_key)

    @contextmanager
    def open_read_snapshot(self, object_key, *, expected_version=None, expected_checksum=None):
        """读取期间内容固定，错误 identity 不得退回本地路径。"""
        item = self.files.get(object_key)
        if item is None:
            with super().open_read_snapshot(object_key, expected_version=expected_version, expected_checksum=expected_checksum) as snapshot:
                yield snapshot
            return
        metadata, content = item
        if expected_version is not None and expected_version != metadata.immutable_version or expected_checksum is not None and expected_checksum != metadata.checksum:
            raise InvalidRequestError("Preview 文件引用版本或摘要不一致")
        with BytesIO(content) as stream:
            yield ObjectReadSnapshot(stream=stream, metadata=metadata)

    def clear(self):
        """图执行结束后释放上传内容，不留下持久对象。"""
        self.files.clear()
