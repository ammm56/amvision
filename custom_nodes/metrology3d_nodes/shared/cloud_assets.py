"""点云节点与既有计量资源服务的适配；保存和恢复不经整云 bytes。"""

from contextlib import ExitStack
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.measurement_resources import (
    MeasurementResourceContent,
)
from backend.contracts.workflows.metrology import ResourceReference
from backend.contracts.workflows.point_cloud import FIELD_WIDTHS
from backend.contracts.workflows.point_cloud_assets import (
    ArrayCloudAsset,
    AssetFileSource,
    AssetLocalSource,
    AssetProvenance,
    CloudAssetField,
    CloudBlob,
    CloudSourceNames,
    OriginalCloudAsset,
    RasterCloudAsset,
    ProfileCloudAsset,
)
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CheckedBlobStream,
    cloud_blob_key,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.io.read_file import read_cloud_file
from custom_nodes.metrology3d_nodes.shared.cloud_lineage_assets import (
    lineage_chunks,
    count_lineage_members,
)
from backend.service.application.workflows.point_cloud.lineage import lineage_shapes
from backend.contracts.workflows.point_cloud_assets import (
    AssetGeneratedLineage,
    AssetProfileLineage,
    AssetVoxelLineage,
)
from backend.service.application.workflows.point_cloud.voxel_lineage import (
    voxel_lineage_shapes,
)
from backend.service.application.workflows.point_cloud.profile_lineage import (
    profile_lineage_shapes,
)
from custom_nodes.metrology3d_nodes.shared.raster_assets import (
    freeze_raster_source,
    original_raster_content,
    restore_raster_asset,
)
from custom_nodes.metrology3d_nodes.shared.profile_assets import (
    freeze_profile_source,
    original_profile_content,
    restore_profile_asset,
)
from backend.service.application.workflows.point_cloud.profile_rows import row_chunks


class _Chunks:
    """将有界块迭代器接到 ObjectStore 的读取接口，不提供伪造 seek。"""

    def __init__(self, chunks):
        self.chunks, self.pending = iter(chunks), b""

    def read(self, size):
        if not self.pending:
            self.pending = next(self.chunks, b"")
        result, self.pending = self.pending[:size], self.pending[size:]
        return result


def _source(reference, options):
    """冻结原始输入描述，不保存系统路径、运行 ID 或租约。"""
    if reference.source.kind == "file":
        file = reference.source.file
        return AssetFileSource(
            kind="file",
            file_name=file["file_name"],
            content_length=file["content_length"],
            content_sha256=file["checksum"],
            profile_id=options.profile_id,
            profile_version=options.profile_version,
            source_observation_id=reference.source.source_observation_id,
        )
    if reference.source.kind == "local-array":
        return AssetLocalSource.model_validate(reference.source.model_dump())
    if reference.source.kind == "calibrated-raster":
        return freeze_raster_source(reference.source)
    if reference.source.kind == "calibrated-profiles":
        return freeze_profile_source(reference.source)
    raise InvalidRequestError("来源不是可直接保存的原始输入")


def freeze_cloud_parent(runtime, reference):
    """冻结源内容描述，不把当前 run/cloud ID 当成持久摘要。"""
    if reference.source.kind == "asset":
        return {
            "content_sha256": reference.source.reference.sha256,
            "reference": reference.source.reference.model_dump(mode="json"),
        }
    parent = runtime.parent_reference(reference)
    root, options = runtime.original_source(reference)
    descriptor = {
        "point_count": reference.point_count,
        "vertex_kind": reference.vertex_kind,
        "topology": reference.topology.model_dump(mode="json")
        if reference.topology
        else None,
        "fields": [f.model_dump(mode="json") for f in reference.fields],
        "normal_info": reference.normal_info.model_dump(mode="json")
        if reference.normal_info
        else None,
        "spatial": reference.spatial.model_dump(mode="json"),
        "source_metadata": reference.source_metadata.model_dump(mode="json")
        if reference.source_metadata
        else None,
        "method": reference.provenance.method.model_dump(mode="json")
        if reference.provenance.method
        else None,
        "parents": [freeze_cloud_parent(runtime, parent)] if parent else [],
        "source": _source(root, options).model_dump(mode="json")
        if root.source.kind != "asset"
        else root.source.model_dump(mode="json"),
    }
    return {
        "content_sha256": sha256(canonical_cloud_json(descriptor)).hexdigest(),
        "reference": None,
    }


