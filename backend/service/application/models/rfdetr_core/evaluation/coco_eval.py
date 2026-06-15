"""RF-DETR core 评估处理模块：`evaluation.coco_eval`。"""

import contextlib
import copy
import os
from typing import Any

import numpy as np
import pycocotools.mask as mask_util
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval

from backend.service.application.models.rfdetr_core.utilities.distributed import all_gather
from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

logger = get_logger()


def _xyxy_to_xywh(boxes: np.ndarray) -> np.ndarray:
    """执行 `_xyxy_to_xywh`。
    
    参数：
    - `boxes`：传入的 `boxes` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    boxes = boxes.copy()
    boxes[:, 2] -= boxes[:, 0]
    boxes[:, 3] -= boxes[:, 1]
    return boxes


class CocoEvaluator:
    """RF-DETR core 类：`CocoEvaluator`。"""

    def __init__(self, coco_gt: COCO, iou_types: list[str], max_dets: int = 100) -> None:
        assert isinstance(iou_types, (list, tuple))
        coco_gt = copy.deepcopy(coco_gt)
        self.coco_gt = coco_gt
        self.max_dets = max_dets
        self.label2cat: dict[int, int] | None = getattr(coco_gt, "label2cat", None)

        self.iou_types = iou_types
        self.coco_eval: dict[str, COCOeval] = {}
        for iou_type in iou_types:
            self.coco_eval[iou_type] = COCOeval(coco_gt, iouType=iou_type)
            self.coco_eval[iou_type].params.maxDets = [1, 10, max_dets]

        self.img_ids: list[int] = []
        self.eval_imgs: dict[str, list[Any]] = {k: [] for k in iou_types}
        self.cat_ids = set(coco_gt.cats.keys())
        self._prefer_raw_category_ids = False

    def _resolve_category_id(self, label: int, use_raw_category_ids: bool) -> int | None:
        """执行 `_resolve_category_id`。
        
        参数：
        - `label`：传入的 `label` 参数。
        - `use_raw_category_ids`：传入的 `use_raw_category_ids` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if use_raw_category_ids:
            return label if label in self.cat_ids else None
        if self.label2cat is not None and label in self.label2cat:
            return self.label2cat[label]
        if label in self.cat_ids:
            return label
        return None

    def _should_use_raw_category_ids(self, labels: list[int]) -> bool:
        """执行 `_should_use_raw_category_ids`。
        
        参数：
        - `labels`：传入的 `labels` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if self.label2cat is None:
            return True
        if self._prefer_raw_category_ids:
            return True
        uses_raw_ids = list(self.label2cat.keys()) == list(self.label2cat.values())
        if uses_raw_ids:
            self._prefer_raw_category_ids = True
            return True
        return False

    def update(self, predictions: dict[int, Any]) -> None:
        """执行 `update`。
        
        参数：
        - `predictions`：传入的 `predictions` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        img_ids = list(np.unique(list(predictions.keys())))
        self.img_ids.extend(img_ids)

        for iou_type in self.iou_types:
            results = self.prepare(predictions, iou_type)

            with open(os.devnull, "w") as devnull:
                with contextlib.redirect_stdout(devnull):
                    coco_dt = COCO.loadRes(self.coco_gt, results) if results else COCO()
            coco_eval = self.coco_eval[iou_type]

            coco_eval.cocoDt = coco_dt
            coco_eval.params.imgIds = list(img_ids)
            img_ids, eval_imgs = evaluate(coco_eval)

            self.eval_imgs[iou_type].append(eval_imgs)

    def synchronize_between_processes(self) -> None:
        """执行 `synchronize_between_processes`。
        
        返回：
        - 当前函数的执行结果。
        """
        for iou_type in self.iou_types:
            self.eval_imgs[iou_type] = np.concatenate(self.eval_imgs[iou_type], 2)
            create_common_coco_eval(self.coco_eval[iou_type], self.img_ids, self.eval_imgs[iou_type])

    def accumulate(self) -> None:
        """执行 `accumulate`。
        
        返回：
        - 当前函数的执行结果。
        """
        for coco_eval in self.coco_eval.values():
            coco_eval.accumulate()

    def summarize(self) -> None:
        """执行 `summarize`。
        
        返回：
        - 当前函数的执行结果。
        """
        for iou_type, coco_eval in self.coco_eval.items():
            logger.info("IoU metric: {}".format(iou_type))
            patched_pycocotools_summarize(coco_eval)

    def prepare(self, predictions: dict[int, Any], iou_type: str) -> list[dict[str, Any]]:
        """执行 `prepare`。
        
        参数：
        - `predictions`：传入的 `predictions` 参数。
        - `iou_type`：传入的 `iou_type` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if iou_type == "bbox":
            return self.prepare_for_coco_detection(predictions)
        elif iou_type == "segm":
            return self.prepare_for_coco_segmentation(predictions)
        elif iou_type == "keypoints":
            return self.prepare_for_coco_keypoint(predictions)
        else:
            raise ValueError("Unknown iou type {}".format(iou_type))

    def prepare_for_coco_detection(self, predictions: dict[int, Any]) -> list[dict[str, Any]]:
        """执行 `prepare_for_coco_detection`。
        
        参数：
        - `predictions`：传入的 `predictions` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        coco_results = []
        for original_id, prediction in predictions.items():
            if len(prediction) == 0:
                continue

            boxes = prediction["boxes"]
            boxes = _xyxy_to_xywh(boxes.cpu().numpy()).tolist()
            scores = prediction["scores"].tolist()
            labels = prediction["labels"].tolist()
            use_raw_category_ids = self._should_use_raw_category_ids(labels)
            for k, box in enumerate(boxes):
                category_id = self._resolve_category_id(labels[k], use_raw_category_ids)
                if category_id is None:
                    continue
                coco_results.append(
                    {
                        "image_id": original_id,
                        "category_id": category_id,
                        "bbox": box,
                        "score": scores[k],
                    }
                )
        return coco_results

    def prepare_for_coco_segmentation(self, predictions: dict[int, Any]) -> list[dict[str, Any]]:
        """执行 `prepare_for_coco_segmentation`。
        
        参数：
        - `predictions`：传入的 `predictions` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        coco_results = []
        for original_id, prediction in predictions.items():
            if len(prediction) == 0:
                continue

            scores = prediction["scores"]
            labels = prediction["labels"]
            masks = prediction["masks"]

            masks = masks > 0.5

            scores = prediction["scores"].tolist()
            labels = prediction["labels"].tolist()
            use_raw_category_ids = self._should_use_raw_category_ids(labels)

            rles = [
                mask_util.encode(np.array(mask.cpu()[0, :, :, np.newaxis], dtype=np.uint8, order="F"))[0]
                for mask in masks
            ]
            for rle in rles:
                rle["counts"] = rle["counts"].decode("utf-8")

            for k, rle in enumerate(rles):
                category_id = self._resolve_category_id(labels[k], use_raw_category_ids)
                if category_id is None:
                    continue
                coco_results.append(
                    {
                        "image_id": original_id,
                        "category_id": category_id,
                        "segmentation": rle,
                        "score": scores[k],
                    }
                )
        return coco_results

    def prepare_for_coco_keypoint(self, predictions: dict[int, Any]) -> list[dict[str, Any]]:
        """执行 `prepare_for_coco_keypoint`。
        
        参数：
        - `predictions`：传入的 `predictions` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        coco_results = []
        for original_id, prediction in predictions.items():
            if len(prediction) == 0:
                continue

            boxes = prediction["boxes"]
            boxes = _xyxy_to_xywh(boxes.cpu().numpy()).tolist()
            scores = prediction["scores"].tolist()
            labels = prediction["labels"].tolist()
            keypoints = prediction["keypoints"]
            keypoints = keypoints.flatten(start_dim=1).tolist()
            use_raw_category_ids = self._should_use_raw_category_ids(labels)
            for k, keypoint in enumerate(keypoints):
                category_id = self._resolve_category_id(labels[k], use_raw_category_ids)
                if category_id is None:
                    continue
                coco_results.append(
                    {
                        "image_id": original_id,
                        "category_id": category_id,
                        "keypoints": keypoint,
                        "score": scores[k],
                    }
                )
        return coco_results


