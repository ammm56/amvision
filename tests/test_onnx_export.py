"""PyTorch ONNX 导出公共工具测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
import time
from types import SimpleNamespace

from backend.service.application.models.export import onnx_export


class _ConcurrentExportProbe:
    """记录 fake ONNX exporter 的同时执行数量。"""

    def __init__(self) -> None:
        """初始化并发计数器。"""

        self.active_count = 0
        self.maximum_active_count = 0
        self.call_count = 0
        self._lock = Lock()

    def export(self, **_: object) -> None:
        """模拟会释放 GIL 的耗时导出调用。"""

        with self._lock:
            self.active_count += 1
            self.maximum_active_count = max(
                self.maximum_active_count,
                self.active_count,
            )
            self.call_count += 1
        time.sleep(0.05)
        with self._lock:
            self.active_count -= 1


def test_torch_onnx_dynamo_exports_are_serialized_per_process(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """确认并发 conversion task 不会同时进入 torch.export 全局状态。"""

    monkeypatch.setattr(
        onnx_export,
        "ensure_torch_onnx_dynamo_exporter_dependencies",
        lambda: None,
    )
    exporter = _ConcurrentExportProbe()
    torch_module = SimpleNamespace(onnx=exporter)

    def run_export(index: int) -> None:
        """执行一条 fake ONNX 导出。"""

        onnx_export.export_torch_model_to_onnx(
            torch_module=torch_module,
            model=object(),
            model_args=(object(),),
            output_path=tmp_path / f"model-{index}.onnx",
            opset_version=18,
            input_names=("images",),
            output_names=("predictions",),
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(run_export, index) for index in range(3)]
        for future in futures:
            future.result()

    assert exporter.call_count == 3
    assert exporter.maximum_active_count == 1
