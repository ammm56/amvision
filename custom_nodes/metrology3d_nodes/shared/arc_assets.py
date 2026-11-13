"""圆弧量值随同支持资产保存；重读复核量值而不重复拟圆。"""

from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.dimension3d_evidence import close
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.boundary_assets import restore_circle
from custom_nodes.metrology3d_nodes.shared.measure_arc import measure_arc


def _same_recomputed(left, right):
    """身份、拓扑严格相同，浮点复算沿既有证据舍入界，不修改质量门槛。"""
    if isinstance(left, float) and isinstance(right, float):
        return close(left, right)
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_recomputed(left[k], right[k]) for k in left
        )
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(
            _same_recomputed(a, b) for a, b in zip(left, right)
        )
    return left == right


def restore_arc_evidence(runtime, cloud, circle, items, *, cancel):
    """复用原测量方法核对完整支持，并输出绑定当前观测的有限证据。"""
    if not items:
        return None
    group = restore_circle(cloud, circle)
    completed, restored = set(), {}
    for item in items:
        cancel()
        key = item.method.parameters_sha256
        if key not in completed:
            result = measure_arc(
                runtime, [group], item.method.parameters, cancel=cancel
            )
            restored.update({i.item_id: i for i in result.items})
            completed.add(key)
        current = restored[item.item_id]
        # 持久源描述和新运行身份不同；模型、方法、量值和真实端点必须完全一致。
        fields = {
            "kind",
            "item_id",
            "component",
            "valid",
            "value",
            "reason",
            "geometry",
            "method",
            "diagnostic",
            "sample_origin",
        }
        if not _same_recomputed(
            item.model_dump(include=fields), current.model_dump(include=fields)
        ):
            raise InvalidRequestError("保存的圆弧证据与实际支持重算不一致")
        omit = {"metrics": {"observation_id"}}
        if not _same_recomputed(
            item.quality.model_dump(exclude=omit),
            current.quality.model_dump(exclude=omit),
        ):
            raise InvalidRequestError("保存的圆弧质量与实际支持重算不一致")
    return MeasurementEvidence3d(
        observation_id=cloud.observation_id,
        frame_id=cloud.spatial.frame_id,
        length_unit=cloud.spatial.length_unit,
        items=tuple(restored[i.item_id] for i in items),
    )


def freeze_arc_evidence(runtime, cloud, circle, value, *, cancel):
    """写入前校验当前观测和完整证据，不接受别的运行或别的圆。"""
    evidence = MeasurementEvidence3d.model_validate(value)
    if (
        circle is None
        or circle.kind != "circle"
        or evidence.observation_id != cloud.observation_id
    ):
        raise InvalidRequestError("保存圆弧证据需要当前同一圆及支持")
    if any(
        i.kind != "measure-arc" or len(i.support) != 1 or i.support[0].feature != circle
        for i in evidence.items
    ):
        raise InvalidRequestError("保存圆弧证据只接受同一圆的完整量值")
    restored = restore_arc_evidence(
        runtime, cloud, circle, evidence.items, cancel=cancel
    )
    if restored is None or restored != evidence:
        raise InvalidRequestError("保存圆弧证据与当前支持或质量不一致")
    return evidence.items
