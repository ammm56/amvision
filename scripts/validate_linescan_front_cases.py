"""实际前图的已知扰动验证；生成物不作为真实缺陷样本或生产精度证据。"""

import argparse
import asyncio
import json
import struct

import cv2
import numpy as np

from scripts.configure_linescan_3913_workflow import DATA
from scripts.validate_linescan_3913_workflow import validate
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.mapped_roi_crop import (
    lift_transform,
)

ROOT = DATA / "validation/front-registered"


def result_value(folder):
    """解析标准 Preview 正文或已下载的资源，不依赖资源返回顺序。"""
    report = json.loads((folder / "report.json").read_text("utf-8"))
    outputs = report.get("outputs", {}).get("outputs", {})
    if "report" in outputs:
        return report, outputs["report"]["value"]
    for descriptor in report["resources"]:
        if descriptor["media_type"] == "application/json":
            value = json.loads((folder / descriptor["file"]).read_text("utf-8"))
            if "report" in value:
                return report, value["report"]["value"]
    return report, None


def code_texts(value):
    """按稳定槽位名称提取已解析文本，拒绝丢项或位置排序匹配。"""
    return {
        row["item_id"]: [
            code["text"]
            for item in row["result"]["items"]
            for code in item["result"]["items"]
            if code["valid"]
        ]
        for row in value["barcodes"]
    }


def controlled_fixtures():
    """在真实概览图上明确删除或移动一个槽位的暗前景；不是拟真的缺陷图。"""
    image = cv2.imdecode(
        np.fromfile(ROOT / "reference.png", np.uint8), cv2.IMREAD_COLOR
    )
    recipe = json.loads((ROOT / "recipe.json").read_text("utf-8"))
    roi = next(r for r in recipe["inspection_rois"] if r["roi_id"] == "slot-r02-c03")
    mask = np.zeros(image.shape[:2], np.uint8)
    cv2.fillPoly(mask, [np.array(roi["polygon_xy"], np.int32)], 255)
    mask[cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) > 100] = 0
    for point in recipe["localization"]["reference_points"]:
        cv2.circle(mask, tuple(np.rint(point["center_xy"]).astype(int)), 40, 0, -1)
    background = image.copy()
    background[mask != 0] = 235
    paths = []
    for name, angle, tx in [("missing", 0, 0), ("displaced", 0, 25), ("tilted", 6, 0)]:
        current = background.copy()
        if name != "missing":
            x1, y1, x2, y2 = roi["bbox_xyxy"]
            matrix = cv2.getRotationMatrix2D(((x1 + x2) / 2, (y1 + y2) / 2), angle, 1)
            matrix[0, 2] += tx
            moved = cv2.warpAffine(image, matrix, (2500, 2048))
            moved_mask = cv2.warpAffine(
                mask, matrix, (2500, 2048), flags=cv2.INTER_NEAREST
            )
            current[moved_mask != 0] = moved[moved_mask != 0]
        path = ROOT / f"controlled-{name}.png"
        cv2.imencode(".png", current)[1].tofile(path)
        paths.append((name, path))
    path = ROOT / "controlled-no-anchors.png"
    cv2.imencode(".png", np.full_like(image, 255))[1].tofile(path)
    return paths + [("no-anchors", path)]


def make_full_motion():
    """只读原 BMP，生成独立全分辨率运动图；不修改来源图片。"""
    source = DATA / "3913正面大图.bmp"
    with source.open("rb") as stream:
        header = stream.read(54)
    offset = struct.unpack_from("<I", header, 10)[0]
    width, height = struct.unpack_from("<ii", header, 18)
    if (width, height) != (20000, 16384) or struct.unpack_from("<H", header, 28)[
        0
    ] != 24:
        raise ValueError("验证夹具仅处理已核对的正面 24-bit BMP")
    source_rows = np.memmap(
        source, dtype=np.uint8, mode="r", offset=offset, shape=(height, width, 3)
    )
    small = np.eye(3)
    small[:2] = cv2.getRotationMatrix2D((1250, 1024), 2, 1)
    small[:2, 2] += [20, 10]
    matrix = lift_transform(small, 8)
    current = cv2.warpAffine(source_rows[::-1], matrix[:2], (width, height))
    path = ROOT / "full-motion.bmp"
    with path.open("wb") as stream:
        # 本样本 offset=54 且行宽整除 4，保持原始 BMP 头和底向上行序。
        if offset != 54 or width * 3 % 4:
            raise ValueError("BMP 头或行对齐不符合夹具要求")
        stream.write(header)
        for row in current[::-1]:
            stream.write(row.tobytes())
    (ROOT / "full-motion-transform.json").write_text(
        json.dumps(matrix.tolist()), "utf-8"
    )
    return path


