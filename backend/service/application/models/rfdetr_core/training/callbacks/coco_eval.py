"""RF-DETR core 训练处理模块：`training.callbacks.coco_eval`。"""

from typing import Any

import numpy as np
import torch
import torch.nn.functional as F  # noqa: N812
from pytorch_lightning import Callback
from torchmetrics.detection import MeanAveragePrecision

from backend.service.application.models.rfdetr_core.evaluation.f1_sweep import sweep_confidence_thresholds
from backend.service.application.models.rfdetr_core.evaluation.matching import (
    build_matching_data,
    distributed_merge_matching_data,
    init_matching_accumulator,
    merge_matching_data,
)
from backend.service.application.models.rfdetr_core.utilities.box_ops import box_cxcywh_to_xyxy


class COCOEvalCallback(Callback):
    """RF-DETR core 类：`COCOEvalCallback`。"""

    def __init__(
        self,
        max_dets: int = 500,
        segmentation: bool = False,
        eval_interval: int = 1,
        log_per_class_metrics: bool = True,
    ) -> None:
        super().__init__()
        self._max_dets = max_dets
        self._segmentation = segmentation
        self._eval_interval = max(1, int(eval_interval))
        self._log_per_class_metrics = bool(log_per_class_metrics)
        self._class_names: list[str] = []
        self._cat_id_to_name: dict[int, str] = {}
        self._f1_local: dict[int, dict[str, Any]] = init_matching_accumulator()

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def setup(self, trainer: Any, pl_module: Any, stage: str) -> None:
        """执行 `setup`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        - `stage`：传入的 `stage` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        iou_type: Any = ["bbox", "segm"] if self._segmentation else "bbox"
        kwargs: dict[str, Any] = dict(
            class_metrics=True,
            max_detection_thresholds=[1, 10, self._max_dets],
        )
        self.map_metric = MeanAveragePrecision(iou_type=iou_type, **kwargs)
        self.map_metric_ema: Any = None

    def on_fit_start(self, trainer: Any, pl_module: Any) -> None:
        """执行 `on_fit_start`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        dm = trainer.datamodule
        if dm is None:
            return
        if hasattr(dm, "class_names"):
            self._class_names = dm.class_names or []
        for attr in ("_dataset_train", "_dataset_val"):
            dataset = getattr(dm, attr, None)
            if dataset is None:
                continue
            coco = getattr(dataset, "coco", None)
            if coco is not None and hasattr(coco, "cats"):
                if hasattr(coco, "label2cat"):
                    self._cat_id_to_name = {
                        label: coco.cats[cat_id]["name"] for label, cat_id in coco.label2cat.items()
                    }
                else:
                    self._cat_id_to_name = {k: v["name"] for k, v in coco.cats.items()}
                return
        self._cat_id_to_name = {i: name for i, name in enumerate(self._class_names)}

    def on_validation_batch_end(
        self,
        trainer: Any,
        pl_module: Any,
        outputs: dict[str, Any],
        batch: Any,
        batch_idx: int,
    ) -> None:
        """执行 `on_validation_batch_end`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        - `outputs`：传入的 `outputs` 参数。
        - `batch`：传入的 `batch` 参数。
        - `batch_idx`：传入的 `batch_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        preds: list[dict[str, torch.Tensor]] = self._convert_preds(outputs["results"])
        targets = self._convert_targets(outputs["targets"])

        self.map_metric.update(preds, targets)

        iou_type = "segm" if self._segmentation else "bbox"
        batch_matching = build_matching_data(preds, targets, iou_threshold=0.5, iou_type=iou_type)
        merge_matching_data(self._f1_local, batch_matching)

        ema_cb = self._get_ema_callback(trainer)
        if ema_cb is not None and ema_cb._average_model is not None:
            if self.map_metric_ema is None:
                ema_iou_type: Any = ["bbox", "segm"] if self._segmentation else "bbox"
                self.map_metric_ema = MeanAveragePrecision(
                    iou_type=ema_iou_type,
                    class_metrics=True,
                    max_detection_thresholds=[1, 10, self._max_dets],
                ).to(pl_module.device)
            samples, _ = batch
            orig_sizes = torch.stack([t["orig_size"] for t in outputs["targets"]]).to(pl_module.device)
            ema_underlying = ema_cb._average_model.module.model
            with torch.no_grad():
                ema_underlying.eval()
                ema_outputs = ema_underlying(samples)
                ema_results = pl_module.postprocess(ema_outputs, orig_sizes)
            ema_preds = self._convert_preds(ema_results)
            self.map_metric_ema.update(ema_preds, targets)

    def on_validation_epoch_end(self, trainer: Any, pl_module: Any) -> None:
        """执行 `on_validation_epoch_end`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if self._eval_interval > 1:
            current_epoch = int(getattr(trainer, "current_epoch", 0)) + 1
            max_epochs = getattr(trainer, "max_epochs", None)
            is_last_epoch = isinstance(max_epochs, int) and max_epochs > 0 and current_epoch >= max_epochs
            if current_epoch % self._eval_interval != 0 and not is_last_epoch:
                self.map_metric.reset()
                if self.map_metric_ema is not None:
                    self.map_metric_ema.reset()
                self._f1_local = init_matching_accumulator()
                return
        self._compute_and_log(trainer, pl_module, "val")

    def on_test_batch_end(
        self,
        trainer: Any,
        pl_module: Any,
        outputs: dict[str, Any],
        batch: Any,
        batch_idx: int,
        dataloader_idx: int = 0,
    ) -> None:
        """执行 `on_test_batch_end`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        - `outputs`：传入的 `outputs` 参数。
        - `batch`：传入的 `batch` 参数。
        - `batch_idx`：传入的 `batch_idx` 参数。
        - `dataloader_idx`：传入的 `dataloader_idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        preds: list[dict[str, torch.Tensor]] = self._convert_preds(outputs["results"])
        targets = self._convert_targets(outputs["targets"])

        self.map_metric.update(preds, targets)

        iou_type = "segm" if self._segmentation else "bbox"
        batch_matching = build_matching_data(preds, targets, iou_threshold=0.5, iou_type=iou_type)
        merge_matching_data(self._f1_local, batch_matching)

    def on_test_epoch_end(self, trainer: Any, pl_module: Any) -> None:
        """执行 `on_test_epoch_end`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        self._compute_and_log(trainer, pl_module, "test")

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def _compute_and_log(self, trainer: Any, pl_module: Any, split: str) -> None:
        """执行 `_compute_and_log`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        - `split`：传入的 `split` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        metrics = self.map_metric.compute()

        pfx = "bbox_" if self._segmentation else ""
        mar_key = f"{pfx}mar_{self._max_dets}"

        overall: dict[str, float] = {
            "mAP 50:95": float(metrics[f"{pfx}map"]),
            "mAP 50": float(metrics[f"{pfx}map_50"]),
            "mAP 75": float(metrics[f"{pfx}map_75"]),
            f"mAR @{self._max_dets}": float(metrics[mar_key]),
        }

        pl_module.log(f"{split}/mAP_50_95", metrics[f"{pfx}map"], prog_bar=True)
        pl_module.log(f"{split}/mAP_50", metrics[f"{pfx}map_50"], prog_bar=True)
        pl_module.log(f"{split}/mAP_75", metrics[f"{pfx}map_75"])
        pl_module.log(f"{split}/mAR", metrics[mar_key])

        trainer.callback_metrics[f"{split}/mAP_50_95"] = metrics[f"{pfx}map"].detach().cpu()
        trainer.callback_metrics[f"{split}/mAP_50"] = metrics[f"{pfx}map_50"].detach().cpu()
        trainer.callback_metrics[f"{split}/mAP_75"] = metrics[f"{pfx}map_75"].detach().cpu()
        trainer.callback_metrics[f"{split}/mAR"] = metrics[mar_key].detach().cpu()

        if self.map_metric_ema is not None:
            ema_metrics = self.map_metric_ema.compute()
            pl_module.log(f"{split}/ema_mAP_50_95", ema_metrics[f"{pfx}map"], prog_bar=True)
            pl_module.log(f"{split}/ema_mAP_50", ema_metrics[f"{pfx}map_50"])
            pl_module.log(f"{split}/ema_mAR", ema_metrics[mar_key])
            trainer.callback_metrics[f"{split}/ema_mAP_50_95"] = ema_metrics[f"{pfx}map"].detach().cpu()
            trainer.callback_metrics[f"{split}/ema_mAP_50"] = ema_metrics[f"{pfx}map_50"].detach().cpu()
            trainer.callback_metrics[f"{split}/ema_mAR"] = ema_metrics[mar_key].detach().cpu()
            if self._segmentation:
                pl_module.log(f"{split}/ema_segm_mAP_50_95", ema_metrics["segm_map"])
                pl_module.log(f"{split}/ema_segm_mAP_50", ema_metrics["segm_map_50"])
                trainer.callback_metrics[f"{split}/ema_segm_mAP_50_95"] = ema_metrics["segm_map"].detach().cpu()
                trainer.callback_metrics[f"{split}/ema_segm_mAP_50"] = ema_metrics["segm_map_50"].detach().cpu()
            self.map_metric_ema.reset()

        if self._segmentation:
            overall["segm mAP 50:95"] = float(metrics["segm_map"])
            overall["segm mAP 50"] = float(metrics["segm_map_50"])
            pl_module.log(f"{split}/segm_mAP_50_95", metrics["segm_map"])
            pl_module.log(f"{split}/segm_mAP_50", metrics["segm_map_50"])
            trainer.callback_metrics[f"{split}/segm_mAP_50_95"] = metrics["segm_map"].detach().cpu()
            trainer.callback_metrics[f"{split}/segm_mAP_50"] = metrics["segm_map_50"].detach().cpu()

        merged = distributed_merge_matching_data(self._f1_local)
        f1_by_cid: dict[int, dict[str, float]] = {}
        if merged:
            sorted_ids = sorted(merged.keys())
            per_class_list = [merged[cid] for cid in sorted_ids]
            classes_with_gt = [i for i, cid in enumerate(sorted_ids) if merged[cid]["total_gt"] > 0]
            f1_results = sweep_confidence_thresholds(per_class_list, np.linspace(0, 1, 101), classes_with_gt)
            best = max(f1_results, key=lambda x: x["macro_f1"])
            overall["F1"] = float(best["macro_f1"])
            overall["Precision"] = float(best["macro_precision"])
            overall["Recall"] = float(best["macro_recall"])
            pl_module.log(f"{split}/F1", float(best["macro_f1"]), prog_bar=True)
            pl_module.log(f"{split}/precision", float(best["macro_precision"]))
            pl_module.log(f"{split}/recall", float(best["macro_recall"]))
            trainer.callback_metrics[f"{split}/F1"] = torch.tensor(float(best["macro_f1"]))
            trainer.callback_metrics[f"{split}/precision"] = torch.tensor(float(best["macro_precision"]))
            trainer.callback_metrics[f"{split}/recall"] = torch.tensor(float(best["macro_recall"]))
            for k, cid in enumerate(sorted_ids):
                f1_by_cid[cid] = {
                    "f1": float(best["per_class_f1"][k]),
                    "precision": float(best["per_class_prec"][k]),
                    "recall": float(best["per_class_rec"][k]),
                }
        else:
            overall["F1"] = 0.0
            overall["Precision"] = 0.0
            overall["Recall"] = 0.0
            pl_module.log(f"{split}/F1", 0.0, prog_bar=True)
            pl_module.log(f"{split}/precision", 0.0)
            pl_module.log(f"{split}/recall", 0.0)
            trainer.callback_metrics[f"{split}/F1"] = torch.tensor(0.0)
            trainer.callback_metrics[f"{split}/precision"] = torch.tensor(0.0)
            trainer.callback_metrics[f"{split}/recall"] = torch.tensor(0.0)

        if "classes" in metrics and metrics["classes"].ndim == 0:
            metrics = dict(metrics)
            metrics["classes"] = metrics["classes"].unsqueeze(0)
            for k in list(metrics):
                if isinstance(metrics[k], torch.Tensor) and metrics[k].ndim == 0 and "per_class" in k:
                    metrics[k] = metrics[k].unsqueeze(0)

        ar_pc_key = f"{pfx}mar_{self._max_dets}_per_class"
        ar_by_cid: dict[int, float] = {}
        if ar_pc_key in metrics and "classes" in metrics:
            for class_id, ar in zip(metrics["classes"], metrics[ar_pc_key]):
                ar_by_cid[int(class_id)] = float(ar)

        per_class = self._build_per_class_rows(
            metrics=metrics, pfx=pfx, split=split, pl_module=pl_module, ar_by_cid=ar_by_cid, f1_by_cid=f1_by_cid
        )

        self._print_metrics_tables(trainer, split, overall, per_class)
        self.map_metric.reset()
        self._f1_local = init_matching_accumulator()

    def _get_ema_callback(self, trainer: Any) -> Any:
        """执行 `_get_ema_callback`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        for callback in getattr(trainer, "callbacks", []):
            if callable(getattr(callback, "get_ema_model_state_dict", None)):
                return callback
        return None

    def _build_per_class_rows(
        self,
        metrics: dict[str, Any],
        pfx: str,
        split: str,
        pl_module: Any,
        ar_by_cid: dict[int, float],
        f1_by_cid: dict[int, dict[str, float]],
    ) -> list[dict[str, Any]]:
        """执行 `_build_per_class_rows`。
        
        参数：
        - `metrics`：传入的 `metrics` 参数。
        - `pfx`：传入的 `pfx` 参数。
        - `split`：传入的 `split` 参数。
        - `pl_module`：传入的 `pl_module` 参数。
        - `ar_by_cid`：传入的 `ar_by_cid` 参数。
        - `f1_by_cid`：传入的 `f1_by_cid` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        per_class: list[dict[str, Any]] = []
        if not self._log_per_class_metrics:
            return per_class

        pc_key = f"{pfx}map_per_class"
        if pc_key not in metrics or "classes" not in metrics:
            return per_class

        for class_id, ap in zip(metrics["classes"], metrics[pc_key]):
            ap_f = float(ap)
            ar_f = ar_by_cid.get(int(class_id), float("nan"))
            if ap_f < 0 and (ar_f != ar_f or ar_f < 0):
                continue
            idx = int(class_id)
            name = self._cat_id_to_name.get(idx, str(idx))
            pl_module.log(f"{split}/AP/{name}", ap)
            row: dict[str, Any] = {"name": name, "ap": ap_f, "ar": ar_f}
            row.update(f1_by_cid.get(idx, {"f1": float("nan"), "precision": float("nan"), "recall": float("nan")}))
            per_class.append(row)
        return per_class

    def _print_metrics_tables(
        self,
        trainer: Any,
        split: str,
        overall: dict[str, float],
        per_class: list[dict[str, Any]],
    ) -> None:
        """执行 `_print_metrics_tables`。
        
        参数：
        - `trainer`：传入的 `trainer` 参数。
        - `split`：传入的 `split` 参数。
        - `overall`：传入的 `overall` 参数。
        - `per_class`：传入的 `per_class` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if not getattr(trainer, "is_global_zero", True):
            return
        try:
            from rich.console import Console
            from rich.table import Table
        except ImportError:
            return

        def _fmt(v: float) -> str:
            if v != v or v < 0:
                return "—"
            return f"{v:.4f}"

        console = Console(force_terminal=True)
        title_pfx = split.capitalize()

        def _render_all() -> None:
            console.print(self._render_overall_merged(title_pfx, overall))

            if per_class:
                t2 = Table(
                    title=f"{title_pfx} — Per-class Metrics",
                    title_style="bold cyan",
                    show_header=True,
                    header_style="bold cyan",
                )
                t2.add_column("Class", style="dim", no_wrap=True)
                t2.add_column("AP 50:95", justify="right")
                t2.add_column("AR", justify="right")
                t2.add_column("F1", justify="right")
                t2.add_column("Precision", justify="right")
                t2.add_column("Recall", justify="right")
                for row in per_class:
                    t2.add_row(
                        row["name"],
                        _fmt(row["ap"]),
                        _fmt(row["ar"]),
                        _fmt(row["f1"]),
                        _fmt(row["precision"]),
                        _fmt(row["recall"]),
                    )
                console.print(t2)

        _render_all()

    def _render_overall_merged(self, title_pfx: str, overall: dict[str, float]) -> str:
        """执行 `_render_overall_merged`。
        
        参数：
        - `title_pfx`：传入的 `title_pfx` 参数。
        - `overall`：传入的 `overall` 参数。
        
        返回：
        - 当前函数的执行结果。
        """

        def _fmt(v: float) -> str:
            if v != v or v < 0:
                return "—"
            return f"{v:.4f}"

        mar_lbl = f"@{self._max_dets}"
        mar_key = f"mAR @{self._max_dets}"

        groups: list[tuple[str, list[tuple[str, str]]]] = [
            (
                "mAP",
                [
                    ("50:95", _fmt(overall["mAP 50:95"])),
                    ("50", _fmt(overall["mAP 50"])),
                    ("75", _fmt(overall["mAP 75"])),
                ],
            ),
            ("mAR", [(mar_lbl, _fmt(overall[mar_key]))]),
            (
                "F1 sweep",
                [
                    ("F1", _fmt(overall["F1"])),
                    ("Prec", _fmt(overall["Precision"])),
                    ("Recall", _fmt(overall["Recall"])),
                ],
            ),
        ]
        if "segm mAP 50:95" in overall:
            groups.append(
                (
                    "segm mAP",
                    [
                        ("50:95", _fmt(overall["segm mAP 50:95"])),
                        ("50", _fmt(overall["segm mAP 50"])),
                    ],
                )
            )

        flat: list[tuple[str, str]] = [(s, v) for _, cols in groups for s, v in cols]
        widths: list[int] = [max(len(s), len(v)) + 2 for s, v in flat]

        col = 0
        for grp, cols in groups:
            nc = len(cols)
            cell_w = sum(widths[col : col + nc]) + (nc - 1)
            needed = len(grp) + 2
            if needed > cell_w:
                for k in range(needed - cell_w):
                    widths[col + k % nc] += 1
            col += nc

        spans: list[tuple[int, int, str]] = []
        col = 0
        for grp, cols in groups:
            nc = len(cols)
            spans.append((col, col + nc - 1, grp))
            col += nc

        grp_ends = {end for start, end, _ in spans[:-1]}
        n = len(flat)

        def grp_w(start: int, end: int) -> int:
            """执行 `grp_w`。
            
            参数：
            - `start`：传入的 `start` 参数。
            - `end`：传入的 `end` 参数。
            
            返回：
            - 当前函数的执行结果。
            """
            return sum(widths[start : end + 1]) + (end - start)

        heavy_horizontal = "━"
        light_horizontal = "─"
        heavy_vertical = "┃"
        light_vertical = "│"
        top_left_corner, top_right_corner = "┏", "┓"
        top_t_down = "┳"
        transition_left, transition_right = "┡", "┩"
        group_join = "╇"
        subgroup_join = "┯"
        mid_left, mid_right, mid_cross = "├", "┤", "┼"
        bottom_left_corner, bottom_right_corner, bottom_t_up = "└", "┘", "┴"

        inner_w = sum(widths) + n - 1
        title = f"{title_pfx} — Overall Metrics"
        title_line = title.center(inner_w + 2)

        r1 = top_left_corner
        for i, (s, e, _) in enumerate(spans):
            r1 += heavy_horizontal * grp_w(s, e)
            r1 += top_t_down if i < len(spans) - 1 else top_right_corner

        r2 = heavy_vertical
        for s, e, grp in spans:
            r2 += grp.center(grp_w(s, e)) + heavy_vertical

        r3 = transition_left
        for i, w in enumerate(widths):
            r3 += heavy_horizontal * w
            if i < n - 1:
                r3 += group_join if i in grp_ends else subgroup_join
        r3 += transition_right

        r4 = light_vertical
        for i, (sub, _) in enumerate(flat):
            r4 += sub.center(widths[i]) + light_vertical

        r5 = mid_left
        for i, w in enumerate(widths):
            r5 += light_horizontal * w
            r5 += mid_cross if i < n - 1 else mid_right

        r6 = light_vertical
        for i, (_, val) in enumerate(flat):
            r6 += val.center(widths[i]) + light_vertical

        r7 = bottom_left_corner
        for i, w in enumerate(widths):
            r7 += light_horizontal * w
            r7 += bottom_t_up if i < n - 1 else bottom_right_corner

        return "\n".join([title_line, r1, r2, r3, r4, r5, r6, r7])

    def _convert_preds(self, preds: list[dict[str, torch.Tensor]]) -> list[dict[str, torch.Tensor]]:
        """执行 `_convert_preds`。
        
        参数：
        - `preds`：传入的 `preds` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        out = []
        for p in preds:
            entry = dict(p)
            if "masks" in entry and entry["masks"].ndim == 4 and entry["masks"].shape[1] == 1:
                entry["masks"] = entry["masks"].squeeze(1)
            out.append(entry)
        return out

    def _convert_targets(self, targets: list[dict[str, torch.Tensor]]) -> list[dict[str, torch.Tensor]]:
        """执行 `_convert_targets`。
        
        参数：
        - `targets`：传入的 `targets` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        out = []
        for t in targets:
            h, w = t["orig_size"].tolist()
            scale = t["boxes"].new_tensor([w, h, w, h])
            boxes = box_cxcywh_to_xyxy(t["boxes"]) * scale
            entry: dict[str, torch.Tensor] = {"boxes": boxes, "labels": t["labels"]}
            if "masks" in t:
                masks = t["masks"].bool()
                if masks.shape[-2:] != (int(h), int(w)):
                    masks = (
                        F.interpolate(
                            masks.float().unsqueeze(1),
                            size=(int(h), int(w)),
                            mode="nearest",
                        )
                        .squeeze(1)
                        .bool()
                    )
                entry["masks"] = masks
            if "iscrowd" in t:
                entry["iscrowd"] = t["iscrowd"]
            out.append(entry)
        return out


