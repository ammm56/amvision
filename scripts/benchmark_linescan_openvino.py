"""同一真实搜索图、同一 FP32 模型交替对照请求复用，不改已有部署配置。"""

import json
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
import openvino as ov

from custom_nodes.opencv_nodes.shared.backend.runtime.bmp import read_bgr24_bmp
from scripts.configure_linescan_3913_workflow import DATA


def main():
    """同步串行 18 次，比较原始模型输出及总时间；不创建队列。"""
    from backend.service.application.runtime.predictors.yolox.io import (
        preprocess_yolox_image,
    )

    image = read_bgr24_bmp(DATA / "3913正面大图.bmp")[2240:3240, 2560:3560].copy()
    tensor, _ = preprocess_yolox_image(
        cv2_module=cv2, np_module=np, image=image, input_size=(640, 640)
    )
    tensor = np.expand_dims(tensor, 0).astype(np.float32)
    model = Path(
        "data/files/task-runs/conversion/task-ea61996024cd/artifacts/builds/yolox-m-barcodeqrcode-20261024222905-m.openvino.xml"
    )
    rows = []
    for threads in [0, 8, 16]:
        properties = {"PERFORMANCE_HINT": "LATENCY", "NUM_STREAMS": 1}
        if threads:
            properties["INFERENCE_NUM_THREADS"] = threads
        compiled = ov.Core().compile_model(str(model), "CPU", properties)
        request = compiled.create_infer_request()
        source = {compiled.input(0): tensor}
        expected = compiled.infer_new_request(source)[compiled.output(0)]
        for iteration in range(3):
            for reuse in [False, True] if iteration % 2 == 0 else [True, False]:
                start = perf_counter()
                for _ in range(18):
                    result = (
                        request.infer(source)
                        if reuse
                        else compiled.infer_new_request(source)
                    )
                    np.testing.assert_array_equal(result[compiled.output(0)], expected)
                row = {
                    "threads": threads,
                    "reuse": reuse,
                    "iteration": iteration,
                    "elapsed_ms": (perf_counter() - start) * 1000,
                }
                rows.append(row)
                print(json.dumps(row), flush=True)
        del request, compiled
    out = DATA / "validation/front-optimization-20261030/openvino-request.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), "utf-8")


if __name__ == "__main__":
    main()
