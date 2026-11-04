"""从有界行号分区生成原始显示叶块，预算先于实际分配。"""

from io import BytesIO
from contextlib import closing
import json

import numpy as np
from scipy.spatial import KDTree

from backend.contracts.workflows.point_cloud import FIELD_WIDTHS
from backend.contracts.workflows.point_cloud_detail import (
    CloudDetailIndex,
    detail_index_dtype,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.detail_partition import (
    bounded_partitions,
    row_chunks,
    seed_partition,
)


class DetailBuildBudget:
    """同一构建的工作块和描述对象预留，由调用方在解除引用后统一释放。"""

    def __init__(self, runtime, owners):
        """owners 沿用当前构建 ExitStack，不建立新资源系统。"""
        self.runtime = runtime
        self.owners = owners
        self.used = 0

    def reserve(self, size):
        """同时约束算法工作预算和当前 Run 活跃数组预算。"""
        if size > self.runtime.policy.max_working_bytes - self.used:
            raise InvalidRequestError("空间显示索引超过算法工作预算")
        reservation = self.runtime.budget.reserve(size)
        self.owners.callback(reservation.close)
        self.used += size


def _layout(cloud, source_count):
    """保留全部字段位宽，行号分别选择可容纳最大身份的无损整数。"""
    fields, dtype, offset = [], [], 0
    for number, field in enumerate(cloud.fields):
        fields.append({**field.model_dump(mode="json"), "offset": offset})
        dtype.append(
            (f"f{number}", np.dtype(field.dtype).newbyteorder("<"), (field.components,))
        )
        offset += FIELD_WIDTHS[field.dtype] * field.components
    logical = detail_index_dtype(cloud.point_count)
    identity = detail_index_dtype(
        source_count if cloud.vertex_kind == "source" else cloud.point_count
    )
    if cloud.lineage_kind == "voxel-aggregate":
        dtype += [("voxel_keys", "<i8", (3,)), ("member_counts", "<u8")]
        offset += 32
    dtype += [
        ("logical", np.dtype(logical).newbyteorder("<")),
        ("identity", np.dtype(identity).newbyteorder("<")),
    ]
    return fields, np.dtype(dtype), logical, identity, offset


def build_index(runtime, cloud, service, root, generation, policy, cancel, owners):
    """分盘过程只保留有界块，局部 KDTree 不改变源点或测量算法。"""
    source_count = runtime.source_point_count(cloud)
    fields, dtype, logical, identity, offset = _layout(cloud, source_count)
    budget = DetailBuildBudget(runtime, owners)
    # 描述、Pydantic 副本和最终 JSON 编码一起预留；增量块随后逐个计费。
    descriptor_bytes = len(json.dumps(fields, ensure_ascii=False).encode("utf-8"))
    budget.reserve(4096 + descriptor_bytes * 16)
    # 极小叶时每点最多对应近两个原生节点及 Python 包装/dict；
    # 连同 double 坐标/行号/掩码计费，字段 gather/打包副本另按位宽计费。
    per_row = 1024 + dtype.itemsize * 4
    available = min(
        runtime.policy.max_working_bytes - budget.used,
        runtime.budget.limit - runtime.budget.used,
    )
    rows = min(runtime.policy.chunk_rows, available // (per_row * 2))
    leaf_limit = min(
        rows,
        policy.preview.max_points,
        policy.preview.max_data_bytes // dtype.itemsize,
        policy.preview.max_working_bytes // (dtype.itemsize * 3 + 64),
    )
    if rows < 1 or leaf_limit < 1:
        raise InvalidRequestError("点云细节工作块超过显式预算")
    # 临时文件只保存逻辑行号，拆分时父子并存最多两份。每行叶记录
    # 包含 XYZ，必然不小于两份逻辑行号，因此临时数据不会突破此上界。
    if cloud.point_count * dtype.itemsize > policy.max_asset_bytes:
        raise InvalidRequestError("点云细节数据超过显式资产预算")
    budget.reserve(rows * per_row)
    directory = service.storage.resolve(root)
    directory.mkdir(parents=True, exist_ok=False)
    row_dtype = np.dtype(logical).newbyteorder("<")
    blocks = []
    with runtime.borrow(cloud) as view:
        seed = seed_partition(view, directory, row_dtype, rows, cancel)
        if not seed.count:
            raise InvalidRequestError("资产没有可显示的有效位置")
        with closing(
            bounded_partitions(view, seed, row_dtype, rows, cancel)
        ) as partitions:
            for partition in partitions:
                with closing(row_chunks(partition, row_dtype, rows, cancel)) as chunks:
                    for selected in chunks:
                        _write_partition(
                            view,
                            selected,
                            fields,
                            dtype,
                            leaf_limit,
                            service,
                            root,
                            runtime.policy.chunk_bytes,
                            cancel,
                            blocks,
                            budget,
                            policy.preview,
                        )
        cancel()
        return CloudDetailIndex.model_validate(
            dict(
                source=cloud.source.reference,
                generation=generation,
                spatial=cloud.spatial,
                vertex_kind=cloud.vertex_kind,
                point_count=cloud.point_count,
                source_point_count=source_count,
                valid_count=seed.count,
                excluded_count=cloud.point_count - seed.count,
                bounds=dict(min=seed.low.tolist(), max=seed.high.tolist()),
                fields=fields,
                normal_info=cloud.normal_info,
                row_bytes=dtype.itemsize,
                logical_dtype=logical,
                identity_dtype=identity,
                logical_offset=offset,
                identity_offset=offset + row_dtype.itemsize,
                leaf_limit=leaf_limit,
                blocks=blocks,
                voxel=dict(
                    keys_offset=offset - 32,
                    members_offset=offset - 8,
                    aggregation=cloud.voxel_aggregation,
                    grid=cloud.voxel_grid,
                )
                if cloud.lineage_kind == "voxel-aggregate"
                else None,
            )
        )


def _write_partition(
    view,
    rows,
    fields,
    dtype,
    leaf_limit,
    service,
    root,
    chunk_bytes,
    cancel,
    blocks,
    budget,
    preview,
):
    """局部树只持有当前分区；字段 gather 和输出块同受既有上限约束。"""
    values, _ = view.gather(rows)
    coordinates = np.asarray(values["positions"], dtype=np.float64)
    del values
    cancel()
    tree = KDTree(
        coordinates,
        leafsize=leaf_limit,
        balanced_tree=True,
        compact_nodes=True,
        copy_data=False,
    )
    cancel()
    pending = [tree.tree]
    while pending:
        cancel()
        node = pending.pop()
        if isinstance(node, KDTree.innernode):
            pending.extend((node.greater, node.less))
            continue
        for start in range(0, len(node.idx), leaf_limit):
            cancel()
            indices = node.idx[start : start + leaf_limit]
            chosen = rows[indices]
            values, identity = view.gather(chosen)
            records = np.empty(len(chosen), dtype=dtype)
            for number, field in enumerate(fields):
                records[f"f{number}"] = values[field["name"]]
            records["logical"], records["identity"] = chosen, identity
            if view.reference.lineage_kind == "voxel-aggregate":
                keys, counts = view.voxel_metadata_rows(chosen)
                records["voxel_keys"], records["member_counts"] = keys, counts
            points = coordinates[indices]
            content = records.tobytes()
            receipt = service.storage.write_immutable_stream(
                object_prefix=root,
                source_stream=BytesIO(content),
                media_type="application/octet-stream",
                extension="bin",
                chunk_size=chunk_bytes,
            )
            block = dict(
                block_id=len(blocks),
                count=len(chosen),
                bounds=dict(
                    min=points.min(axis=0).tolist(), max=points.max(axis=0).tolist()
                ),
                byte_length=len(content),
                sha256=receipt.metadata.checksum,
            )
            size = len(json.dumps(block, ensure_ascii=False, indent=2).encode("utf-8"))
            # 至少这些字节必然进入最终描述，早拒绝过多叶块；最终还精确检查总正文。
            if (len(blocks) + 1) * 128 > preview.max_body_bytes:
                raise InvalidRequestError("点云细节索引超过显式描述预算")
            budget.reserve(1024 + size * 16)
            blocks.append(block)