def _stored_field_names(reference, options):
    """保留原字段别名，计算字段用明确规范名称，不伪造原始文件列。"""
    if not options or reference.vertex_kind != "source":
        return ()
    existing = {m.target_name: m.source_names for m in options.field_mapping}
    canonical = {"normals": ("nx", "ny", "nz")}
    return tuple(
        CloudSourceNames(
            name=f.name,
            source_names=existing.get(f.name, canonical.get(f.name, (f.name,))),
        )
        for f in reference.fields
    )


def _layout(reference):
    """构造所有字段的精确 little-endian 存储布局，包含对齐间隙。"""
    fields, cursor = [], 0
    for field in reference.fields:
        width = FIELD_WIDTHS[field.dtype]
        offset = (cursor + width - 1) // width * width
        size = reference.point_count * field.components * width
        fields.append(
            CloudAssetField(
                **field.model_dump(),
                count=reference.point_count,
                offset_bytes=offset,
                byte_length=size,
            )
        )
        cursor = offset + size
    return tuple(fields), cursor


def _chunks(view, fields, rows, cancel):
    """分字段写入，不物化逻辑子集或改变 NaN 位模式。"""
    cursor = 0
    for field in fields:
        if field.offset_bytes > cursor:
            yield bytes(field.offset_bytes - cursor)
        for start in range(0, view.reference.point_count, rows):
            cancel()
            yield view.chunk(start, min(start + rows, view.reference.point_count))[
                field.name
            ].tobytes(order="C")
        cursor = field.offset_bytes + field.byte_length


def _index_chunks(view, rows, dtype, cancel):
    """源行号按原始总点数选择宽度，不经浮点数转换。"""
    for start in range(0, view.reference.point_count, rows):
        cancel()
        yield (
            view.source_indices(start, min(start + rows, view.reference.point_count))
            .astype(dtype, copy=False)
            .tobytes()
        )


def _blob(role, name, chunks):
    """对将写入的同一不可变视图计算长度和摘要，不分配整块数据。"""
    digest, size = sha256(), 0
    for chunk in chunks:
        size += len(chunk)
        digest.update(chunk)
    return CloudBlob(
        role=role, name=name, content_length=size, sha256=digest.hexdigest()
    )


