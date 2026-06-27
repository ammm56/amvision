"""YOLO task 输出格式边界回归测试。"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from backend.service.application.models.yolo_core_common.geometry import (
    build_yolo_letterbox_transform,
)
from backend.service.application.models.yolo11_core.decode.detection import (
    build_yolo11_detection_prediction,
    decode_yolo11_detection_boxes_xywh,
    decode_yolo11_detection_boxes_xyxy,
)
from backend.service.application.models.yolo11_core.postprocess.detection import (
    build_yolo11_detection_records,
)
from backend.service.application.models.yolo11_core.postprocess.obb import (
    build_yolo11_obb_postprocess_instances,
)
from backend.service.application.models.yolo11_core.postprocess.pose import (
    build_yolo11_pose_postprocess_instances,
)
from backend.service.application.models.yolo11_core.postprocess.segmentation import (
    prepare_yolo11_segmentation_nms_inputs_array,
)
from backend.service.application.models.yolo26_core.decode.detection import (
    build_yolo26_detection_prediction,
)
from backend.service.application.models.yolo26_core.postprocess.detection import (
    build_yolo26_detection_records,
)
from backend.service.application.models.yolo26_core.postprocess.obb import (
    build_yolo26_obb_postprocess_instances,
)
from backend.service.application.models.yolo26_core.postprocess.pose import (
    build_yolo26_pose_postprocess_instances,
)
from backend.service.application.models.yolo26_core.postprocess.segmentation import (
    prepare_yolo26_segmentation_topk_inputs_array,
)
from backend.service.application.models.yolov8_core.decode.detection import (
    build_yolov8_detection_prediction,
    decode_yolov8_detection_boxes,
)
from backend.service.application.models.yolov8_core.postprocess.detection import (
    build_yolov8_detection_records,
)


def _build_raw_detection_outputs() -> dict[str, torch.Tensor]:
    """构造一个单 anchor 的 raw detection 输出。"""

    return {
        "feats": (torch.zeros((1, 1, 1, 1), dtype=torch.float32),),
        "boxes": torch.tensor([[[1.0], [2.0], [3.0], [4.0]]], dtype=torch.float32),
        "scores": torch.tensor([[[4.0]]], dtype=torch.float32),
    }


def _keep_all_nms_indices(
    *,
    boxes: np.ndarray,
    scores: np.ndarray,
    class_ids: np.ndarray,
    nms_threshold: float,
    np_module: object,
) -> np.ndarray:
    """测试用 NMS：保留全部候选。"""

    _ = boxes, scores, class_ids, nms_threshold
    return np_module.arange(1, dtype=np_module.int64)


def _wide_letterbox_transform():
    """构造 1920x1080 到 640x640 的中心 LetterBox 变换。"""

    return build_yolo_letterbox_transform(
        source_width=1920,
        source_height=1080,
        input_size=(640, 640),
    )


def test_yolov8_yolo11_decode_raw_predictions_as_xywh() -> None:
    """YOLOv8 / YOLO11 非 end2end raw 推理输出保持 Ultralytics 默认 xywh。"""

    raw_outputs = _build_raw_detection_outputs()
    dfl_decoder = torch.nn.Identity()

    yolov8_boxes = decode_yolov8_detection_boxes(
        raw_outputs=raw_outputs,
        strides=(10,),
        dfl_decoder=dfl_decoder,
    )
    yolo11_boxes = decode_yolo11_detection_boxes_xywh(
        raw_outputs=raw_outputs,
        strides=(10,),
        dfl_decoder=dfl_decoder,
    )
    yolo11_boxes_xyxy = decode_yolo11_detection_boxes_xyxy(
        raw_outputs=raw_outputs,
        strides=(10,),
        dfl_decoder=dfl_decoder,
    )

    assert yolov8_boxes.detach().cpu().tolist() == [[[15.0], [15.0], [40.0], [60.0]]]
    assert yolo11_boxes.detach().cpu().tolist() == [[[15.0], [15.0], [40.0], [60.0]]]
    assert yolo11_boxes_xyxy.detach().cpu().tolist() == [[[-5.0], [-15.0], [35.0], [45.0]]]


def test_yolo26_detection_prediction_defaults_to_xyxy() -> None:
    """YOLO26 end2end detection 推理张量默认使用 xyxy。"""

    prediction = build_yolo26_detection_prediction(
        raw_outputs=_build_raw_detection_outputs(),
        strides=(10,),
        dfl_decoder=torch.nn.Identity(),
    )

    assert prediction.detach().cpu().tolist() == [
        [[-5.0], [-15.0], [35.0], [45.0], [pytest.approx(0.9820137619972229)]]
    ]


def test_yolov8_yolo11_prediction_builders_emit_xywh_raw_output() -> None:
    """YOLOv8 / YOLO11 inference builder 对外仍是 raw xywh + class scores。"""

    yolov8_prediction = build_yolov8_detection_prediction(
        raw_outputs=_build_raw_detection_outputs(),
        strides=(10,),
        dfl_decoder=torch.nn.Identity(),
    )
    yolo11_prediction = build_yolo11_detection_prediction(
        raw_outputs=_build_raw_detection_outputs(),
        strides=(10,),
        dfl_decoder=torch.nn.Identity(),
    )

    assert yolov8_prediction[:, :4].detach().cpu().tolist() == [
        [[15.0], [15.0], [40.0], [60.0]]
    ]
    assert yolo11_prediction[:, :4].detach().cpu().tolist() == [
        [[15.0], [15.0], [40.0], [60.0]]
    ]


def test_yolov8_yolo11_runtime_records_are_original_image_xyxy() -> None:
    """YOLOv8 / YOLO11 runtime 消费 raw xywh，但公开输出原图坐标 xyxy。"""

    letterbox_transform = build_yolo_letterbox_transform(
        source_width=1920,
        source_height=1080,
        input_size=(640, 640),
    )
    prediction_array = np.asarray(
        [[[320.0, 320.0, 160.0, 80.0, 0.9]]],
        dtype=np.float32,
    )

    yolov8_records = build_yolov8_detection_records(
        np_module=np,
        prediction_array=prediction_array,
        labels=("barcode",),
        score_threshold=0.01,
        nms_threshold=0.7,
        letterbox_transform=letterbox_transform,
    )
    yolo11_records = build_yolo11_detection_records(
        np_module=np,
        prediction_array=prediction_array,
        labels=("barcode",),
        score_threshold=0.01,
        nms_threshold=0.7,
        letterbox_transform=letterbox_transform,
    )

    assert yolov8_records[0].bbox_xyxy == (720.0, 420.0, 1200.0, 660.0)
    assert yolo11_records[0].bbox_xyxy == (720.0, 420.0, 1200.0, 660.0)


def test_yolo26_runtime_records_consume_processed_xyxy_output() -> None:
    """YOLO26 runtime 消费 end2end processed xyxy，并公开原图坐标 xyxy。"""

    records = build_yolo26_detection_records(
        np_module=np,
        prediction_array=np.asarray(
            [[[240.0, 280.0, 400.0, 360.0, 0.9, 0.0]]],
            dtype=np.float32,
        ),
        labels=("barcode",),
        score_threshold=0.01,
        nms_threshold=0.7,
        letterbox_transform=build_yolo_letterbox_transform(
            source_width=1920,
            source_height=1080,
            input_size=(640, 640),
        ),
    )

    assert records[0].bbox_xyxy == (720.0, 420.0, 1200.0, 660.0)


def test_yolo11_segmentation_uses_xywh_boxes_only_for_candidate_filtering() -> None:
    """YOLO11 segmentation raw box 只作为 mask 候选筛选辅助。"""

    nms_inputs = prepare_yolo11_segmentation_nms_inputs_array(
        image_prediction=np.asarray([[320.0, 320.0, 160.0, 80.0, 0.9, 0.25]]),
        np_module=np,
        num_classes=1,
        score_threshold=0.01,
    )

    assert nms_inputs is not None
    assert nms_inputs.boxes_xyxy.tolist() == [[240.0, 280.0, 400.0, 360.0]]


def test_yolo26_segmentation_uses_xyxy_boxes_only_for_end2end_candidate_filtering() -> None:
    """YOLO26 segmentation end2end box 只作为 mask 候选筛选辅助。"""

    topk_inputs = prepare_yolo26_segmentation_topk_inputs_array(
        image_prediction=np.asarray([[240.0, 280.0, 400.0, 360.0, 0.9, 0.25]]),
        np_module=np,
        num_classes=1,
        score_threshold=0.01,
    )

    assert topk_inputs is not None
    assert topk_inputs.boxes_xyxy.tolist() == [[240.0, 280.0, 400.0, 360.0]]


def test_yolo11_pose_raw_boxes_are_xywh_and_keypoints_are_task_output() -> None:
    """YOLO11 pose raw box 使用 xywh，pose 主输出保持 keypoints。"""

    instances, keypoint_shape = build_yolo11_pose_postprocess_instances(
        np_module=np,
        prediction_array=np.asarray(
            [[[320.0, 320.0, 160.0, 80.0, 0.9, 320.0, 320.0, 0.95]]],
            dtype=np.float32,
        ),
        labels=("hand",),
        score_threshold=0.01,
        keypoint_confidence_threshold=0.01,
        letterbox_transform=_wide_letterbox_transform(),
        default_kpt_shape=(1, 3),
        nms_threshold=0.7,
        nms_indices_func=_keep_all_nms_indices,
    )

    assert keypoint_shape == (1, 3)
    assert instances[0].bbox_xyxy == (720.0, 420.0, 1200.0, 660.0)
    assert instances[0].keypoints[0].x == 960.0
    assert instances[0].keypoints[0].y == 540.0


def test_yolo26_pose_processed_boxes_are_xyxy_and_keypoints_are_task_output() -> None:
    """YOLO26 pose processed box 使用 xyxy，pose 主输出保持 keypoints。"""

    instances, keypoint_shape = build_yolo26_pose_postprocess_instances(
        np_module=np,
        prediction_array=np.asarray(
            [[[240.0, 280.0, 400.0, 360.0, 0.9, 0.0, 320.0, 320.0, 0.95]]],
            dtype=np.float32,
        ),
        labels=("hand",),
        score_threshold=0.01,
        keypoint_confidence_threshold=0.01,
        letterbox_transform=_wide_letterbox_transform(),
        default_kpt_shape=(1, 3),
        nms_threshold=0.7,
        nms_indices_func=_keep_all_nms_indices,
    )

    assert keypoint_shape == (1, 3)
    assert instances[0].bbox_xyxy == (720.0, 420.0, 1200.0, 660.0)
    assert instances[0].keypoints[0].x == 960.0
    assert instances[0].keypoints[0].y == 540.0


def test_yolo11_obb_uses_xywhr_as_task_output_and_xyxy_as_bounds() -> None:
    """YOLO11 OBB 主输出保持 xywhr，xyxy 只是外接矩形辅助。"""

    instances = build_yolo11_obb_postprocess_instances(
        np_module=np,
        prediction_array=np.asarray(
            [[[320.0, 320.0, 160.0, 80.0, 0.9, 0.0]]],
            dtype=np.float32,
        ),
        labels=("defect",),
        score_threshold=0.01,
        letterbox_transform=_wide_letterbox_transform(),
        nms_threshold=0.7,
        nms_indices_func=_keep_all_nms_indices,
    )

    assert instances[0].bbox_xywhr == (960.0, 540.0, 480.0, 240.0, 0.0)
    assert instances[0].bbox_xyxy == (720.0, 420.0, 1200.0, 660.0)


def test_yolo26_obb_processed_uses_xywhr_as_task_output_and_xyxy_as_bounds() -> None:
    """YOLO26 OBB processed 主输出保持 xywhr，xyxy 只是外接矩形辅助。"""

    instances = build_yolo26_obb_postprocess_instances(
        np_module=np,
        prediction_array=np.asarray(
            [[[320.0, 320.0, 160.0, 80.0, 0.9, 0.0, 0.0]]],
            dtype=np.float32,
        ),
        labels=("defect",),
        score_threshold=0.01,
        letterbox_transform=_wide_letterbox_transform(),
        nms_threshold=0.7,
        nms_indices_func=_keep_all_nms_indices,
    )

    assert instances[0].bbox_xywhr == (960.0, 540.0, 480.0, 240.0, 0.0)
    assert instances[0].bbox_xyxy == (720.0, 420.0, 1200.0, 660.0)
