"""编辑态 Preview 的版本化显示资产；复用现有捕获接口，不接入正式数据面。"""

from __future__ import annotations

import hashlib
import logging
from pathlib import PurePosixPath

from backend.service.application.workflows.runtime_preview import (
    MAX_PREVIEW_BYTES, MAX_PREVIEW_VALUES, PREVIEW_TYPES, RuntimePreviewCapture, _copy_json,
)

DISPLAY_FORMAT = "amvision.workflow-preview-displays.v1"
LOGGER = logging.getLogger(__name__)


class PreviewResultStore(RuntimePreviewCapture):
    """每个 Run 独占的显示写入器；循环节点只保留最后一次完整调用。"""

    def __init__(self, storage, preview_run_id: str):
        """storage 提供原子写入；preview_run_id 决定资产的生命周期。"""
        super().__init__()
        self.storage = storage
        self.run_id = preview_run_id
        self.root = f"workflows/runtime/preview-runs/{preview_run_id}"
        self.descriptors: dict[str, dict] = {}
        self.sizes: dict[str, tuple[int, int]] = {}
        self.failure: str | None = None
        self._publish_manifest()

    def _publish_manifest(self) -> None:
        """使用 ObjectStore 已有临时文件与 replace 机制发布完整清单。"""
        try:
            self.storage.write_json(f"{self.root}/displays/manifest.json", {
                "format_id": DISPLAY_FORMAT, "preview_run_id": self.run_id,
                "displays": list(self.descriptors.values()), "error": self.failure,
            })
        except Exception:
            self.failure = "preview_display_write_failed"
            LOGGER.exception("Preview 显示清单保存失败: %s", self.run_id)

    def capture(self, *, node_id, definition, outputs, invocation_id, duration_ms) -> None:
        """按显示 body 契约捕获，保留交互；不按节点名称猜测显示能力。"""
        with self.lock:
            for port in definition.output_ports:
                payload = outputs.get(port.name)
                if not isinstance(payload, dict) or payload.get("type") not in PREVIEW_TYPES:
                    continue
                display_id = hashlib.sha256(f"{node_id}\0{port.name}".encode()).hexdigest()
                descriptor = {"display_id": display_id, "node_id": node_id,
                    "node_type_id": definition.node_type_id, "output_port": port.name,
                    "invocation_id": invocation_id, "duration_ms": duration_ms,
                    "type": payload["type"], "error": None}
                try:
                    # 预算针对最终保留数据，循环覆盖不会不断耗尽容量。
                    old = self.sizes.get(display_id, (0, 0))
                    available = [MAX_PREVIEW_BYTES - sum(s[0] for s in self.sizes.values()) + old[0],
                                 MAX_PREVIEW_VALUES - sum(s[1] for s in self.sizes.values()) + old[1]]
                    budget = available.copy()
                    copied = _copy_json(payload, budget)
                    self._preserve_uploaded_images(copied)
                    self.storage.write_json(f"{self.root}/displays/{display_id}.json", copied)
                    self.sizes[display_id] = (available[0] - budget[0], available[1] - budget[1])
                except Exception as error:
                    # 单个显示失败不清空其他节点，也不改变业务执行状态。
                    descriptor["error"] = str(error) if isinstance(error, ValueError) else "preview_display_write_failed"
                    LOGGER.warning("Preview 节点显示不可用: %s/%s", self.run_id, node_id, exc_info=True)
                self.descriptors[display_id] = descriptor
                self._publish_manifest()

    def _preserve_uploaded_images(self, value) -> None:
        """只复制即将回收的上传图片，项目资产及已属于 Run 的图片继续引用。"""
        if isinstance(value, dict):
            key = value.get("object_key")
            if value.get("transport_kind") == "storage-ref" and isinstance(key, str) and key.startswith("workflows/runtime-inputs/"):
                name = hashlib.sha256(key.encode()).hexdigest() + PurePosixPath(key).suffix
                target = f"{self.root}/artifacts/inputs/{name}"
                if not self.storage.resolve(target).is_file():
                    self.storage.copy_file(self.storage.resolve(key), target)
                value["object_key"] = target
            for item in value.values():
                self._preserve_uploaded_images(item)
        elif isinstance(value, list):
            for item in value:
                self._preserve_uploaded_images(item)


def read_display_manifest(storage, preview_run):
    """读取新清单，或从历史完整响应生成兼容清单；不重新执行应用。"""
    root = f"workflows/runtime/preview-runs/{preview_run.preview_run_id}"
    key = f"{root}/displays/manifest.json"
    if storage.resolve(key).is_file():
        return storage.read_json(key)
    if preview_run.metadata.get("preview_display_format") == DISPLAY_FORMAT:
        return {"format_id": DISPLAY_FORMAT, "preview_run_id": preview_run.preview_run_id,
                "displays": [], "error": "preview_display_results_unavailable"}
    # 旧运行显式标为 legacy，由旧完整查询交付，避免在只读请求中改写历史结果。
    return {"format_id": DISPLAY_FORMAT, "preview_run_id": preview_run.preview_run_id,
            "displays": [], "legacy": True, "error": None}
