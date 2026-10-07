"""由 Blender 离线生成连接器开发图、解析几何真值和标定图，不接入产品运行时。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector


def write_json(path: Path, value: object) -> None:
    """将 value 以可审阅的 UTF-8 JSON 写入指定 path。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def material(name: str, rgb: tuple, metallic: float = 0.0, emission: bool = False):
    """建立指定颜色的表面；emission 用于无阴影的标定板。"""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = 0.32 if metallic else 0.7
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*rgb, 1)
        bsdf.inputs["Emission Strength"].default_value = 1
    return mat


def cube(name: str, center: tuple, dimensions: tuple, mat, parent=None, bevel_mm: float = 0.0):
    """用毫米中心和尺寸建立长方体，只有非计量壳体允许倒角。"""
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = tuple(v / 1000 for v in dimensions)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.parent = parent
    obj.location = tuple(v / 1000 for v in center)
    obj.data.materials.append(mat)
    if bevel_mm:
        modifier = obj.modifiers.new("housing bevel", "BEVEL")
        modifier.width = bevel_mm / 1000
        modifier.segments = 2
        obj.modifiers.new("normals", "WEIGHTED_NORMAL")
    return obj


def setup_scene(spec: dict, perspective: bool = False, exposure: float = 0.0):
    """准备固定相机及有界 CPU 渲染，避免依赖现场 GPU 或用户 Blender 启动配置。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    config = spec["render"]
    scene.unit_settings.system = "METRIC"
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = config["samples"]
    scene.cycles.use_denoising = False
    scene.cycles.seed = 1007
    scene.render.threads_mode = "FIXED"
    scene.render.threads = config["threads"]
    scene.render.resolution_x = config["width"]
    scene.render.resolution_y = config["height"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = exposure
    world = bpy.data.worlds.new("studio")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.3, 0.3, 0.3, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.5
    scene.world = world
    bpy.ops.object.camera_add(location=(0, 0, config["camera_distance_mm"] / 1000))
    camera = bpy.context.object
    camera.data.type = "PERSP" if perspective else "ORTHO"
    camera.data.sensor_fit = "HORIZONTAL"
    camera.data.sensor_width = config["sensor_width_mm"]
    camera.data.lens = config["focal_length_mm"]
    camera.data.ortho_scale = config["ortho_width_mm"] / 1000
    camera.data.clip_start = 0.001
    camera.data.clip_end = 10
    scene.camera = camera
    for index, position in enumerate(((-20, 10, 45), (24, -10, 30))):
        bpy.ops.object.light_add(type="AREA", location=tuple(v / 1000 for v in position))
        lamp = bpy.context.object
        lamp.name = f"area_{index}"
        lamp.data.energy = 0.002 if index == 0 else 0.0006
        lamp.data.shape = "DISK"
        lamp.data.size = 0.04
        lamp.rotation_euler = (-lamp.location).to_track_quat("-Z", "Y").to_euler()
    background = material("background", (0.16, 0.18, 0.20))
    cube("background", (0, 0, -5), (150, 100, 0.5), background)
    return scene


def root_object(name: str, translation: tuple, angle: float):
    """建立工件原点，translation 使用毫米，angle 为逆时针角度。"""
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    obj.location = tuple(v / 1000 for v in translation)
    obj.rotation_euler.z = math.radians(angle)
    return obj


def project(scene, point_mm: list) -> list:
    """以 Blender 相机投影毫米世界点；结果采用左上角像素中心为 (0,0)。"""
    ndc = world_to_camera_view(scene, scene.camera, Vector(point_mm) / 1000)
    return [ndc.x * scene.render.resolution_x - 0.5, (1 - ndc.y) * scene.render.resolution_y - 0.5]


def world_point(root, point_mm: list) -> list:
    """把局部毫米点转换到世界毫米点，不调用待开发的节点算法。"""
    return list((root.matrix_world @ (Vector(point_mm) / 1000)) * 1000)


def camera_truth(scene, spec: dict) -> dict:
    """输出解析相机参数，供独立校验程序与 Blender 投影交叉核对。"""
    config = spec["render"]
    width, height = config["width"], config["height"]
    focal = config["focal_length_mm"] / config["sensor_width_mm"] * width
    return {
        "model": "pinhole" if scene.camera.data.type == "PERSP" else "orthographic",
        "width": width, "height": height, "pixel_center_origin": "top-left pixel center = (0,0)",
        "camera_world_mm": [0, 0, config["camera_distance_mm"]],
        "world_to_camera_axes": [[1, 0, 0], [0, -1, 0], [0, 0, -1]],
        "principal_point_px": [(width - 1) / 2, (height - 1) / 2],
        "focal_px": focal if scene.camera.data.type == "PERSP" else None,
        "pixels_per_mm": width / config["ortho_width_mm"] if scene.camera.data.type == "ORTHO" else None,
        "distortion_coefficients": [0, 0, 0, 0, 0],
        "note": "Ideal synthetic camera. No sensor noise or lens distortion is claimed."
    }


def cases() -> list[dict]:
    """固定工程开发/保留验证条件，包含缺首中末 PIN 和无效分支。"""
    return [
        {"id": "reference", "split": "reference"},
        {"id": "translate", "shift": [2.1, -0.7], "split": "development"},
        {"id": "rotate_pos", "angle": 7, "split": "development"},
        {"id": "rotate_neg", "angle": -11, "split": "validation"},
        {"id": "missing_first", "missing": 0, "split": "development"},
        {"id": "missing_middle", "missing": 4, "split": "validation"},
        {"id": "missing_last", "missing": -1, "split": "validation"},
        {"id": "offset", "offset": 0.25, "split": "development"},
        {"id": "narrow", "width": 0.45, "split": "development"},
        {"id": "wide", "width": 0.84, "split": "validation"},
        {"id": "width_on_limit", "width": 0.69, "split": "validation"},
        {"id": "width_inside_limit", "width": 0.68, "split": "validation"},
        {"id": "width_outside_limit", "width": 0.70, "split": "validation"},
        {"id": "designed_empty", "empty": 4, "split": "development"},
        {"id": "empty_occupied", "empty": 4, "occupied": True, "split": "validation"},
        {"id": "extra_pin", "extra": True, "split": "validation"},
        {"id": "dark", "exposure": -1.5, "split": "development"},
        {"id": "bright", "exposure": 1.0, "split": "validation"},
        {"id": "cropped", "shift": [13, 0], "split": "validation"},
        {"id": "no_part", "no_part": True, "split": "validation"},
        {"id": "two_parts", "two_parts": True, "split": "validation"},
        {"id": "perspective", "perspective": True, "angle": 5, "shift": [1, 0.4], "split": "development"}
    ]


def build_part(scene, family: dict, case: dict):
    """建立简化几何与名义/实际 PIN；材质与壳体外形不宣称复刻厂商产品。"""
    is_front = family["view"] == "front"
    columns, rows = family["columns"], family["rows"]
    pitch, nominal_width = family["pitch_mm"], family["pin_width_mm"]
    shift = case.get("shift", [0, 0])
    root = root_object("part", (shift[0], shift[1] - (2.77 if is_front else 0), 0), case.get("angle", 0))
    black = material("housing", (0.018, 0.023, 0.030))
    gold = material("pins", (0.55, 0.31, 0.075), metallic=0.7)
    marker = material("synthetic orientation mark", (0.85, 0.85, 0.83))
    length = columns * pitch
    if not case.get("no_part"):
        if is_front:
            cube("housing", (0, 1.27, 0), (length, 2.54, 2.54), black, root, 0.07)
            cube("orientation_mark", (-length / 2 + 0.8, 1.27, 1.29), (0.5, 1, 0.04), marker, root)
        else:
            cube("housing", (0, 0, -1.27), (length, rows * pitch, 2.54), black, root, 0.07)
            cube("orientation_mark", (-length / 2 + 0.7, rows * pitch / 2 - 0.6, 0.02), (0.5, 0.5, 0.04), marker, root)
    pins = []
    count = rows * columns
    for row in range(rows):
        for column in range(columns):
            index = row * columns + column
            pin_id = f"R{row + 1}P{column + 1:02d}"
            x = (column - (columns - 1) / 2) * pitch
            y = 5.54 if is_front else (row - (rows - 1) / 2) * pitch
            nominal = [x, y, 0.32 if is_front else 6]
            expected_present = index != case.get("empty", -100)
            actual_present = not case.get("no_part") and (expected_present or case.get("occupied", False))
            if "missing" in case and index == case["missing"] % count:
                actual_present = False
            width = case.get("width", nominal_width) if index == 4 else nominal_width
            x += case.get("offset", 0) if index == 4 else 0
            actual = [x, y, nominal[2]]
            if actual_present:
                if is_front:
                    cube(pin_id, (x, 2.77, 0), (width, 11.54, nominal_width), gold, root)
                else:
                    cube(pin_id, (x, y, 1.5), (width, nominal_width, 9), gold, root)
            pins.append({"pin_id": pin_id, "row": row, "column": column, "expected_present": expected_present,
                         "actual_present": actual_present, "nominal_center_local_mm": nominal,
                         "actual_center_local_mm": actual if actual_present else None,
                         "width_mm": width if actual_present else None})
    extras = []
    if case.get("extra"):
        point = [-length / 2 + pitch, 10 if is_front else rows * pitch / 2 + 1, 0.32 if is_front else 6]
        cube("extra_pin", (point[0], point[1], 0 if is_front else 1.5), (0.64, 1.3 if is_front else 0.64, 0.64 if is_front else 9), gold, root)
        extras.append({"id": "extra-1", "center_local_mm": point})
    if case.get("two_parts"):
        # 两件仅用于定位歧义分支，不作为下面单工件计量真值的输入。
        root.location.y -= 0.004 if is_front else 0.0035
        root.scale = (0.65, 0.65, 0.65)
        second = root.copy()
        bpy.context.collection.objects.link(second)
        second.name = "part_second"
        second.location.y += 0.009 if is_front else 0.008
        for child in list(root.children):
            duplicate = child.copy()
            bpy.context.collection.objects.link(duplicate)
            duplicate.parent = second
    bpy.context.view_layer.update()
    for pin in pins:
        pin["nominal_center_image_px"] = project(scene, world_point(root, pin["nominal_center_local_mm"]))
        if pin["actual_present"]:
            center = pin["actual_center_local_mm"]
            left = [center[0] - pin["width_mm"] / 2, center[1], center[2]]
            right = [center[0] + pin["width_mm"] / 2, center[1], center[2]]
            pin["width_endpoints_world_mm"] = [world_point(root, left), world_point(root, right)]
            pin["width_endpoints_image_px"] = [project(scene, p) for p in pin["width_endpoints_world_mm"]]
            pin["center_world_mm"] = world_point(root, center)
            pin["center_image_px"] = project(scene, pin["center_world_mm"])
    for extra in extras:
        extra["center_image_px"] = project(scene, world_point(root, extra["center_local_mm"]))
    return root, pins, extras


def expected_result(spec: dict, case: dict, pins: list, extras: list) -> dict:
    """按显式工程规则计算解析预期；不调用任何图像测量实现。"""
    invalid = "not_found" if case.get("no_part") else "ambiguous" if case.get("two_parts") else "out_of_view" if case["id"] == "cropped" else None
    if invalid:
        return {"state": "invalid", "reason": invalid, "measurements_valid": False, "checks": []}
    rules = spec["engineering_rules"]
    checks = []
    for pin in pins:
        checks.append({"id": "presence:" + pin["pin_id"], "passed": pin["expected_present"] == pin["actual_present"]})
        if pin["expected_present"] and pin["actual_present"]:
            width = pin["width_mm"]
            checks.append({"id": "width:" + pin["pin_id"], "value_mm": width,
                           "passed": rules["pin_width_min_mm"] <= width <= rules["pin_width_max_mm"]})
            offset = abs(pin["actual_center_local_mm"][0] - pin["nominal_center_local_mm"][0])
            checks.append({"id": "offset:" + pin["pin_id"], "value_mm": offset, "passed": offset <= rules["max_offset_mm"]})
    for first, second in zip(pins, pins[1:]):
        if first["row"] != second["row"] or not (first["expected_present"] and second["expected_present"]):
            continue
        if not (first["actual_present"] and second["actual_present"]):
            checks.append({"id": f"pitch:{first['pin_id']}:{second['pin_id']}", "value_mm": None, "passed": False, "valid": False})
            continue
        distance = abs(second["actual_center_local_mm"][0] - first["actual_center_local_mm"][0])
        checks.append({"id": f"pitch:{first['pin_id']}:{second['pin_id']}", "value_mm": distance,
                       "passed": rules["pitch_min_mm"] <= distance <= rules["pitch_max_mm"]})
    checks.append({"id": "unexpected_objects", "passed": not extras})
    return {"state": "ok" if all(x["passed"] for x in checks) else "ng", "checks": checks,
            "note": "Synthetic rule oracle; rendered intensity boundaries need an explicit error allowance."}


def render(scene, path: Path) -> None:
    """输出无文字/标注的原始合成 PNG，不将 JPEG 当计量母图。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def generate_connector(spec: dict, output: Path, family: dict, case: dict) -> dict:
    """生成一幅工件图、真值与必要的可编辑 Blender 场景。"""
    scene = setup_scene(spec, case.get("perspective", False), case.get("exposure", 0))
    root, pins, extras = build_part(scene, family, case)
    sample_id = family["id"] + "__" + case["id"]
    image_path = Path("images") / (sample_id + ".png")
    truth_path = Path("truth") / (sample_id + ".json")
    transform = root.matrix_world.copy()
    transform.translation *= 1000
    camera = camera_truth(scene, spec)
    cx, cy = camera["principal_point_px"]
    if camera["model"] == "orthographic":
        scale = camera["pixels_per_mm"]
        projection = Matrix(((scale, 0, 0, cx), (0, -scale, 0, cy), (0, 0, 0, 1)))
    else:
        focal, distance = camera["focal_px"], camera["camera_world_mm"][2]
        projection = Matrix(((focal, 0, -cx, cx * distance), (0, -focal, -cy, cy * distance), (0, 0, -1, distance)))
    plane_z = 0.32 if family["view"] == "front" else 6
    plane_embedding = Matrix(((1, 0, 0), (0, 1, 0), (0, 0, plane_z), (0, 0, 1)))
    homography = projection @ transform @ plane_embedding
    truth = {"sample_id": sample_id, "synthetic": True, "family": family, "condition": case,
             "camera": camera, "world_from_part_mm": [list(row) for row in transform],
             "measurement_plane_local_z_mm": plane_z,
             "image_from_measurement_plane": [list(row) for row in homography],
             "measurement_plane_from_image": [list(row) for row in homography.inverted()],
             "pins": pins, "extra_observations": extras,
             "object_count": 0 if case.get("no_part") else 2 if case.get("two_parts") else 1,
             "expected": expected_result(spec, case, pins, extras)}
    render(scene, output / image_path)
    write_json(output / truth_path, truth)
    if case["id"] == "reference":
        scene_path = output / "scenes" / (family["id"] + ".blend")
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(scene_path))
        length = family["columns"] * family["pitch_mm"]
        y0, y1 = (0, 2.54) if family["view"] == "front" else (-2.54, 2.54)
        z = 1.27 if family["view"] == "front" else 0
        roi = [project(scene, world_point(root, [x, y, z])) for x, y in ((-length / 2, y0), (length / 2, y0), (length / 2, y1), (-length / 2, y1))]
        write_json(output / "references" / (family["id"] + ".json"), {
            "image": image_path.as_posix(), "truth": truth_path.as_posix(), "template_roi_polygon_px": roi,
            "template_anchor_image_px": project(scene, world_point(root, [0, 0, z])),
            "layout": [{"pin_id": p["pin_id"], "expected_present": p["expected_present"], "center_local_mm": p["nominal_center_local_mm"]} for p in pins],
            "note": "Reference + explicit ROI, not an installed application template. Orientation mark is a synthetic fixture feature."
        })
    return {"id": sample_id, "image": image_path.as_posix(), "truth": truth_path.as_posix(), "split": case["split"], "expected_state": truth["expected"]["state"]}