def save_cloud(
    runtime,
    reference,
    *,
    service,
    project_id,
    name,
    mode,
    write_identity,
    policy,
    cancel,
    expected_base=None,
    actor_id=None,
    features=None,
    height_map=None,
    sampling=None,
    edge=None,
    evidence=None,
):
    """保存原件或全部派生字段；已提交版本由服务拥有，不归运行 Scope 删除。"""
    if mode not in ("original", "derived"):
        raise InvalidRequestError("点云保存模式无效")
    from custom_nodes.metrology3d_nodes.shared.boundary_assets import freeze_boundary

    boundary = freeze_boundary(reference, features, mode)
    arc_evidence = None
    if evidence is not None:
        from custom_nodes.metrology3d_nodes.shared.arc_assets import freeze_arc_evidence

        arc_evidence = freeze_arc_evidence(
            runtime, reference, boundary, evidence, cancel=cancel
        )
    policy = replace(
        policy,
        chunk_bytes=min(
            policy.chunk_bytes,
            runtime.policy.chunk_bytes,
            runtime.policy.max_working_bytes,
        ),
    )
    root, options = runtime.original_source(reference)
    selected = root if mode == "original" else reference
    with runtime.producing(), ExitStack() as stack:
        view = stack.enter_context(runtime.borrow(selected))
        if selected.source.kind == "asset" and (
            (height_map is None and sampling is None and edge is None)
            or isinstance(
                service.read(
                    selected.source.reference, project_id=project_id
                ).content.point_cloud,
                ArrayCloudAsset,
            )
        ):
            document = service.read(selected.source.reference, project_id=project_id)
            cloud = document.content.point_cloud
            if mode == "original" and cloud.source.kind == "derived":
                document = _original_asset(service, document, project_id)
                cloud = document.content.point_cloud
            content = document.content
            streams = {
                blob.name: stack.enter_context(
                    service.storage.open_read_snapshot(
                        cloud_blob_key(service, document.reference, blob)
                    )
                ).stream
                for blob in cloud.blobs
            }
        elif (
            mode == "original"
            and root.source.kind in ("calibrated-raster", "calibrated-profiles")
            and root.source.file is not None
        ):
            content = (
                original_raster_content(root)
                if root.source.kind == "calibrated-raster"
                else original_profile_content(root)
            )
            streams = {
                "original.bin": stack.enter_context(
                    service.storage.open_read_snapshot(
                        root.source.file["object_key"],
                        expected_checksum=root.source.content_sha256,
                        expected_version=root.source.file["immutable_version"],
                    )
                ).stream
            }
        elif mode == "original" and root.source.kind == "file":
            source = _source(root, options)
            blob = CloudBlob(
                role="original",
                name="original.bin",
                content_length=source.content_length,
                sha256=source.content_sha256,
            )
            cloud = OriginalCloudAsset(
                format_id="amvision.point-cloud-asset.v1",
                kind="point-cloud",
                representation="file-original",
                source=source,
                spatial=root.spatial,
                provenance=AssetProvenance(
                    method=None, parents=(), source_retained=True
                ),
                blobs=(blob,),
                source_field_names=tuple(
                    CloudSourceNames(name=m.target_name, source_names=m.source_names)
                    for m in options.field_mapping
                ),
                parent_assets=(),
                point_count=root.point_count,
                source_metadata=root.source_metadata,
                original_format="ply"
                if options.profile_id.startswith("ply-")
                else "pcd"
                if options.profile_id.startswith("pcd-")
                else "xyz",
                original_file_name=source.file_name,
                profile_id=options.profile_id,
                profile_version=options.profile_version,
                fields=root.fields,
                vertex_kind="source",
                topology=None,
            )
            content = MeasurementResourceContent(kind="point-cloud", point_cloud=cloud)
            streams = {
                "original.bin": stack.enter_context(
                    service.storage.open_read_snapshot(
                        root.source.file["object_key"],
                        expected_checksum=source.content_sha256,
                    )
                ).stream
            }
        else:
            # 只读取已绑定的根资产，沿用其中已校验的来源，不猜测历史父链。
            if root.source.kind == "asset":
                root_cloud = service.read(
                    root.source.reference, project_id=project_id
                ).content.point_cloud
                source, source_count = root_cloud.original_observation()
                if source_count != runtime.source_point_count(selected):
                    raise InvalidRequestError("保存来源与运行原始总点数不一致")
            else:
                source = _source(root, options)
            fields, length = _layout(selected)
            row_size = sum(FIELD_WIDTHS[f.dtype] * f.components for f in fields)
            rows = min(
                runtime.policy.chunk_rows,
                runtime.policy.max_working_bytes // (row_size * 2 + 32),
                policy.chunk_bytes // max(8, row_size),
            )
            if rows < 1:
                raise InvalidRequestError("点云保存块预算不能容纳一行")
            parent = runtime.parent_reference(selected)
            parent_description = (
                freeze_cloud_parent(runtime, parent) if parent else None
            )
            parents = (parent_description,) if parent else ()
            retained = tuple(
                p["reference"] for p in parents if p["reference"] is not None
            )
            retained_originals = bool(retained) and all(
                service.read(
                    ResourceReference.model_validate(r), project_id=project_id
                ).content.point_cloud.provenance.source_retained
                for r in retained
            )
            source_count = runtime.source_point_count(selected)
            index_dtype = "uint32" if source_count <= 2**32 else "uint64"

            def data_factory():
                return _chunks(view, fields, rows, cancel)

            blobs = [_blob("data", "data.bin", data_factory())]
            streams = {"data.bin": _Chunks(data_factory())}
            if source.kind == "calibrated-profiles":
                table = stack.enter_context(runtime.borrow_profile_rows(selected))

                def profile_factory():
                    return row_chunks(
                        table,
                        source.profiles,
                        chunk_bytes=policy.chunk_bytes,
                        cancel=cancel,
                    )

                rows_blob = _blob("profile-rows", "profile-rows.bin", profile_factory())
                if rows_blob.sha256 != source.row_table_sha256:
                    raise InvalidRequestError("保存轮廓原行表与观测摘要不一致")
                blobs.append(rows_blob)
                streams[rows_blob.name] = _Chunks(profile_factory())
            indices = None
            lineage = None
            if selected.vertex_kind == "generated":
                if selected.lineage_kind == "grid-profile":
                    profile_arrays = view.profile_lineage_snapshot()
                    lineage = AssetProfileLineage(
                        kind="grid-profile",
                        source_point_count=source_count,
                        cell_count=len(profile_arrays["cell_indices"]),
                        source_count=len(profile_arrays["cell_sources"]),
                        source=source,
                    )
                    rows = min(
                        rows,
                        runtime.policy.max_working_bytes // 2 // (row_size * 2 + 32),
                    )
                    if rows < 1:
                        raise InvalidRequestError("剖面保存剩余工作预算不足")

                    def lineage_factory():
                        for array in profile_arrays.values():
                            for start in range(0, len(array), rows):
                                cancel()
                                yield array[start : start + rows].tobytes(order="C")
                else:
                    count = count_lineage_members(view, rows, cancel)
                    lineage = (
                        AssetVoxelLineage(
                            kind="voxel-aggregate",
                            source_point_count=source_count,
                            member_count=count,
                            source_dtype=index_dtype,
                            source=source,
                            aggregation=selected.voxel_aggregation,
                            grid=selected.voxel_grid,
                        )
                        if selected.lineage_kind == "voxel-aggregate"
                        else AssetGeneratedLineage(
                            source_point_count=source_count,
                            face_count=count,
                            source=source,
                        )
                    )

                    def lineage_factory():
                        return lineage_chunks(view, rows, cancel)

                blobs.append(_blob("lineage", "lineage.bin", lineage_factory()))
                streams["lineage.bin"] = _Chunks(lineage_factory())
            elif parent:

                def index_factory():
                    return _index_chunks(view, rows, index_dtype, cancel)

                blobs.append(_blob("indices", "source-indices.bin", index_factory()))
                streams["source-indices.bin"] = _Chunks(index_factory())
                indices = {
                    "dtype": index_dtype,
                    "count": selected.point_count,
                    "source_point_count": source_count,
                    "source": source,
                }
            cloud = ArrayCloudAsset(
                format_id="amvision.point-cloud-asset.v1",
                kind="point-cloud",
                representation="array-blocks",
                source={"kind": "derived"} if parent else source,
                spatial=selected.spatial,
                provenance=AssetProvenance(
                    method=selected.provenance.method,
                    parents=parents,
                    source_retained=retained_originals and len(retained) == len(parents)
                    if parent
                    else True,
                ),
                blobs=tuple(blobs),
                source_field_names=_stored_field_names(selected, options),
                parent_assets=retained,
                point_count=selected.point_count,
                source_metadata=selected.source_metadata,
                fields=fields,
                content_length=length,
                indices=indices,
                lineage=lineage,
                vertex_kind=selected.vertex_kind,
                topology=selected.topology,
                normal_info=selected.normal_info,
            )
            content = MeasurementResourceContent(kind="point-cloud", point_cloud=cloud)
        # 资产原样复制保留已存证据；新增证据必须先通过完整支持身份校验。
        if boundary is not None:
            payload = content.model_dump(mode="json")
            payload["point_cloud"].pop("circle", None)
            payload["point_cloud"].pop("arc_evidence", None)
            payload["point_cloud"]["boundary"] = None
            payload["point_cloud"][boundary.kind] = boundary.model_dump(mode="json")
            content = MeasurementResourceContent.model_validate(payload)
        if arc_evidence is not None:
            payload = content.model_dump(mode="json")
            payload["point_cloud"]["arc_evidence"] = [
                i.model_dump(mode="json") for i in arc_evidence
            ]
            content = MeasurementResourceContent.model_validate(payload)
        if height_map is not None:
            from custom_nodes.metrology3d_nodes.shared.height_map_assets import (
                prepare_height_map,
            )

            evidence, blob, stream = stack.enter_context(
                prepare_height_map(
                    runtime,
                    selected,
                    height_map,
                    mode=mode,
                    chunk_bytes=policy.chunk_bytes,
                    cancel=cancel,
                )
            )
            payload = content.model_dump(mode="json")
            payload["point_cloud"]["height_map"] = evidence.model_dump(mode="json")
            payload["point_cloud"]["blobs"] = [
                b for b in payload["point_cloud"]["blobs"] if b["role"] != "height-map"
            ] + [blob.model_dump(mode="json")]
            content = MeasurementResourceContent.model_validate(payload)
            streams[blob.name] = stream
        if sampling is not None:
            from custom_nodes.metrology3d_nodes.shared.edge_sampling_assets import (
                prepare_sampling,
            )

            evidence, blob, stream = stack.enter_context(
                prepare_sampling(
                    runtime,
                    selected,
                    sampling,
                    mode=mode,
                    chunk_bytes=policy.chunk_bytes,
                    cancel=cancel,
                )
            )
            payload = content.model_dump(mode="json")
            payload["point_cloud"]["sampling"] = evidence.model_dump(mode="json")
            payload["point_cloud"]["blobs"] = [
                b for b in payload["point_cloud"]["blobs"] if b["role"] != "sampling"
            ] + [blob.model_dump(mode="json")]
            content = MeasurementResourceContent.model_validate(payload)
            streams[blob.name] = stream
        if edge is not None:
            from custom_nodes.metrology3d_nodes.shared.edge_assets import prepare_edge

            evidence, blob, stream = stack.enter_context(
                prepare_edge(
                    runtime,
                    selected,
                    edge,
                    mode=mode,
                    chunk_bytes=policy.chunk_bytes,
                    cancel=cancel,
                    height_evidence=content.point_cloud.height_map,
                )
            )
            payload = content.model_dump(mode="json")
            payload["point_cloud"]["edge"] = evidence.model_dump(mode="json")
            payload["point_cloud"]["blobs"] = [
                b for b in payload["point_cloud"]["blobs"] if b["role"] != "edge"
            ] + [blob.model_dump(mode="json")]
            content = MeasurementResourceContent.model_validate(payload)
            streams[blob.name] = stream
        return service.save_cloud(
            project_id=project_id,
            name=name,
            content=content,
            streams=streams,
            write_identity=write_identity,
            policy=policy,
            cancel=cancel,
            expected_base=expected_base,
            actor_id=actor_id,
        ).reference


