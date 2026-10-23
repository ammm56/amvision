"""现有 NodePack context 的处理器注册，不启动独立服务。"""

from custom_nodes._metrology3d_nodes.backend import handlers
from custom_nodes._metrology3d_nodes.backend import geometry_handlers
from custom_nodes._metrology3d_nodes.backend import measurement_handlers
from custom_nodes._metrology3d_nodes.backend import boundary_handlers

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
}


def register(context):
    """生产 loader 仍不发现内部目录；测试沿同一公开注册方法接入。"""
    for key, handler in HANDLERS.items():
        context.register_python_callable("custom.metrology3d." + key, handler)
