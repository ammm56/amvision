"""拟面节点支持范围接线；复用裁剪、拟面和现有资源事务。"""

from backend.contracts.workflows.geometry3d import CropCloudParameters
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane


def fit_supported_plane(runtime, reference, parameters, *, cancel):
    """成功保留特征实测支持；异常/取消撤销本次新增引用和数组。"""
    if parameters.support.kind == "cloud":
        return fit_plane(runtime, reference, parameters.settings, cancel=cancel)
    source = parameters.support
    selection = CropCloudParameters(
        roi_id=source.roi.roi_id, rois=(source.roi, *source.bounds)
    )
    # restoring 已提供引用登记和 Scope 数组的原子清理，不再维护一套资源记录。
    with runtime.restoring():
        selected, _ = crop_roi(runtime, reference, selection, cancel=cancel)
        result = fit_plane(runtime, selected, parameters.settings, cancel=cancel)
        cancel()
        return result