def _original_asset(service, document, project_id):
    """沿实际持久依赖寻找唯一原件，不能把未保存父描述当可读资产。"""
    pending, seen, originals = [document], set(), {}
    while pending:
        current = pending.pop()
        key = current.reference.model_dump_json()
        if key in seen:
            continue
        seen.add(key)
        cloud = current.content.point_cloud
        if not cloud.provenance.source_retained:
            raise InvalidRequestError("点云资产未保留全部原始来源")
        if cloud.source.kind != "derived":
            originals[current.reference.sha256] = current
        else:
            pending.extend(
                service.read(r, project_id=project_id) for r in cloud.parent_assets
            )
    if len(originals) != 1:
        raise InvalidRequestError("无法定位唯一完整原始点云资产")
    return next(iter(originals.values()))


def read_asset(runtime, reference, *, service, project_id, policy, cancel):
    """恢复独立数组，新运行不借用历史 mmap 或历史运行身份。"""
    policy = replace(
        policy,
        chunk_bytes=min(
            policy.chunk_bytes,
            runtime.policy.chunk_bytes,
            runtime.policy.max_working_bytes,
        ),
    )
    with runtime.producing():
        document = service.read(reference, project_id=project_id)
        if reference.kind != "point-cloud":
            raise InvalidRequestError("读取资产必须选择 point-cloud")
        cloud = document.content.point_cloud
        if sum(b.content_length for b in cloud.blobs) > policy.max_asset_bytes:
            raise InvalidRequestError("点云资产超过显式容量")
        if isinstance(cloud, RasterCloudAsset):
            return restore_raster_asset(runtime, document, service, project_id, cancel)
        if isinstance(cloud, ProfileCloudAsset):
            return restore_profile_asset(runtime, document, service, project_id, cancel)
        if isinstance(cloud, OriginalCloudAsset):
            blob = cloud.blobs[0]
            key = cloud_blob_key(service, reference, blob)
            file = {
                "transport_kind": "storage",
                "storage_ref": "object-store",
                "object_key": key,
                "file_name": cloud.original_file_name,
                "media_type": "application/octet-stream",
                "content_length": blob.content_length,
                "checksum_algorithm": "sha256",
                "checksum": blob.sha256,
                "immutable_version": f"sha256:{blob.sha256}",
            }
            result = read_cloud_file(
                object_store=service.storage,
                project_id=project_id,
                file=file,
                options=cloud.file_options(),
                policy=runtime.policy,
                budget=runtime.budget,
                scope=runtime.storage_scope,
                cancel=cancel,
            )
            if (
                result.point_count != cloud.point_count
                or result.fields != cloud.fields
                or result.source_metadata != cloud.source_metadata
            ):
                raise InvalidRequestError("原件资产解码与已核验内容不一致")
            return runtime.register_asset(
                owner=result.arrays, document=document, indices=None, cancel=cancel
            )
        return _read_blocks(runtime, document, service, policy, cancel)


