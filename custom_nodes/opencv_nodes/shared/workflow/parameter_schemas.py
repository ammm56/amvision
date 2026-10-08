"""新计量节点的参数 Schema 单一来源；总目录与分类目录共用。"""


def apply_parameter_schema(node: dict) -> None:
    """仅补充声明了类型化参数的节点，既有静态节点定义保持原样。"""
    identifier = node.get("node_type_id")
    if identifier not in {
        "custom.opencv.planar-calibrate",
        "custom.opencv.rigid-locate",
    }:
        return
    from backend.contracts.workflows.schema_helpers import inline_model_schema

    if identifier == "custom.opencv.planar-calibrate":
        from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.planar_calibrate import (
            Settings,
        )
    else:
        from custom_nodes.opencv_nodes.categories.matching.backend.nodes.rigid_locate import (
            Settings,
        )
    node["parameter_schema"] = inline_model_schema(Settings)
    if identifier == "custom.opencv.rigid-locate":
        node["parameter_schema"]["properties"]["template_resource"].update(
            {
                "title": "Template",
                "x-ui-widget": "measurement-resource",
                "x-resource-kind": "localization-template",
            }
        )
