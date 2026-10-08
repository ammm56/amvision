"""使用已准备资源组织现场步骤应用；仅构建文档，不直接修改服务或现场数据。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from backend.contracts.workflows.workflow_app_mode import (
    WorkflowAppModeConfig,
    WorkflowAppModeDisplay,
)
from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
)


def _node(identifier, kind, parameters, x, y):
    """创建有明确画布位置的节点。"""
    return dict(
        node_id=identifier,
        node_type_id=kind,
        parameters=parameters,
        ui_state={"x": x, "y": y, "width": 340},
    )


def _edge(a, port, b, target):
    """端口关联保持显式，节点组不参与执行。"""
    return dict(
        edge_id=f"{a}-{port}-{b}-{target}",
        source_node_id=a,
        source_port=port,
        target_node_id=b,
        target_port=target,
    )


def _group(identifier, name, members, x, y, width, height):
    """步骤组只组织编辑画布。"""
    return dict(
        group_id=identifier,
        name=name,
        member_node_ids=members,
        rect=dict(x=x, y=y, width=width, height=height),
        color="#00C896",
    )


def _note(identifier, title, content, x=0, y=-420, width=880, height=300):
    """在配方中保留工况与操作边界。"""
    return dict(
        note_id=identifier,
        title=title,
        content=content,
        rect=dict(x=x, y=y, width=width, height=height),
        tone="info",
    )


def _result_columns(fields):
    """显式设置通用列显示语义；不修改原始测量值或公差判定。"""
    formats = {"unit": "unit", "passed": "result", "valid": "validity", "reason": "reason"}
    return [dict(key=key, label=label, format=formats.get(key, "value")) for key, label in fields]


def _application(graph, project_id, displays):
    """由模板公开端口生成应用绑定及完整的应用模式配置。"""
    return FlowApplication(
        application_id=graph.template_id,
        display_name=graph.display_name,
        description=graph.description,
        template_ref=dict(
            template_id=graph.template_id,
            template_version=graph.template_version,
            source_kind="embedded",
        ),
        bindings=[
            dict(
                binding_id=p.input_id,
                direction="input",
                template_port_id=p.input_id,
                binding_kind="workflow-execute-input",
                config={"payload_type_id": p.payload_type_id},
            )
            for p in graph.template_inputs
        ]
        + [
            dict(
                binding_id="output_" + p.output_id,
                direction="output",
                template_port_id=p.output_id,
                binding_kind="workflow-execute-output",
                config={"payload_type_id": p.payload_type_id},
            )
            for p in graph.template_outputs
        ],
        metadata={
            "project_id": project_id,
            "engineering_only": True,
            "app_mode": WorkflowAppModeConfig(
                title=graph.display_name, displays=displays
            ).model_dump(mode="json"),
        },
    )


def inspection_application(
    example_dir: Path,
    *,
    family: str,
    project_id: str,
    resources: dict,
    empty_pin_id: str | None = None,
):
    """复用已验证的尺寸配方，替换导入资源引用并增加步骤分组和逐项结果预览。"""
    if family not in {"single10_front", "dual08_top"}:
        raise ValueError(f"未配置的开发物料：{family}")
    payload = json.loads(
        (example_dir / f"{family}.template.json").read_text(encoding="utf-8")
    )
    single = family == "single10_front"
    name = "连接器 · 单排10针检测" if single else "连接器 · 双排16针检测"
    payload.update(
        template_id="workflow-app-connector-" + ("single10" if single else "dual16"),
        display_name=name,
        description="合成开发物料；定位、PIN 检查、毫米尺寸、公差判定和结果显示。",
    )
    nodes = {n["node_id"]: n for n in payload["nodes"]}
    if empty_pin_id:
        # 设计空位是独立产品配方，存在性检查仍保留；不对不存在的针计算尺寸。
        pin = next(
            (
                p
                for p in nodes["pins"]["parameters"]["layout"]["pins"]
                if p["pin_id"] == empty_pin_id
            ),
            None,
        )
        if pin is None:
            raise ValueError(f"配方中不存在设计空位编号：{empty_pin_id}")
        pin["expected_present"] = False
        items = nodes["measure"]["parameters"]["items"]
        removed = {
            item["item_id"]
            for item in items
            if empty_pin_id in (item.get("pin_a"), item.get("pin_b"))
        }
        nodes["measure"]["parameters"]["items"] = [
            item for item in items if item["item_id"] not in removed
        ]
        nodes["limits"]["parameters"]["rules"] = [
            rule
            for rule in nodes["limits"]["parameters"]["rules"]
            if rule["item_id"] not in removed
        ]
        payload["template_id"] += "-empty"
        payload["display_name"] += " · 设计空位"
    nodes["locate"]["parameters"]["template_resource"] = resources[
        "localization-template"
    ]
    nodes["measure"]["parameters"]["calibration_resource"] = resources[
        "planar-calibration"
    ]
    nodes["pins"]["parameters"]["layout"]["reference_sha256"] = resources[
        "localization-template"
    ]["sha256"]
    nodes["pins"]["parameters"]["layout"]["diagnostic_pin_id"] = "R1P01"
    nodes["pins"]["parameters"]["debug_image_panel_enabled"] = True
    nodes["image"]["parameters"]["title"] = "检测结果"
    # 图片与表格使用同次原图，按所选项叠加几何；不再预先把所有尺寸画到像素中。
    payload["nodes"] = [node for node in payload["nodes"] if node["node_id"] != "draw"]
    payload["edges"] = [edge for edge in payload["edges"] if "draw" not in (edge["source_node_id"],edge["target_node_id"])]
    payload["edges"].append(_edge("input", "image", "image", "image"))
    nodes["display"]["parameters"]["title"] = "本次检测"
    for field, label in zip(
        nodes["display"]["parameters"]["fields"], ("结果", "检查项", "合格项")
    ):
        field["label"] = label
    positions = {
        "input": (0, 0),
        "locate": (450, 0),
        "pins": (950, 0),
        "measure": (1450, 0),
        "merge": (1950, 0),
        "limits": (2400, 0),
        "display": (2850, 0),
        "image": (3350, 0),
    }
    for identifier, (x, y) in positions.items():
        nodes[identifier]["ui_state"] = {"x": x, "y": y, "width": 340}
    payload["nodes"].extend(
        [
            _node("values", "core.value.numeric-table-to-value", {}, 1950, 760),
            _node(
                "measurements",
                "core.io.value-preview",
                {"title": "尺寸与有效性", "path": "items", "display_mode":"table", "columns":_result_columns((("item_id","检查项"),("value","实测值"),("unit","单位"),("valid","有效"),("reason","原因")))},
                2400,
                760,
            ),
            _node(
                "decisions",
                "core.io.value-preview",
                {"title": "逐项判定", "path": "items", "display_mode":"table", "columns":_result_columns((("item_id","检查项"),("value","实测值"),("unit","单位"),("lower","下限"),("upper","上限"),("passed","结果"),("reason","原因")))},
                2850,
                760,
            ),
        ]
    )
    payload["edges"].extend(
        [
            _edge("measure", "measurements", "values", "table"),
            _edge("values", "value", "measurements", "value"),
            _edge("limits", "summary", "decisions", "value"),
            _edge("measure", "result_geometry", "decisions", "geometry"),
            _edge("decisions", "body", "image", "results"),
        ]
    )
    payload["template_outputs"].append(
        dict(
            output_id="measurements",
            display_name="Measurements",
            payload_type_id="value.v1",
            source_node_id="values",
            source_port="value",
        )
    )
    payload["groups"] = [
        _group("input-step", "01 · 原图输入", ["input"], -30, -65, 420, 720),
        _group("locate-step", "02 · 工件定位", ["locate"], 420, -65, 470, 720),
        _group("pins-step", "03 · PIN 检查", ["pins"], 920, -65, 470, 720),
        _group("measure-step", "04 · 尺寸测量", ["measure"], 1420, -65, 470, 720),
        _group(
            "judge-step", "05 · 公差判定", ["merge", "limits"], 1920, -65, 870, 720
        ),
        _group(
            "display-step",
            "06 · 结果显示",
            ["display", "image"],
            2820,
            -65,
            970,
            720,
        ),
        _group(
            "detail-step",
            "调试 · 尺寸与逐项判定",
            ["values", "measurements", "decisions"],
            1920,
            695,
            1340,
            580,
        ),
    ]
    payload["notes"] = [
        _note(
            "operation",
            "使用步骤",
            "1. 输入本产品族的原始 PNG。\n2. 定位后检查固定 PIN 编号及候选带。\n3. 按已保存的标定版本测量，再按独立公差判定。\n4. 应用模式查看本次图片和 OK/NG；逐项详情用于调试。\n\n输入缺失直接报错，不回退到参考图。",
        ),
        _note(
            "scope",
            "配方与合成资源",
            f"物料：{family}；节距 2.54 mm，PIN 宽度 0.64 mm。\n检测时复用固定模板和合成正交比例；不逐件重新标定。\n棋盘标定应用使用另一种针孔相机，不能直接替换此标定。\n示例公差用于开发；异常值为 null，不使用名义值补齐。\n无隐式图片、JSONL 或生产计数写入。",
            x=1000,
        ),
    ]
    if empty_pin_id:
        payload["notes"][1]["content"] += (
            f"\n设计空位：{empty_pin_id} 必须为空，误插判 NG；针位编号保持不变。"
            "\n该配方使用 designed_empty / empty_occupied 图片，不能和满针产品配方混用。"
        )
    graph = WorkflowGraphTemplate.model_validate(payload)
    return graph, _application(
        graph,
        project_id,
        (
            WorkflowAppModeDisplay(
                node_id="image", output_port="body", title="检测结果", size="large"
            ),
        ),
    )


def calibration_applications(assets: Path, *, project_id: str):
    """两套准备工作流：棋盘相机标定与独立点验证的平面标定，不接入逐件检测热路径。"""
    paths = sorted((assets / "calibration").glob("*.png"))
    if len(paths) != 12:
        raise ValueError("需要已准备的 12 张棋盘图")
    image = cv2.imdecode(np.fromfile(paths[0], np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None or image.shape != (800, 1280):
        raise ValueError("参考棋盘必须是可解码的 1280×800 图像")
    found, corners = cv2.findChessboardCornersSB(image, (9, 6))
    if not found:
        raise ValueError("参考棋盘角点检测失败")
    worlds = np.mgrid[0:9, 0:6].T.reshape(-1, 2).astype(float) * 2.0
    points = [
        dict(image=p.tolist(), world=w.tolist())
        for p, w in zip(corners.reshape(-1, 2), worlds)
    ]
    holdout = {12, 22, 31, 41}
    plane_settings = dict(
        image_width=1280,
        image_height=800,
        plane_id="synthetic-checkerboard",
        model="homography",
        unit="millimeter",
        max_validation_error=0.02,
        control_points=[p for i, p in enumerate(points) if i not in holdout],
        validation_points=[p for i, p in enumerate(points) if i in holdout],
    )
    camera_nodes = [
        _node(
            "boards",
            "core.io.image-list-local",
            {"paths": [str(p.resolve()) for p in paths]},
            0,
            0,
        ),
        _node(
            "calibrate",
            "custom.opencv.camera-calibrate",
            {
                "columns": 9,
                "rows": 6,
                "square_size": 2.0,
                "object_point_unit": "millimeter",
                "min_views": 12,
                "use_sb": True,
            },
            480,
            0,
        ),
        _node(
            "result", "core.io.value-preview", {"title": "相机内参与逐视图误差"}, 960, 0
        ),
    ]
    plane_nodes = [
        _node(
            "board",
            "core.io.image-load-local",
            {"local_path": str(paths[0].resolve())},
            0,
            0,
        ),
        _node("image", "core.io.image-preview", {"title": "平面标定参考棋盘"}, 480, 0),
        _node("calibrate", "custom.opencv.planar-calibrate", plane_settings, 960, 0),
        _node("result", "core.io.value-preview", {"title": "平面标定验证"}, 1440, 0),
    ]
    specs = [
        (
            "camera",
            "连接器 · 相机标定准备",
            camera_nodes,
            [
                _edge("boards", "images", "calibrate", "images"),
                _edge("calibrate", "calibration", "result", "value"),
            ],
            "calibration",
            "value.v1",
        ),
        (
            "plane",
            "连接器 · 平面标定准备",
            plane_nodes,
            [
                _edge("board", "image", "image", "image"),
                _edge("calibrate", "summary", "result", "value"),
            ],
            "calibration",
            "planar-calibration.v1",
        ),
    ]
    result = []
    for key, title, nodes, edges, port, payload_type in specs:
        graph = WorkflowGraphTemplate(
            template_id=f"workflow-app-connector-{key}-setup",
            template_version="0.1.8",
            display_name=title,
            description="合成棋盘开发资源；配置步骤应用，不在逐件检测时反复求解。",
            nodes=nodes,
            edges=edges,
            template_outputs=[
                dict(
                    output_id="calibration",
                    display_name="Calibration",
                    payload_type_id=payload_type,
                    source_node_id="calibrate",
                    source_port=port,
                ),
                dict(
                    output_id="preview",
                    display_name="Preview",
                    payload_type_id="response-body.v1",
                    source_node_id="result",
                    source_port="body",
                ),
            ],
            notes=[
                _note(
                    "instructions",
                    "标定准备与适用边界",
                    "9×6 内角点，格长 2 mm，12 张针孔相机合成棋盘。\n相机标定读取全部图片；平面标定使用第 1 张图的 50 个拟合点和 4 个独立验证点。\n平面误差上限 0.02 mm，超限时失败。\n此针孔棋盘与连接器正交渲染不属于同一成像工况，不可交叉套用标定。\n实物换相机、镜头、测量平面或图像空间后须重新标定和验证。",
                )
            ],
            metadata={"engineering_only": True, "synthetic_calibration": True},
        )
        displays = [
            WorkflowAppModeDisplay(
                node_id="result", output_port="body", title="标定结果", size="large"
            )
        ]
        if key == "plane":
            displays.insert(
                0,
                WorkflowAppModeDisplay(
                    node_id="image", output_port="body", title="标定图", size="large"
                ),
            )
        result.append((graph, _application(graph, project_id, tuple(displays))))
    return result


def export_applications(assets: Path, examples: Path, installation: Path, output: Path):
    """导出可由前端导入的完整文档；资源引用取自明确的安装清单，不自动创建资源。"""
    installed = json.loads(installation.read_text(encoding="utf-8"))
    project_id = installed["project_id"]
    applications = []
    for family, references in installed["resources"].items():
        for empty_pin_id in (None, "R1P05"):
            applications.append(
                inspection_application(
                    examples / family,
                    family=family,
                    project_id=project_id,
                    resources=references,
                    empty_pin_id=empty_pin_id,
                )
            )
    applications.extend(calibration_applications(assets, project_id=project_id))
    output.mkdir(parents=True, exist_ok=True)
    for graph, application in applications:
        document = dict(
            format_id="amvision.workflow-app-document.v1",
            application=application.model_dump(mode="json"),
            template=graph.model_dump(mode="json"),
        )
        (output / f"{application.application_id}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return applications


def main():
    """命令行只生成离线文档，不覆盖服务中的已保存应用或运行实例。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--examples", type=Path, required=True)
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    applications = export_applications(
        args.assets, args.examples, args.installation, args.output
    )
    print(f"Exported {len(applications)} Workflow App documents to {args.output}")


if __name__ == "__main__":
    main()
