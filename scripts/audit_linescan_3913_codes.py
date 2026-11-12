"""离线对照实际白码像素及解码参数；不修改 Workflow，也不生成替代条码。"""

import json

import cv2
import numpy as np
from PIL import Image
import zxingcpp

from scripts.configure_linescan_3913_workflow import DATA


def main():
    """用已执行的定位框从原 BMP 裁像素，逐项保存解码对照结果。"""
    folder = DATA / "validation/front-bmp-final"
    result = None
    for path in sorted(folder.glob("resource*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "report" in payload:
            result = payload["report"]["value"]
    if result is None:
        raise RuntimeError("先完成 front-bmp-final 验证")
    output = DATA / "validation/barcode-pixel-audit"
    output.mkdir(exist_ok=True)
    Image.MAX_IMAGE_PIXELS = 300_000_000
    rows = []
    with Image.open(DATA / "3913正面.bmp") as image:
        for slot in result["barcodes"]:
            source = slot["source"]
            if not slot["result"]["items"]:
                continue
            box = slot["result"]["items"][0]["source"]["bbox_xyxy"]
            ox, oy = source["bbox_xyxy"][:2]
            crop = image.crop((ox + box[0], oy + box[1], ox + box[2], oy + box[3]))
            crop.save(output / (source["roi_id"] + ".png"))
            rgb = np.asarray(crop)
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            candidates = {
                "rgb": rgb,
                "gray": gray,
                "red": rgb[:, :, 0],
                "green": rgb[:, :, 1],
                "blue": rgb[:, :, 2],
                "gray_3x": cv2.resize(
                    gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC
                ),
            }
            outcomes = {}
            for name, pixels in candidates.items():
                for algorithm in ("LocalAverage", "GlobalHistogram", "FixedThreshold"):
                    codes = zxingcpp.read_barcodes(
                        pixels,
                        formats=zxingcpp.BarcodeFormat.DataMatrix,
                        binarizer=getattr(zxingcpp.Binarizer, algorithm),
                        try_rotate=True,
                        try_invert=True,
                    )
                    outcomes[name + "/" + algorithm] = [
                        code.text for code in codes if code.valid
                    ]
            rows.append({"roi_id": source["roi_id"], "tests": outcomes})
    (output / "report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: sum(bool(row["tests"][key]) for row in rows)
                for key in rows[0]["tests"]
            },
            ensure_ascii=False,
        )
    )
    print(
        "unreadable", [row["roi_id"] for row in rows if not any(row["tests"].values())]
    )


if __name__ == "__main__":
    main()
