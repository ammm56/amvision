"""连接器包只注册行业处理器，不建立独立执行服务。"""

from custom_nodes.connector_nodes.categories.array.backend.nodes import pin_array_locate
from custom_nodes.connector_nodes.categories.measurement.backend.nodes import measure


def register(context) -> None:
    """使用既有节点包生命周期、禁用与超时控制注册两个行业节点。"""
    for module in (pin_array_locate, measure):
        context.register_python_callable(module.NODE_TYPE_ID, module.handle_node)
