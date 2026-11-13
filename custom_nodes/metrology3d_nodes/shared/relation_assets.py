"""关系与同根完整派生链使用一个资产提交；恢复不拟合、不重写已有观测。"""

from uuid import uuid4

import numpy as np

from backend.contracts.workflows.geometry3d_observations import Features3d
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.relation3d_assets import (
    RelationAsset,
    RelationAssetItem,
    StoredCloudArray,
    StoredCloudState,
    StoredCloudStep,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CheckedBlobStream,
    cloud_blob_key,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.arc_assets import _same_recomputed
from custom_nodes.metrology3d_nodes.shared.dimension_runtime import select_features
from custom_nodes.metrology3d_nodes.shared.measurement_support import select_planes
from custom_nodes.metrology3d_nodes.shared.relation_result import relation_evidence


def _state(cloud):
    """只投影语义字段，不保留云 ID、run ID 或访问路径。"""
    return StoredCloudState.model_validate(
        cloud.model_dump(include=set(StoredCloudState.model_fields))
    )


def _groups(value):
    """沿现有 Features3d 契约接收单组或显式多组。"""
    if value is None:
        return ()
    return tuple(
        Features3d.model_validate(v)
        for v in (value if isinstance(value, (list, tuple)) else (value,))
    )


def _support(runtime, cloud, groups, parameters, selector):
    """读取既有模型的实际支持，不从显示或模型系数构造云。"""
    if selector.kind in {"coordinate", "source-point"}:
        return cloud
    if selector.kind == "plane":
        return select_planes(runtime, groups, parameters, [selector.feature_id])[
            0
        ].support
    return select_features(
        runtime,
        groups,
        parameters,
        [selector.feature_id],
        "circle" if selector.kind == "circle-center" else "line",
    )[0].support


def _collect(runtime, cloud, groups, evidence, cancel):
    """共同原云和真实父链唯一化；不按坐标相同或摘要相同猜测同源。"""
    root, _ = runtime.original_source(cloud)
    references, indices, steps = [root], {root.model_dump_json(): 0}, []

    def member(reference):
        cancel()
        if reference.state != "ready":
            return None
        if (
            runtime.original_source(reference)[0] != root
            or reference.observation_id != cloud.observation_id
        ):
            raise InvalidRequestError("关系支持不属于同一实际原云")
        chain = []
        while reference.model_dump_json() not in indices:
            if len(chain) + len(steps) >= 8192:
                raise InvalidRequestError("关系支持派生链超过描述上限")
            chain.append(reference)
            reference = runtime.parent_reference(reference)
            if reference is None:
                raise InvalidRequestError("关系支持缺少共同父链")
        parent = indices[reference.model_dump_json()]
        for reference in reversed(chain):
            with runtime.borrow_derivation(reference) as (actual_parent, arrays):
                if actual_parent != references[parent]:
                    raise InvalidRequestError("关系支持父链发生变化")
                kind = (
                    "generated"
                    if "lineage" in arrays
                    else "materialized"
                    if "owner" in arrays
                    else "ordered"
                    if reference.topology is not None
                    else "subset"
                )
                layouts = []
                for group in sorted(arrays):
                    for name, value in sorted(arrays[group].items()):
                        if value.ndim != 2 or value.dtype.byteorder == ">":
                            raise InvalidRequestError("关系支持不是规范 LE 数组")
                        layouts.append(
                            StoredCloudArray(
                                group=group,
                                name=name,
                                dtype=value.dtype.name,
                                rows=value.shape[0],
                                columns=value.shape[1],
                            )
                        )
                step = StoredCloudStep(
                    parent=parent,
                    kind=kind,
                    method=reference.provenance.method,
                    state=_state(reference),
                    arrays=tuple(layouts),
                )
            references.append(reference)
            steps.append(step)
            parent = len(steps)
            indices[reference.model_dump_json()] = parent
        return parent

    primary = member(cloud)
    items = []
    for item in evidence.items:
        if item.kind != "measure-relation":
            raise InvalidRequestError("关系资产不能混入其他测量类型")
        current = relation_evidence(
            runtime, cloud, groups, item.method.parameters, cancel=cancel
        )
        if (
            current.items != (item,)
            or current.observation_id != evidence.observation_id
        ):
            raise InvalidRequestError("关系保存证据与当前完整支持不一致")
        p = item.method.parameters
        members = tuple(
            member(_support(runtime, cloud, groups, p, selector))
            for selector in (p.relation.reference, p.relation.target)
        )
        items.append(RelationAssetItem(evidence=item, members=members))
    return (
        root,
        tuple(references),
        RelationAsset(primary=primary, steps=tuple(steps), items=tuple(items)),
    )


def _chunks(runtime, references, saved, chunk_bytes, cancel):
    """同一排列两次流式扫描用于摘要与提交；不创建全量 bytes 副本。"""
    for reference, step in zip(references[1:], saved.steps):
        cancel()
        with runtime.borrow_derivation(reference) as (_, groups):
            for layout in step.arrays:
                array = groups[layout.group][layout.name]
                view = memoryview(array).cast("B") if array.nbytes else memoryview(b"")
                try:
                    for offset in range(0, len(view), chunk_bytes):
                        cancel()
                        yield bytes(view[offset : offset + chunk_bytes])
                finally:
                    view.release()


def save_relation_asset(runtime, cloud, **kwargs):
    """完整关系走已有版本原子提交，写失败不会出现半个 A/B 资产。"""
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import (
        _save_cloud,
        _blob,
        _Chunks,
    )

    if kwargs["mode"] != "derived" or any(
        kwargs.get(key) is not None for key in ("height_map", "sampling", "edge")
    ):
        raise InvalidRequestError("关系保存使用派生模式，不混入其他附属输出")
    evidence = MeasurementEvidence3d.model_validate(kwargs["evidence"])
    groups = _groups(kwargs.get("features"))
    policy, cancel = kwargs["policy"], kwargs["cancel"]
    try:
        with runtime.producing():
            root, references, saved = _collect(runtime, cloud, groups, evidence, cancel)
            if saved.byte_length() > policy.max_asset_bytes:
                raise InvalidRequestError("关系支持超过资产预算")
            chunk_bytes = min(
                policy.chunk_bytes,
                runtime.policy.chunk_bytes,
                runtime.policy.max_working_bytes,
            )

            def factory():
                """在同一生产借用内重新创建流，不复用已耗尽生成器。"""
                return _chunks(runtime, references, saved, chunk_bytes, cancel)

            blob = _blob("relation", "relation.bin", factory())
            args = {
                key: value
                for key, value in kwargs.items()
                if key not in {"features", "evidence"}
            }
            return _save_cloud(
                runtime,
                root,
                **args,
                relation_attachment=(saved, blob, _Chunks(factory())),
            )
    except BaseException as error:
        release_exception_frames(error)
        raise


def _read_step(runtime, step, stream, chunk_bytes, cancel):
    """先联合准入再分组交接，所有数组都在现有 Scope 中拥有明确归属。"""
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import _fill

    size = sum(a.byte_length() for a in step.arrays)
    if size > runtime.policy.max_decoded_bytes:
        raise InvalidRequestError("关系派生支持超过解码预算")
    reservation = runtime.budget.reserve(size)
    groups = {}
    try:
        for layout in step.arrays:
            cancel()
            array = np.empty(
                (layout.rows, layout.columns),
                dtype=np.dtype(layout.dtype).newbyteorder("<"),
            )
            groups.setdefault(layout.group, {})[layout.name] = array
            _fill(stream, array, chunk_bytes, cancel)
        array = None
        owners = {}
        for group, arrays in groups.items():
            part = reservation.split(sum(a.nbytes for a in arrays.values()))
            owner = OwnedCloudArrays(arrays, part)
            try:
                runtime.storage_scope.register(
                    ("relation-array", uuid4().hex), owner, lambda value: value.close()
                )
            except BaseException:
                owner.close()
                raise
            owners[group] = owner
        return owners
    finally:
        groups.clear()
        reservation.close()


def _bind_model(side, support):
    """创建新特征值对象；历史拟合来源保持，实际支持来自已恢复父链。"""
    snapshot = side.plane or side.feature
    if snapshot is None:
        return None
    data = snapshot.model_dump(mode="json")
    if side.plane:
        data.update(kind="plane", feature_id=side.plane.method.parameters.feature_id)
    data["quality"]["metrics"]["observation_id"] = support.observation_id
    boundary = data["method"].get("boundary")
    if boundary:
        for value in (boundary, *boundary["segments"], *boundary["groups"]):
            value["quality"]["metrics"]["observation_id"] = support.observation_id
    data["support"] = support.model_dump(mode="json")
    return data


def _comparable(item):
    """只排除新观测和新资产来源摘要；方法、原始行号、支持、模型与数值均比较。"""
    payload = item.model_dump(mode="json")
    for side in payload["support"]:
        side.pop("content_sha256")

    def visit(value):
        if isinstance(value, dict):
            if "metrics" in value and isinstance(value["metrics"], dict):
                value["metrics"].pop("observation_id", None)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return payload


def restore_relation_asset(runtime, root, *, document, service, policy, cancel):
    """新原云逐步恢复同源分支；不变更旧引用，不拟合，失败由调用方事务撤销。"""
    saved = document.content.point_cloud.relation
    blob = next(b for b in document.content.point_cloud.blobs if b.role == "relation")
    references = [root]
    chunk_bytes = min(
        policy.chunk_bytes, runtime.policy.chunk_bytes, runtime.policy.max_working_bytes
    )
    with service.storage.open_read_snapshot(
        cloud_blob_key(service, document.reference, blob)
    ) as snapshot:
        stream = CheckedBlobStream(
            snapshot.stream, blob, cancel, document.content.point_cloud
        )
        for step in saved.steps:
            owners = _read_step(runtime, step, stream, chunk_bytes, cancel)
            parent = references[step.parent]
            args = dict(parent=parent, method=step.method, cancel=cancel)
            if step.kind in {"subset", "ordered"}:
                function = (
                    runtime.register_ordered
                    if step.kind == "ordered"
                    else runtime.register_subset
                )
                if step.kind == "ordered":
                    args["topology"] = step.state.topology
                reference = function(**args, indices=owners["indices"])
            elif step.kind == "generated":
                reference = runtime.register_generated(
                    **args,
                    owner=owners["owner"],
                    lineage=owners["lineage"],
                    fields=step.state.fields,
                    point_count=step.state.point_count,
                    topology=step.state.topology,
                )
            else:
                reference = runtime.register_derived(
                    **args,
                    owner=owners["owner"],
                    fields=step.state.fields,
                    spatial=step.state.spatial,
                )
            if _state(reference) != step.state:
                raise InvalidRequestError("恢复支持与已存语义或精度不一致")
            references.append(reference)
        if stream.read(1):
            raise InvalidRequestError("关系支持包含未声明尾字节")
    primary = references[saved.primary]
    models = {}
    for item in saved.items:
        for side, member in zip(item.evidence.support, item.members):
            support = (
                references[member]
                if member is not None
                else primary.unavailable((side.plane or side.feature).reason)
            )
            model = _bind_model(side, support)
            if model is not None:
                identity = model["feature_id"]
                if identity in models and models[identity] != model:
                    raise InvalidRequestError("关系保存存在同名不同模型")
                models[identity] = model
    features = Features3d(
        run_id=primary.run_id,
        observation_id=primary.observation_id,
        frame_id=primary.spatial.frame_id,
        length_unit=primary.spatial.length_unit,
        items=tuple(models.values()),
    )
    items = []
    for stored in saved.items:
        cancel()
        current = relation_evidence(
            runtime,
            primary,
            (features,),
            stored.evidence.method.parameters,
            cancel=cancel,
        ).items[0]
        if not _same_recomputed(_comparable(stored.evidence), _comparable(current)):
            raise InvalidRequestError("关系恢复与保存的支持、量值或失败证据不一致")
        items.append(current)
    return (
        primary,
        features,
        MeasurementEvidence3d(
            observation_id=primary.observation_id,
            frame_id=primary.spatial.frame_id,
            length_unit=primary.spatial.length_unit,
            items=tuple(items),
        ),
    )
