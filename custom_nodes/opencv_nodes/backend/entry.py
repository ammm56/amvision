"""OpenCV 节点包统一 backend entrypoint。"""

from __future__ import annotations

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.opencv_nodes.categories.basic.backend.nodes import (
    NODE_HANDLERS as BASIC_NODE_HANDLERS,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes import (
    NODE_HANDLERS as CALIBRATION_NODE_HANDLERS,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes import (
    NODE_HANDLERS as DEFECT_NODE_HANDLERS,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes import (
    NODE_HANDLERS as GEOMETRY_NODE_HANDLERS,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes import (
    NODE_HANDLERS as MATCHING_NODE_HANDLERS,
)
from custom_nodes.opencv_nodes.categories.measurement.backend.nodes import (
    NODE_HANDLERS as MEASUREMENT_NODE_HANDLERS,
)
from custom_nodes.opencv_nodes.categories.render.backend.nodes import (
    NODE_HANDLERS as RENDER_NODE_HANDLERS,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes import (
    NODE_HANDLERS as SHAPE_NODE_HANDLERS,
)


_NODE_HANDLER_GROUPS = (
    BASIC_NODE_HANDLERS,
    CALIBRATION_NODE_HANDLERS,
    DEFECT_NODE_HANDLERS,
    GEOMETRY_NODE_HANDLERS,
    MATCHING_NODE_HANDLERS,
    MEASUREMENT_NODE_HANDLERS,
    RENDER_NODE_HANDLERS,
    SHAPE_NODE_HANDLERS,
)


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册 OpenCV 包内全部分类的节点处理函数。

    参数：
    - context：当前 OpenCV node pack 的注册上下文。
    """

    for handler_group in _NODE_HANDLER_GROUPS:
        handler_items = (
            handler_group.items()
            if isinstance(handler_group, dict)
            else handler_group
        )
        for node_type_id, handler in handler_items:
            context.register_python_callable(node_type_id, handler)
