"""现有 NodePack context 的处理器注册，不启动独立服务。"""

from custom_nodes.metrology3d_nodes.backend import handlers
from custom_nodes.metrology3d_nodes.backend import geometry_handlers
from custom_nodes.metrology3d_nodes.backend import measurement_handlers
from custom_nodes.metrology3d_nodes.backend import boundary_handlers
from custom_nodes.metrology3d_nodes.backend import dimension_handlers
from custom_nodes.metrology3d_nodes.backend import pose_handlers
from custom_nodes.metrology3d_nodes.backend.raster_handler import raster_to_cloud
from custom_nodes.metrology3d_nodes.backend.profile_handler import profiles_to_cloud

HANDLERS = {
    "raster-to-cloud": raster_to_cloud,
    "profiles-to-cloud": profiles_to_cloud,
    "read-cloud": handlers.read,
    "normalize-units": handlers.normalize,
    "filter-valid": handlers.filter_points,
    "denoise-cloud": handlers.denoise,
    "resample-cloud": handlers.resample,
    "estimate-normals": handlers.normals,
    "cloud-preview": handlers.preview,
    "save-cloud": handlers.save,
    "export-cloud": handlers.export,
    "crop-roi": geometry_handlers.crop,
    "fit-plane": geometry_handlers.plane,
    "build-frame": geometry_handlers.frame,
    "invert-pose": pose_handlers.invert,
    "compose-pose": pose_handlers.compose,
    "register-cloud": pose_handlers.register,
    "transform-cloud": geometry_handlers.transform,
    "height-query": measurement_handlers.height,
    "measure-step": measurement_handlers.step,
    "extract-boundary": boundary_handlers.extract,
    "fit-line": boundary_handlers.line,
    "fit-circle": boundary_handlers.circle,
    "measure-extents": dimension_handlers.extents,
    "measure-edge-pair": dimension_handlers.edge_pair,
    "measure-hole": dimension_handlers.hole,
}


def register(context):
    """沿正式 NodePack context 注册，不创建另一套执行器。"""
    for key, handler in HANDLERS.items():
        context.register_python_callable("custom.metrology3d." + key, handler)