def merge(img_ids: list[int], eval_imgs: Any) -> tuple[np.ndarray, np.ndarray]:
    """执行 `merge`。
    
    参数：
    - `img_ids`：传入的 `img_ids` 参数。
    - `eval_imgs`：传入的 `eval_imgs` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    all_img_ids = all_gather(img_ids)
    all_eval_imgs = all_gather(eval_imgs)

    merged_img_ids: list[int] = []
    for p in all_img_ids:
        merged_img_ids.extend(p)

    merged_eval_imgs = []
    for p in all_eval_imgs:
        merged_eval_imgs.append(p)

    merged_img_ids_arr = np.array(merged_img_ids)
    merged_eval_imgs_arr = np.concatenate(merged_eval_imgs, 2)

    merged_img_ids_arr, idx = np.unique(merged_img_ids_arr, return_index=True)
    merged_eval_imgs_arr = merged_eval_imgs_arr[..., idx]

    return merged_img_ids_arr, merged_eval_imgs_arr


def create_common_coco_eval(coco_eval: COCOeval, img_ids: list[int], eval_imgs: Any) -> None:
    """执行 `create_common_coco_eval`。
    
    参数：
    - `coco_eval`：传入的 `coco_eval` 参数。
    - `img_ids`：传入的 `img_ids` 参数。
    - `eval_imgs`：传入的 `eval_imgs` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    img_ids_arr, eval_imgs = merge(img_ids, eval_imgs)
    img_ids_list = list(img_ids_arr)
    eval_imgs_list = list(eval_imgs.flatten())

    coco_eval.evalImgs = eval_imgs_list
    coco_eval.params.imgIds = img_ids_list
    coco_eval._paramsEval = copy.deepcopy(coco_eval.params)


