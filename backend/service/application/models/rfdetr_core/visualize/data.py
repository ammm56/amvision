from pathlib import Path

import numpy as np
from PIL import Image

from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

logger = get_logger()


def save_gt_predictions_visualization(
    scenario_name: str,
    image_width: int,
    image_height: int,
    gt_boxes: list[list[float]],
    gt_class_ids: list[int],
    pred_boxes: list[list[float]],
    pred_class_ids: list[int],
    pred_confidences: list[float],
    pred_ious: list[float | None],
    save_dir: Path,
) -> None:
    """执行 `save_gt_predictions_visualization`。
    
    参数：
    - `scenario_name`：传入的 `scenario_name` 参数。
    - `image_width`：传入的 `image_width` 参数。
    - `image_height`：传入的 `image_height` 参数。
    - `gt_boxes`：传入的 `gt_boxes` 参数。
    - `gt_class_ids`：传入的 `gt_class_ids` 参数。
    - `pred_boxes`：传入的 `pred_boxes` 参数。
    - `pred_class_ids`：传入的 `pred_class_ids` 参数。
    - `pred_confidences`：传入的 `pred_confidences` 参数。
    - `pred_ious`：传入的 `pred_ious` 参数。
    - `save_dir`：传入的 `save_dir` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from backend.service.application.models.rfdetr_core import supervision_compat as sv

    save_dir.mkdir(exist_ok=True)

    top_padding = 60
    image = np.zeros((image_height + top_padding, image_width, 3), dtype=np.uint8)
    scene: Image.Image = Image.fromarray(image)

    gt_boxes_offset = [[x, y + top_padding, w, h] for x, y, w, h in gt_boxes]
    pred_boxes_offset = [[x, y + top_padding, w, h] for x, y, w, h in pred_boxes]

    gt_xyxy = sv.xywh_to_xyxy(np.array(gt_boxes_offset))
    pred_xyxy = sv.xywh_to_xyxy(np.array(pred_boxes_offset))

    gt_detections = None
    pred_detections = None

    if len(gt_xyxy) > 0:
        gt_detections = sv.Detections(
            xyxy=gt_xyxy,
            class_id=np.array(gt_class_ids),
        )

    if len(pred_xyxy) > 0:
        pred_detections = sv.Detections(
            xyxy=pred_xyxy,
            class_id=np.array(pred_class_ids),
            confidence=np.array(pred_confidences),
        )

    gt_colors = sv.ColorPalette(
        [
            sv.Color(128, 128, 128),
            sv.Color(0, 255, 100),
            sv.Color(0, 200, 255),
        ]
    )
    pred_colors = sv.ColorPalette(
        [
            sv.Color(128, 128, 128),
            sv.Color(255, 100, 50),
            sv.Color(255, 50, 200),
        ]
    )

    gt_box_annotator = sv.BoxAnnotator(color=gt_colors, thickness=3, color_lookup=sv.ColorLookup.CLASS)
    pred_box_annotator = sv.BoxAnnotator(color=pred_colors, thickness=3, color_lookup=sv.ColorLookup.CLASS)

    gt_label_annotator = sv.LabelAnnotator(
        color=gt_colors,
        text_color=sv.Color.BLACK,
        text_scale=0.5,
        text_padding=3,
        text_position=sv.Position.TOP_LEFT,
        color_lookup=sv.ColorLookup.CLASS,
    )
    pred_label_annotator = sv.LabelAnnotator(
        color=pred_colors,
        text_color=sv.Color.BLACK,
        text_scale=0.5,
        text_padding=3,
        text_position=sv.Position.TOP_RIGHT,
        color_lookup=sv.ColorLookup.CLASS,
    )

    gt_labels = [f"c{class_id}" for class_id in gt_class_ids]

    pred_labels = []
    for class_id, conf, iou in zip(pred_class_ids, pred_confidences, pred_ious):
        if iou is not None:
            pred_labels.append(f"c{class_id}\nconf={conf:.3f}\niou={iou:.3f}")
        else:
            pred_labels.append(f"c{class_id}\nconf={conf:.3f}")

    if gt_detections is not None:
        scene = gt_box_annotator.annotate(scene=scene, detections=gt_detections)
        scene = gt_label_annotator.annotate(scene=scene, detections=gt_detections, labels=gt_labels)
    if pred_detections is not None:
        scene = pred_box_annotator.annotate(scene=scene, detections=pred_detections)
        scene = pred_label_annotator.annotate(scene=scene, detections=pred_detections, labels=pred_labels)

    scene.save(save_dir / f"{scenario_name}.png")
    logger.info(f"Saved visualization to {save_dir}/{scenario_name}.png")


