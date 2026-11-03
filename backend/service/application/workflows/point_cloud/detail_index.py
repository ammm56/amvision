"""worker 内准备资产显示索引；API 只读取已提交的有限块。"""

from hashlib import sha256
from io import BytesIO
import json
from uuid import uuid4
import re

import numpy as np
from scipy.spatial import KDTree

from backend.contracts.workflows.point_cloud import FIELD_WIDTHS
from backend.contracts.workflows.point_cloud_detail import CloudDetailIndex
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
        # 原生树最坏节点、double 坐标及行映射计入预算，不只计 Python 数组。
        reserve = cloud.point_count * 192
        if reserve > runtime.policy.max_working_bytes:
            raise InvalidRequestError("空间显示索引超过算法工作预算")
        reservation = runtime.budget.reserve(reserve)
        generation = uuid4().hex
        pending_root = root + "/" + generation
        try:
            result = _build(
                runtime, cloud, service, pending_root, generation, policy, cancel
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
            reservation.close()
        _prune(service, root, generation)
        return result


def _prune(service, root, keep):
    """仅回收本模块生成的代次目录，不触及源资产或任意路径。"""
    path = service.storage.resolve(root)
    if path.is_dir():
        for child in path.iterdir():
            if re.fullmatch(r"[0-9a-f]{32}", child.name) and child.name != keep:
                service.storage.delete_tree(root + "/" + child.name)


def _build(runtime, cloud, service, root, generation, policy, cancel):
    """SciPy KDTree 分区，全部叶点原样保存；重复点叶块再按容量分块。"""
    fields, dtype, offset = [], [], 0
    for number, field in enumerate(cloud.fields):
        fields.append({**field.model_dump(mode="json"), "offset": offset})
        dtype.append(
            (f"f{number}", np.dtype(field.dtype).newbyteorder("<"), (field.components,))
        )
        offset += FIELD_WIDTHS[field.dtype] * field.components
    dtype += [("logical", "<u8"), ("identity", "<u8")]
    record_dtype = np.dtype(dtype)
    leaf_limit = min(
        runtime.policy.chunk_rows,
        policy.preview.max_points,
        policy.preview.max_data_bytes // record_dtype.itemsize,
        policy.preview.max_working_bytes // (record_dtype.itemsize * 3 + 64),
    )
    if (
        leaf_limit < 1
        or cloud.point_count * record_dtype.itemsize > policy.max_asset_bytes
    ):
        raise InvalidRequestError("点云细节数据超过显式显示或资产预算")
    coordinates = np.empty((cloud.point_count, 3), dtype=np.float64)
    logical = np.empty(cloud.point_count, dtype=np.int64)
    valid_count = 0
    with runtime.borrow(cloud) as view:
        for start in range(0, cloud.point_count, runtime.policy.chunk_rows):
            cancel()
            stop = min(start + runtime.policy.chunk_rows, cloud.point_count)
            values = view.chunk(start, stop)
            valid = np.isfinite(values["positions"]).all(axis=1)
            if "validity" in values:
                valid &= values["validity"].reshape(-1) != 0
            rows = np.flatnonzero(valid)
            count = len(rows)
            coordinates[valid_count : valid_count + count] = values["positions"][rows]
            logical[valid_count : valid_count + count] = rows + start
            valid_count += count
        if not valid_count:
            raise InvalidRequestError("资产没有可显示的有效位置")
        cancel()
        tree = KDTree(
            coordinates[:valid_count],
            leafsize=leaf_limit,
            balanced_tree=True,
            compact_nodes=True,
            copy_data=False,
        )
        cancel()
        pending, blocks = [tree.tree], []
        while pending:
            cancel()
            node = pending.pop()
            if isinstance(node, KDTree.innernode):
                pending.extend((node.greater, node.less))
                continue
            indices = node.idx
            for start in range(0, len(indices), leaf_limit):
                cancel()
                selected = indices[start : start + leaf_limit]
                rows = logical[selected]
                values, identity = view.gather(rows)
                records = np.empty(len(rows), dtype=record_dtype)
                for number, field in enumerate(cloud.fields):
                    records[f"f{number}"] = values[field.name]
                records["logical"], records["identity"] = rows, identity
                points = coordinates[selected]
                bounds = dict(
                    min=points.min(axis=0).tolist(), max=points.max(axis=0).tolist()
                )
                content = records.tobytes()
                receipt = service.storage.write_immutable_stream(
                    object_prefix=root,
                    source_stream=BytesIO(content),
                    media_type="application/octet-stream",
                    extension="bin",
                    chunk_size=runtime.policy.chunk_bytes,
                )
                blocks.append(
                    dict(
                        block_id=len(blocks),
                        count=len(rows),
                        bounds=bounds,
                        byte_length=len(content),
                        sha256=receipt.metadata.checksum,
                    )
                )
        return CloudDetailIndex.model_validate(
            dict(
                source=cloud.source.reference,
                generation=generation,
                spatial=cloud.spatial,
                vertex_kind=cloud.vertex_kind,
                point_count=cloud.point_count,
                source_point_count=runtime.source_point_count(cloud),
                valid_count=valid_count,
                excluded_count=cloud.point_count - valid_count,
                bounds=dict(min=tree.mins.tolist(), max=tree.maxes.tolist()),
                fields=fields,
                row_bytes=record_dtype.itemsize,
                logical_offset=offset,
                identity_offset=offset + 8,
                leaf_limit=leaf_limit,
                blocks=blocks,
            )
        )