def make_full_missing():
    """生成原分辨率单槽 PCB 区域被擦除的确定性夹具，用于验证异常槽跳过读码。"""
    source = DATA / "3913正面大图.bmp"
    path = ROOT / "full-missing.bmp"
    with source.open("rb") as stream:
        header = stream.read(54)
    if struct.unpack_from("<I", header, 10)[0] != 54 or struct.unpack_from(
        "<ii", header, 18
    ) != (20000, 16384):
        raise ValueError("BMP 头不符合夹具要求")
    rows = np.memmap(
        source, dtype=np.uint8, mode="r", offset=54, shape=(16384, 20000, 3)
    )
    with path.open("wb") as stream:
        stream.write(header)
        for index, row in enumerate(rows):
            y = 16383 - index
            if 1035 * 8 <= y < 1145 * 8:
                row = row.copy()
                row[810 * 8 : 1100 * 8] = 235
            stream.write(row.tobytes())
    return path


async def main(full):
    """逐步正式执行 Preview 并核对结果；失败用例同样必须按预期失败。"""
    report_root = DATA / "validation/front-array"
    cases = [
        (name, ROOT / f"localization-{name}.png")
        for name in ["shift", "rotate", "rotate-negative"]
    ]
    cases += controlled_fixtures()
    if full:
        cases += [
            ("full-original", DATA / "3913正面大图.bmp"),
            ("full-motion", make_full_motion()),
            ("full-missing", make_full_missing()),
            ("full-resized-search", DATA / "3913正面大图.bmp"),
        ]
    records = []
    for name, image in cases:
        failed = name == "no-anchors"
        await validate(
            argparse.Namespace(
                image=image,
                face="front",
                report=f"front-array/preview-{name}",
                local_file=True,
                inspection_only=not name.startswith("full-"),
                expect_status="failed" if failed else "succeeded",
                barcode_bbox=[1620, 950, 2820, 2050]
                if name == "full-resized-search"
                else None,
            )
        )
        report, value = result_value(report_root / f"preview-{name}")
        record = {
            "case": name,
            "state": report["terminal"]["status"],
            "timings": report["terminal"].get("timings"),
            "session_released": report["session_released"],
        }
        if failed:
            assert report["terminal"]["error"]["node_id"] == "locate"
        else:
            failures = [
                r["item_id"]
                for r in value["placement_2d"]["items"]
                if not r["result"]["passed"]
            ]
            record["failed_slots"] = failures
            assert len(value["placement_2d"]["items"]) == 18
            if name == "displaced":
                # 25像素横移同时侵入邻槽的边界观察域，两个槽均应标记。
                assert failures == ["slot-r02-c03", "slot-r02-c04"]
            elif name in {"missing", "tilted", "full-missing"}:
                assert failures == ["slot-r02-c03"]
            else:
                assert not failures
            if name == "full-original":
                assert len(code_texts(value)) == 18
                assert all(len(texts) == 1 for texts in code_texts(value).values())
            if name in {"full-motion", "full-resized-search"}:
                _, original = result_value(report_root / "preview-full-original")
                record["decoded_count"] = sum(
                    bool(v) for v in code_texts(value).values()
                )
                record["same_codes_as_original"] = code_texts(value) == code_texts(
                    original
                )
                assert record["same_codes_as_original"]
            if name == "full-missing":
                skipped = sorted(set(failures) - set(code_texts(value)))
                assert skipped == ["slot-r02-c03"]
                assert len(value["barcodes"]) == 17
                assert all(len(texts) == 1 for texts in code_texts(value).values())
                record.update(skipped=skipped, decoded_count=17)
        records.append(record)
        (report_root / "chain-cases.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), "utf-8"
        )
        print(record, flush=True)


