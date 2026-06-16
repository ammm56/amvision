"""YOLOX checkpoint 文件辅助函数。"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any


def save_checkpoint(
    *,
    torch_module: Any,
    state: dict[str, object],
    is_best: bool,
    save_dir: Path,
    model_name: str = "",
) -> Path:
    """保存 YOLOX checkpoint，并在需要时同步 best checkpoint。"""

    save_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = save_dir / f"{model_name}_ckpt.pth"
    torch_module.save(state, checkpoint_path)
    if is_best:
        shutil.copyfile(checkpoint_path, save_dir / "best_ckpt.pth")
    return checkpoint_path
