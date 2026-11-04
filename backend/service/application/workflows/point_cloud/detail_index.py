"""worker 内准备资产显示索引；API 只读取已提交的有限块。"""

from contextlib import ExitStack
from hashlib import sha256
import json
from uuid import uuid4
import re

from backend.contracts.workflows.point_cloud_detail import CloudDetailIndex
from backend.service.application.workflows.point_cloud.detail_builder import build_index
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.infrastructure.filesystem.shared_files import open_shared_read


def index_root(service, reference):
    """仅由已校验资源身份定位同一版本下的可重建派生文件。"""
    return service.version_key(reference).rsplit("/", 1)[0] + "/display-index"


def read_index(service, reference, *, project_id, policy):
    """先核对项目及源资产，删除或旧身份不能通过缓存继续读取。"""
    service.read(reference, project_id=project_id)
    path = service.storage.resolve(index_root(service, reference) + "/index.json")
    try:
        with open_shared_read(path) as stream:
            content = stream.read(policy.max_body_bytes + 1)
    except FileNotFoundError as error:
        raise ResourceNotFoundError(
            "原始细节尚未准备，请在 Cloud Preview 中显式准备资产细节"
        ) from error
    if len(content) > policy.max_body_bytes:
        raise InvalidRequestError("点云细节索引超过显式描述预算")
    try:
        index = CloudDetailIndex.model_validate_json(content)
    except ValueError as error:
        raise InvalidRequestError("点云细节索引损坏，需要重新准备") from error
    if index.source != reference:
        raise InvalidRequestError("点云细节索引来源不一致")
    return index


def read_block(service, reference, block_id, *, generation, project_id, policy):
    """每块验证实际字节；不在请求处理器重建、解码或扫描原云。"""
    index = read_index(service, reference, project_id=project_id, policy=policy)
    if index.generation != generation:
        raise InvalidRequestError("点云细节索引已更新，请重新加载")
    if not 0 <= block_id < len(index.blocks):
        raise ResourceNotFoundError("点云细节块不存在")
    block = index.blocks[block_id]
    if block.byte_length > policy.max_data_bytes:
        raise InvalidRequestError("点云细节块超过当前显示传输预算")
    key = (
        index_root(service, reference)
        + f"/{index.generation}/immutable/sha256-{block.sha256}/content.bin"
    )
    with service.storage.open_read_snapshot(
        key, expected_checksum=block.sha256
    ) as snapshot:
        data = snapshot.stream.read(block.byte_length + 1)
    if len(data) != block.byte_length or sha256(data).hexdigest() != block.sha256:
        raise InvalidRequestError("点云细节块长度或摘要不一致")
    return data


def prepare_index(runtime, cloud, *, service, project_id, policy, cancel):
    """仅对完整资产引用准备；当前变换/裁剪输出必须先显式保存并重读。"""
    if cloud.source.kind != "asset" or cloud.state != "ready":
        raise InvalidRequestError("原始细节需要已保存并读取的完整点云资产")
    reference = cloud.source.reference
    root = index_root(service, reference)
    with runtime.producing(), service.mutation(project_id):
        document = service.read(reference, project_id=project_id)
        if document.content.point_cloud.point_count != cloud.point_count:
            raise InvalidRequestError("显示点云不等于来源资产")
        # 预算变小或旧描述损坏时也不能提前删除已提交代次。
        # 残留代次只在新索引完整提交后或删除源资产时统一回收。
        owners = ExitStack()
        generation = uuid4().hex
        pending_root = root + "/" + generation
        try:
            result = build_index(
                runtime,
                cloud,
                service,
                pending_root,
                generation,
                policy,
                cancel,
                owners,
            )
            payload = result.model_dump(mode="json")
            # 与现有 ObjectStore.write_json 的实际 UTF-8 格式一致计费。
            if (
                len(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
                > policy.preview.max_body_bytes
            ):
                raise InvalidRequestError("点云细节索引超过显式描述预算")
            cancel()
            # 源资源与删除共用既有 Project 锁，完整块写完后才原子提交索引。
            service.storage.write_json(root + "/index.json", payload)
        except BaseException as error:
            release_exception_frames(error)
            service.storage.delete_tree(pending_root)
            raise
        finally:
            owners.close()
        _prune(service, root, generation)
        return result


def _prune(service, root, keep):
    """仅回收本模块生成的代次目录，不触及源资产或任意路径。"""
    path = service.storage.resolve(root)
    if path.is_dir():
        for child in path.iterdir():
            if re.fullmatch(r"[0-9a-f]{32}", child.name) and child.name != keep:
                service.storage.delete_tree(root + "/" + child.name)
