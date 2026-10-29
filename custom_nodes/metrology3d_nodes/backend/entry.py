"""现有 NodePack context 的处理器注册，不启动独立服务。"""

from custom_nodes.metrology3d_nodes.backend import handlers
from custom_nodes.metrology3d_nodes.backend import geometry_handlers
from custom_nodes.metrology3d_nodes.backend import measurement_handlers
from custom_nodes.metrology3d_nodes.backend import boundary_handlers
from custom_nodes.metrology3d_nodes.backend import dimension_handlers

HANDLERS = {
    "read-cloud": handlers.read,
    "normalize-units": handlers.normalize,
    "filter-valid": handlers.filter_points,
    "cloud-preview": handlers.preview,
    "save-cloud": handlers.save,
    "export-cloud": handlers.export,
    "crop-roi": geometry_handlers.crop,
    "fit-plane": geometry_handlers.plane,
    "build-frame": geometry_handlers.frame,
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
