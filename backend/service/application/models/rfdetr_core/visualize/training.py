"""RF-DETR core 可视化处理模块：`visualize.training`。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def plot_metrics(
    metrics_csv: str,
    output_path: Optional[str] = None,
    loss_log_scale: bool = False,
) -> str:
    """执行 `plot_metrics`。
    
    参数：
    - `metrics_csv`：传入的 `metrics_csv` 参数。
    - `output_path`：传入的 `output_path` 参数。
    - `loss_log_scale`：传入的 `loss_log_scale` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError("matplotlib is required for plot_metrics(). Install it with: pip install matplotlib") from exc

    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError("pandas is required for plot_metrics(). Install it with: pip install pandas") from exc

    try:
        import seaborn as sns
    except ImportError as exc:
        raise ImportError("seaborn is required for plot_metrics(). Install it with: pip install seaborn") from exc

    csv_path = Path(metrics_csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"metrics.csv not found: {csv_path}")

    if output_path is None:
        output_path = str(csv_path.parent / "metrics_plot.png")

    df = pd.read_csv(csv_path)
    if "epoch" not in df.columns:
        raise ValueError("metrics.csv does not contain an 'epoch' column.")
    df = df.groupby("epoch").mean(numeric_only=True).reset_index()

    def _val_cols(*patterns: str) -> list[str]:
        """执行 `_val_cols`。
        
        返回：
        - 当前函数的执行结果。
        """
        return [c for c in df.columns if c.startswith("val/") and any(p in c for p in patterns) and df[c].notna().any()]

    loss_cols = [c for c in ("train/loss", "val/loss", "test/loss") if c in df.columns and df[c].notna().any()]

    metric_groups: dict[str, list[str]] = {
        "Loss": loss_cols,
        "AP@0.50": _val_cols("mAP_50"),
        "AP@0.50:0.95": _val_cols("mAP_50_95"),
        "AR": _val_cols("mAR"),
    }
    metric_groups["AP@0.50"] = [c for c in metric_groups["AP@0.50"] if "mAP_50_95" not in c]
    metric_groups = {k: v for k, v in metric_groups.items() if v}

    n_groups = len(metric_groups)
    n_cols = 2
    n_rows = (n_groups + n_cols - 1) // n_cols

    fig, axes = plt.subplots(n_rows, n_cols, figsize=(12, 5 * n_rows), squeeze=False)
    axes_flat = axes.flatten()

    melted = df.melt(id_vars="epoch", var_name="metric", value_name="value")

    for idx, (title, metric_list) in enumerate(metric_groups.items()):
        ax = axes_flat[idx]
        group_data = melted[melted["metric"].isin(metric_list)]
        sns.lineplot(data=group_data, x="epoch", y="value", hue="metric", marker="o", ax=ax)
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_xlabel("Epoch", fontsize=11)
        ax.set_ylabel(title, fontsize=11)
        ax.grid(True, alpha=0.3)
        if title == "Loss" and loss_log_scale:
            ax.set_yscale("log")

    for idx in range(n_groups, len(axes_flat)):
        axes_flat[idx].set_visible(False)

    fig.suptitle("RF-DETR Training Metrics", fontsize=14)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return str(Path(output_path).resolve())