def _read_blocks(runtime, document, service, policy, cancel):
    """分块装入预算已预留的独立数组，失败时释放所有尚未发布资源。"""
    cloud = document.content.point_cloud
    array_bytes = sum(f.byte_length for f in cloud.fields)
    index_bytes = next(
        (b.content_length for b in cloud.blobs if b.role == "indices"), 0
    )
    lineage_bytes = next(
        (b.content_length for b in cloud.blobs if b.role == "lineage"), 0
    )
    profile_bytes = next(
        (b.content_length for b in cloud.blobs if b.role == "profile-rows"), 0
    )
    if (
        array_bytes + index_bytes + lineage_bytes + profile_bytes
        > runtime.policy.max_decoded_bytes
    ):
        raise InvalidRequestError("资产数组超过解码预算")
    reservation = runtime.budget.reserve(
        array_bytes + index_bytes + lineage_bytes + profile_bytes
    )
    arrays, owners = {}, []
    index_reservation = None
    lineage_reservation = None
    lineage_arrays = {}
    profile_arrays = {}
    profile_reservation = None
    try:
        for field in cloud.fields:
            cancel()
            arrays[field.name] = np.empty(
                (field.count, field.components),
                dtype=np.dtype(field.dtype).newbyteorder("<"),
            )
        if cloud.indices:
            arrays["__indices"] = np.empty(
                (cloud.indices.count, 1),
                dtype=np.dtype(cloud.indices.dtype).newbyteorder("<"),
            )
        if cloud.lineage:
            shapes = (
                voxel_lineage_shapes(
                    cloud.point_count,
                    cloud.lineage.member_count,
                    cloud.lineage.source_dtype,
                )
                if isinstance(cloud.lineage, AssetVoxelLineage)
                else profile_lineage_shapes(
                    cloud.point_count,
                    cloud.lineage.cell_count,
                    cloud.lineage.source_count,
                )
                if isinstance(cloud.lineage, AssetProfileLineage)
                else lineage_shapes(cloud.point_count, cloud.lineage.face_count)
            )
            for name, (shape, dtype) in shapes.items():
                cancel()
                lineage_arrays[name] = np.empty(shape, dtype=dtype)
        if profile_bytes:
            origin, _ = cloud.original_observation()
            for name, dtype, shape in origin.profiles.row_layout():
                cancel()
                profile_arrays[name] = np.empty(
                    shape, dtype=np.dtype(dtype).newbyteorder("<")
                )
        for blob in cloud.blobs:
            with service.storage.open_read_snapshot(
                cloud_blob_key(service, document.reference, blob)
            ) as snapshot:
                checked = CheckedBlobStream(snapshot.stream, blob, cancel)
                if blob.role == "data":
                    cursor = 0
                    for field in cloud.fields:
                        padding = (
                            checked.read(field.offset_bytes - cursor)
                            if field.offset_bytes > cursor
                            else b""
                        )
                        if len(padding) != field.offset_bytes - cursor or any(padding):
                            raise InvalidRequestError("资产对齐字节无效")
                        _fill(checked, arrays[field.name], policy.chunk_bytes, cancel)
                        if field.name in ("validity", "sample_origin"):
                            for start in range(
                                0, cloud.point_count, runtime.policy.chunk_rows
                            ):
                                cancel()
                                if np.any(
                                    arrays[field.name][
                                        start : start + runtime.policy.chunk_rows
                                    ]
                                    > (1 if field.name == "validity" else 2)
                                ):
                                    raise InvalidRequestError(
                                        "资产有效性或来源编码无效"
                                    )
                        cursor = field.offset_bytes + field.byte_length
                elif blob.role == "indices":
                    _fill(checked, arrays["__indices"], policy.chunk_bytes, cancel)
                    for start in range(0, cloud.point_count, runtime.policy.chunk_rows):
                        cancel()
                        if np.any(
                            arrays["__indices"][
                                start : start + runtime.policy.chunk_rows
                            ]
                            >= cloud.indices.source_point_count
                        ):
                            raise InvalidRequestError("资产源行号越界")
                elif blob.role == "lineage":
                    for value in lineage_arrays.values():
                        _fill(checked, value, policy.chunk_bytes, cancel)
                elif blob.role == "profile-rows":
                    for value in profile_arrays.values():
                        _fill(checked, value, policy.chunk_bytes, cancel)
                elif blob.role in {"height-map", "sampling", "edge"}:
                    # 附属证据由读取方按需恢复；此处仍完整校验，不能漏掉坏数据块。
                    checked = CheckedBlobStream(snapshot.stream, blob, cancel, cloud)
                    while checked.read(policy.chunk_bytes):
                        pass
                else:
                    raise InvalidRequestError("数组资产含非法数据块")
                value = None
                if checked.read(1):
                    raise InvalidRequestError("资产数据块含多余字节")
        # 将一次联合准入拆成两个所有权，拆分期间不释放实际数组计费。
        index = arrays.pop("__indices", None)
        owner = OwnedCloudArrays(arrays, reservation)
        arrays.clear()
        owners.append(owner)
        runtime.storage_scope.register(
            ("asset", uuid4().hex), owner, lambda v: v.close()
        )
        indices = None
        if index is not None:
            index_reservation = reservation.split(index_bytes)
            indices = OwnedCloudArrays({"indices": index}, index_reservation)
            index = None
            owners.append(indices)
            runtime.storage_scope.register(
                ("asset-indices", uuid4().hex), indices, lambda v: v.close()
            )
        lineage = None
        if cloud.lineage is not None:
            lineage_reservation = reservation.split(lineage_bytes)
            lineage = OwnedCloudArrays(lineage_arrays, lineage_reservation)
            lineage_arrays.clear()
            owners.append(lineage)
            runtime.storage_scope.register(
                ("asset-lineage", uuid4().hex), lineage, lambda v: v.close()
            )
        profile_rows = None
        if profile_bytes:
            profile_reservation = reservation.split(profile_bytes)
            profile_rows = OwnedCloudArrays(profile_arrays, profile_reservation)
            profile_arrays.clear()
            owners.append(profile_rows)
            runtime.storage_scope.register(
                ("asset-profile-rows", uuid4().hex), profile_rows, lambda v: v.close()
            )
        return runtime.register_asset(
            owner=owner,
            document=document,
            indices=indices,
            lineage=lineage,
            profile_rows=profile_rows,
            cancel=cancel,
        )
    except BaseException as error:
        arrays.clear()
        lineage_arrays.clear()
        profile_arrays.clear()
        value = None
        index = None
        release_exception_frames(error)
        for owner in reversed(owners):
            owner.close()
        reservation.close()
        if index_reservation is not None:
            index_reservation.close()
        if profile_reservation is not None:
            profile_reservation.close()
        if lineage_reservation is not None:
            lineage_reservation.close()
        raise


def _fill(stream, array, chunk_bytes, cancel):
    """按原始字节写入独立数组，保留 NaN payload 与 uint64 精度。"""
    target = memoryview(array).cast("B") if array.nbytes else memoryview(b"")
    offset = 0
    try:
        while offset < len(target):
            cancel()
            data = stream.read(min(chunk_bytes, len(target) - offset))
            if not data:
                raise InvalidRequestError("点云资产数组截断")
            target[offset : offset + len(data)] = data
            offset += len(data)
    finally:
        target.release()
