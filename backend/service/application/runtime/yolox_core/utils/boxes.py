"""项目内 YOLOX 框处理与后处理工具。"""

from __future__ import annotations

import torch
import torchvision


def postprocess(
    prediction: torch.Tensor,
    num_classes: int,
    conf_thre: float = 0.7,
    nms_thre: float = 0.45,
    class_agnostic: bool = False,
):
    """按原 YOLOX 规则执行后处理与 NMS。"""

    box_corner = prediction.new(prediction.shape)
    box_corner[:, :, 0] = prediction[:, :, 0] - prediction[:, :, 2] / 2
    box_corner[:, :, 1] = prediction[:, :, 1] - prediction[:, :, 3] / 2
    box_corner[:, :, 2] = prediction[:, :, 0] + prediction[:, :, 2] / 2
    box_corner[:, :, 3] = prediction[:, :, 1] + prediction[:, :, 3] / 2
    prediction[:, :, :4] = box_corner[:, :, :4]

    outputs = [None for _ in range(len(prediction))]
    for image_index, image_pred in enumerate(prediction):
        if not image_pred.size(0):
            continue

        class_conf, class_pred = torch.max(image_pred[:, 5 : 5 + num_classes], 1, keepdim=True)
        conf_mask = (image_pred[:, 4] * class_conf.squeeze() >= conf_thre).squeeze()
        detections = torch.cat((image_pred[:, :5], class_conf, class_pred.float()), 1)
        detections = detections[conf_mask]
        if not detections.size(0):
            continue

        if class_agnostic:
            keep_index = torchvision.ops.nms(
                detections[:, :4],
                detections[:, 4] * detections[:, 5],
                nms_thre,
            )
        else:
            keep_index = torchvision.ops.batched_nms(
                detections[:, :4],
                detections[:, 4] * detections[:, 5],
                detections[:, 6],
                nms_thre,
            )

        detections = detections[keep_index]
        if outputs[image_index] is None:
            outputs[image_index] = detections
        else:
            outputs[image_index] = torch.cat((outputs[image_index], detections))
    return outputs


def bboxes_iou(bboxes_a: torch.Tensor, bboxes_b: torch.Tensor, xyxy: bool = True) -> torch.Tensor:
    """计算两组边界框之间的 IoU 矩阵。"""

    if bboxes_a.shape[1] != 4 or bboxes_b.shape[1] != 4:
        raise IndexError("IoU 输入边界框维度必须是 4")

    if xyxy:
        top_left = torch.max(bboxes_a[:, None, :2], bboxes_b[:, :2])
        bottom_right = torch.min(bboxes_a[:, None, 2:], bboxes_b[:, 2:])
        area_a = torch.prod(bboxes_a[:, 2:] - bboxes_a[:, :2], 1)
        area_b = torch.prod(bboxes_b[:, 2:] - bboxes_b[:, :2], 1)
    else:
        top_left = torch.max(
            bboxes_a[:, None, :2] - bboxes_a[:, None, 2:] / 2,
            bboxes_b[:, :2] - bboxes_b[:, 2:] / 2,
        )
        bottom_right = torch.min(
            bboxes_a[:, None, :2] + bboxes_a[:, None, 2:] / 2,
            bboxes_b[:, :2] + bboxes_b[:, 2:] / 2,
        )
        area_a = torch.prod(bboxes_a[:, 2:], 1)
        area_b = torch.prod(bboxes_b[:, 2:], 1)

    valid_mask = (top_left < bottom_right).type(top_left.type()).prod(dim=2)
    area_intersection = torch.prod(bottom_right - top_left, 2) * valid_mask
    return area_intersection / (area_a[:, None] + area_b - area_intersection)


def xyxy2cxcywh(bboxes: torch.Tensor | object):
    """把 xyxy 格式框原地转换为 cxcywh。"""

    bboxes[:, 2] = bboxes[:, 2] - bboxes[:, 0]
    bboxes[:, 3] = bboxes[:, 3] - bboxes[:, 1]
    bboxes[:, 0] = bboxes[:, 0] + bboxes[:, 2] * 0.5
    bboxes[:, 1] = bboxes[:, 1] + bboxes[:, 3] * 0.5
    return bboxes


def cxcywh2xyxy(bboxes: torch.Tensor | object):
    """把 cxcywh 格式框原地转换为 xyxy。"""

    original_width = bboxes[:, 2].clone() if hasattr(bboxes[:, 2], "clone") else bboxes[:, 2].copy()
    original_height = bboxes[:, 3].clone() if hasattr(bboxes[:, 3], "clone") else bboxes[:, 3].copy()
    bboxes[:, 0] = bboxes[:, 0] - original_width * 0.5
    bboxes[:, 1] = bboxes[:, 1] - original_height * 0.5
    bboxes[:, 2] = bboxes[:, 0] + original_width
    bboxes[:, 3] = bboxes[:, 1] + original_height
    return bboxes