#################################################################
#################################################################
def evaluate(self: COCOeval) -> tuple[list[int], np.ndarray]:
    """执行 `evaluate`。
    
    返回：
    - 当前函数的执行结果。
    """
    p = self.params
    if p.useSegm is not None:
        p.iouType = "segm" if p.useSegm == 1 else "bbox"
        logger.warning("useSegm (deprecated) is not None. Running {} evaluation".format(p.iouType))
    p.imgIds = list(np.unique(p.imgIds))
    if p.useCats:
        p.catIds = list(np.unique(p.catIds))
    p.maxDets = sorted(p.maxDets)
    self.params = p

    self._prepare()
    category_ids = p.catIds if p.useCats else [-1]

    if p.iouType == "segm" or p.iouType == "bbox":
        compute_iou = self.computeIoU
    elif p.iouType == "keypoints":
        compute_iou = self.computeOks
    self.ious = {(imgId, catId): compute_iou(imgId, catId) for imgId in p.imgIds for catId in category_ids}

    evaluate_image = self.evaluateImg
    max_det = p.maxDets[-1]
    eval_images = [
        evaluate_image(imgId, catId, areaRng, max_det)
        for catId in category_ids
        for areaRng in p.areaRng
        for imgId in p.imgIds
    ]
    eval_images = np.asarray(eval_images).reshape(len(category_ids), len(p.areaRng), len(p.imgIds))
    self._paramsEval = copy.deepcopy(self.params)
    return p.imgIds, eval_images