def validate_placement_offline():
    """直接调用实际定位、比较处理器，独立核对整盘运动和局部异常。"""
    from dataclasses import replace
    from backend.nodes import ExecutionImageRegistry
    from backend.nodes.runtime_support import register_typed_image_matrix
    from custom_nodes.opencv_nodes.categories.defect.backend.nodes.roi_foreground_compare import (
        handle_node as compare,
    )
    from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.roi_array import (
        handle_node as array,
    )
    from backend.nodes.core_nodes.support.roi import (
        build_roi_payload,
        bbox_to_polygon_xy,
        polygon_bbox_xyxy,
        polygon_area,
    )
    from scripts.validate_linescan_front_registration import (
        request,
        image_ref,
        hough,
        locate,
        build_recipe,
    )

    recipe = build_recipe()
    bundle = json.loads(
        (DATA / "validation/front-array/workflow-bundle.json").read_text("utf-8")
    )
    nodes = {n["node_id"]: n for n in bundle["template"]["nodes"]}
    seed_points = nodes["slot_seed"]["parameters"]["polygon_xy"]
    seed = build_roi_payload(
        roi_id="seed",
        display_name=None,
        roi_kind="polygon",
        polygon_xy=seed_points,
        bbox_xyxy=polygon_bbox_xyxy(seed_points),
        area=polygon_area(seed_points),
    )
    box = nodes["tray_roi"]["parameters"]["bbox_xyxy"]
    frame = build_roi_payload(
        roi_id="frame",
        display_name=None,
        roi_kind="bbox",
        bbox_xyxy=box,
        polygon_xy=bbox_to_polygon_xy(box),
        area=round((box[2] - box[0]) * (box[3] - box[1])),
    )
    rois = array(
        request(
            "geometry",
            "roi_array",
            {"roi": seed, "frame": frame},
            nodes["slot_array"]["parameters"],
        )
    )["rois"]
    parameters = next(
        n["parameters"]
        for n in bundle["template"]["nodes"]
        if n["node_id"] == "compare_foreground"
    )
    cases = [
        (n, ROOT / f"localization-{n}.png")
        for n in ("original", "shift", "rotate", "rotate-negative")
    ]
    cases += controlled_fixtures()
    records = []
    for name, path in cases:
        registry = ExecutionImageRegistry()
        try:
            circles = hough(
                request(
                    "shape",
                    "hough_circles",
                    {"image": image_ref(path)},
                    recipe["hough"],
                )
            )
            try:
                pose = locate(
                    request(
                        "matching",
                        "circle_pattern_locate",
                        {"circles": circles["circles"]},
                        recipe["localization"],
                    )
                )
            except Exception:
                if name != "no-anchors":
                    raise
                records.append({"case": name, "localization_rejected": True})
                continue
            assert name != "no-anchors"
            source = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
            aligned = cv2.warpPerspective(
                source,
                np.asarray(pose["transform"]["matrix_3x3"]),
                (2500, 2048),
                flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
            )
            req = replace(
                request("defect", "roi_foreground_compare", {}, parameters),
                execution_metadata={"execution_image_registry": registry},
            )
            current = register_typed_image_matrix(req, image_matrix=aligned)
            output = compare(
                replace(
                    req,
                    input_values={
                        "image": current,
                        "reference_image": image_ref(ROOT / "reference.png"),
                        "rois": rois,
                    },
                )
            )
            items = output["summary"]["value"]["items"]
            failed = [r["item_id"] for r in items if not r["result"]["passed"]]
            expected = (
                ["slot-r02-c03", "slot-r02-c04"]
                if name == "displaced"
                else ["slot-r02-c03"]
                if name in {"missing", "tilted"}
                else []
            )
            assert failed == expected, (name, failed)
            records.append({"case": name, "failed": failed, "items": items})
            print(name, "passed", 18 - len(failed), "failed", failed, flush=True)
        finally:
            registry.clear()
    report = ROOT.parent / "front-array/placement-cases.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(records, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-motion", action="store_true")
    parser.add_argument("--offline-placement", action="store_true")
    args = parser.parse_args()
    if args.offline_placement:
        validate_placement_offline()
    else:
        asyncio.run(main(args.full_motion))
