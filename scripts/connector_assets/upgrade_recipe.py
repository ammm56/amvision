"""审核并更新旧合成连接器示例配方；保留业务公差、资源引用和用户编排。"""

from copy import deepcopy

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate


def upgrade_example_recipe(
    existing: WorkflowGraphTemplate, canonical: WorkflowGraphTemplate,
) -> WorkflowGraphTemplate:
    """仅更新已核对的示例采样和显示配置；产品或标定不同则拒绝套用。"""
    result = existing.model_dump(mode="json")
    nodes = {node["node_id"]: node for node in result["nodes"]}
    reference = {node.node_id: node for node in canonical.nodes}
    for key in ("locate", "pins", "measure", "limits", "display"):
        if key not in nodes or nodes[key]["node_type_id"] != reference[key].node_type_id:
            raise ValueError(f"节点 {key} 与参考配方不匹配，必须人工审核")
    for key, field in (("locate", "template_resource"), ("measure", "calibration_resource")):
        if nodes[key]["parameters"][field]["sha256"] != reference[key].parameters[field]["sha256"]:
            raise ValueError(f"{field} 内容不同，不能套用合成配方")
    for key, field in (("limits", "rules"), ("measure", "items")):
        if nodes[key]["parameters"][field] != reference[key].parameters[field]:
            raise ValueError(f"{field} 已调整，必须审核测量定义和公差")
    parameters = nodes["pins"]["parameters"]
    layout = parameters["layout"]
    expected = reference["pins"].parameters["layout"]
    for key in ("reference_id", "reference_sha256", "pins"):
        if layout[key] != expected[key]:
            raise ValueError(f"PIN 布局 {key} 不同，不能套用参考配方")
    # 搜索范围是产品配方，不随采样阈值升级而覆盖用户设置。
    def band_geometry(bands):
        """去掉本次允许升级的采样类型后比较候选带。"""
        return [{k: v for k, v in band.items() if k != "sampling_type"} for band in bands]

    if band_geometry(layout["candidate_bands"]) != band_geometry(expected["candidate_bands"]):
        raise ValueError("候选带搜索范围不同，必须人工审核")
    # 配套更新线性光强采样阈值和阵列外搜索类型，保留诊断针脚及调试显示开关。
    parameters["image_encoding"] = "srgb"
    layout["types"] = deepcopy(expected["types"])
    layout["candidate_bands"] = deepcopy(expected["candidate_bands"])
    for field in nodes["display"]["parameters"]["fields"]:
        if field.get("path") == "passed_count":
            field["path"] = "required_ok_count"
        if field.get("path") == "state":
            field.setdefault("states", {}).setdefault("invalid", "#D98B00")
    return WorkflowGraphTemplate.model_validate(result)