#################################################################
#################################################################
def patched_pycocotools_summarize(self: COCOeval) -> None:
    """执行 `patched_pycocotools_summarize`。
    
    返回：
    - 当前函数的执行结果。
    """

    def _summarize(ap: int = 1, iou_thr: float | None = None, area_rng: str = "all", max_dets: int = 100) -> float:
        p = self.params
        log_template = " {:<18} {} @[ IoU={:<9} | area={:>6s} | maxDets={:>3d} ] = {:0.3f}"
        title_str = "Average Precision" if ap == 1 else "Average Recall"
        type_str = "(AP)" if ap == 1 else "(AR)"
        iou_str = (
            "{:0.2f}:{:0.2f}".format(p.iouThrs[0], p.iouThrs[-1]) if iou_thr is None else "{:0.2f}".format(iou_thr)
        )

        aind = [i for i, aRng in enumerate(p.areaRngLbl) if aRng == area_rng]
        mind = [i for i, mDet in enumerate(p.maxDets) if mDet == max_dets]
        if ap == 1:
            s = self.eval["precision"]
            if iou_thr is not None:
                t = np.where(iou_thr == p.iouThrs)[0]
                s = s[t]
            s = s[:, :, :, aind, mind]
        else:
            s = self.eval["recall"]
            if iou_thr is not None:
                t = np.where(iou_thr == p.iouThrs)[0]
                s = s[t]
            s = s[:, :, aind, mind]
        mean_s = -1 if len(s[s > -1]) == 0 else float(np.mean(s[s > -1]))
        logger.info(log_template.format(title_str, type_str, iou_str, area_rng, max_dets, mean_s))
        return mean_s

    def _summarizeDets() -> np.ndarray:  # noqa: N802
        stats = np.zeros((12,))
        stats[0] = _summarize(1, max_dets=self.params.maxDets[2])
        stats[1] = _summarize(1, iou_thr=0.5, max_dets=self.params.maxDets[2])
        stats[2] = _summarize(1, iou_thr=0.75, max_dets=self.params.maxDets[2])
        stats[3] = _summarize(1, area_rng="small", max_dets=self.params.maxDets[2])
        stats[4] = _summarize(1, area_rng="medium", max_dets=self.params.maxDets[2])
        stats[5] = _summarize(1, area_rng="large", max_dets=self.params.maxDets[2])
        stats[6] = _summarize(0, max_dets=self.params.maxDets[0])
        stats[7] = _summarize(0, max_dets=self.params.maxDets[1])
        stats[8] = _summarize(0, max_dets=self.params.maxDets[2])
        stats[9] = _summarize(0, area_rng="small", max_dets=self.params.maxDets[2])
        stats[10] = _summarize(0, area_rng="medium", max_dets=self.params.maxDets[2])
        stats[11] = _summarize(0, area_rng="large", max_dets=self.params.maxDets[2])
        return stats

    def _summarizeKps() -> np.ndarray:  # noqa: N802
        stats = np.zeros((10,))
        stats[0] = _summarize(1, max_dets=20)
        stats[1] = _summarize(1, max_dets=20, iou_thr=0.5)
        stats[2] = _summarize(1, max_dets=20, iou_thr=0.75)
        stats[3] = _summarize(1, max_dets=20, area_rng="medium")
        stats[4] = _summarize(1, max_dets=20, area_rng="large")
        stats[5] = _summarize(0, max_dets=20)
        stats[6] = _summarize(0, max_dets=20, iou_thr=0.5)
        stats[7] = _summarize(0, max_dets=20, iou_thr=0.75)
        stats[8] = _summarize(0, max_dets=20, area_rng="medium")
        stats[9] = _summarize(0, max_dets=20, area_rng="large")
        return stats

    if not self.eval:
        raise Exception("Please run accumulate() first")
    iou_type = self.params.iouType
    if iou_type == "segm" or iou_type == "bbox":
        summarize = _summarizeDets
    elif iou_type == "keypoints":
        summarize = _summarizeKps
    self.stats = summarize()