def generate_calibration(spec: dict, output: Path, index: int) -> dict:
    """渲染具有已知内参与姿态的多视角棋盘，单独验证标定而非模拟实际镜头。"""
    scene = setup_scene(spec, perspective=True)
    cfg = spec["calibration"]
    cols, rows, square = cfg["columns_inner"] + 1, cfg["rows_inner"] + 1, cfg["square_size_mm"]
    board = root_object("board", (((index % 3) - 1) * 6, ((index // 3) % 3 - 1) * 4, (index % 4) * 2), (index % 5 - 2) * 7)
    board.rotation_euler.x = math.radians((index % 4 - 1.5) * 12)
    board.rotation_euler.y = math.radians((index // 4 - 1) * 18)
    white = material("white", (0.85, 0.85, 0.85), emission=True)
    black = material("black", (0.005, 0.005, 0.005), emission=True)
    cube("border", (0, 0, -0.06), (cols * square + 2, rows * square + 2, 0.1), white, board)
    for row in range(rows):
        for column in range(cols):
            cube("square", ((column - (cols - 1) / 2) * square, (row - (rows - 1) / 2) * square, 0), (square, square, 0.02), white if (row + column) % 2 else black, board)
    bpy.context.view_layer.update()
    corners = [world_point(board, [(column + 1 - cols / 2) * square, (row + 1 - rows / 2) * square, 0.01]) for row in range(rows - 1) for column in range(cols - 1)]
    sample_id = f"calibration_{index:02d}"
    image_path = Path("calibration") / (sample_id + ".png")
    truth_path = image_path.with_suffix(".json")
    render(scene, output / image_path)
    write_json(output / truth_path, {"sample_id": sample_id, "synthetic": True, "camera": camera_truth(scene, spec),
               "pattern_size": [cols - 1, rows - 1], "square_size_mm": square,
               "corners_world_mm": corners, "corners_image_px": [project(scene, p) for p in corners]})
    return {"id": sample_id, "image": image_path.as_posix(), "truth": truth_path.as_posix(), "split": "calibration"}


def main() -> None:
    """只向新输出目录生成资源；拒绝覆盖已有样本，防止破坏手工数据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--smoke", action="store_true", help="只生成一个参考样本供渲染核对")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"输出目录必须为空: {output}")
    spec_path = Path(__file__).with_name("spec.json")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "spec.json", spec)
    samples = []
    selected_families = spec["families"][:1] if args.smoke else spec["families"]
    selected_cases = cases()[:1] if args.smoke else cases()
    for family in selected_families:
        for case in selected_cases:
            samples.append(generate_connector(spec, output, family, case))
            print("ASSET_COMPLETE", samples[-1]["id"], flush=True)
    if not args.smoke:
        for index in range(spec["calibration"]["views"]):
            samples.append(generate_calibration(spec, output, index))
            print("ASSET_COMPLETE", samples[-1]["id"], flush=True)
    for sample in samples:
        sample["image_sha256"] = hashlib.sha256((output / sample["image"]).read_bytes()).hexdigest()
        sample["truth_sha256"] = hashlib.sha256((output / sample["truth"]).read_bytes()).hexdigest()
    write_json(output / "manifest.json", {"dataset_id": spec["dataset_id"], "blender_version": bpy.app.version_string,
               "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
               "synthetic": True, "real_metrology_reference": False, "samples": samples})


if __name__ == "__main__":
    main()
