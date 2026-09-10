"""编辑态显示副本的内存编码与交接；业务端口值不经过显示传输。"""

from concurrent.futures import ThreadPoolExecutor, Future
from collections import OrderedDict
from copy import deepcopy
from threading import BoundedSemaphore, RLock
from uuid import uuid4
from itertools import islice

from backend.service.application.workflows.runtime_preview import RuntimePreviewCapture, PREVIEW_TYPES, _copy_json
from backend.service.application.workflows.preview.values import PreviewValues

JPEG_QUALITY = 90
"""页面显示编码质量；不改变节点业务图片或模型输入。"""


class PreviewDisplayCapture(RuntimePreviewCapture):
    """复用执行器已有观察点；有界后台编码不占用 HTTP 或模型运行线程。"""

    def __init__(self, bridge, emit, events=None):
        """一条独立编码线程和最多 128 个图像任务，矩阵字节另行限制。"""
        self.bridge = bridge
        self.emit = emit
        self.events = events
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview-display-events")
        self.encoder = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview-image-encode")
        self.capacity = BoundedSemaphore(128)
        self.display_capacity = BoundedSemaphore(128)
        self.lock = RLock()
        self.bytes = 0
        self.images = OrderedDict()
        self.display_bytes = 0
        self.failure = None
        self.encoding_sources = {}
        self.values = PreviewValues(bridge)

    def image(self, request, *, image_payload, save_location=None, **options):
        """保存是节点明确行为；显示图只复制到内存，保留原图尺寸和坐标空间。"""
        from backend.nodes.runtime_support import _load_preview_image_matrix, require_execution_image_registry
        saved_output = None
        if save_location:
            # 显式保存沿用节点既有语义；显示结果仍使用内存通道。
            from backend.nodes.runtime_support import load_encoded_image_bytes_from_payload, resolve_optional_save_location, save_bytes
            location = resolve_optional_save_location(save_location, scope="file")
            if location is not None:
                _, content = load_encoded_image_bytes_from_payload(request, image_payload=image_payload)
                saved_output = save_bytes(request, save_location=location, content=content).to_payload()
        _, matrix, width, height = _load_preview_image_matrix(request, image_payload=image_payload)
        source_key = None
        source_jpeg = None
        if isinstance(image_payload, dict) and image_payload.get("transport_kind") == "memory":
            entry = require_execution_image_registry(request).get_entry(image_payload.get("image_handle"))
            if isinstance(entry.content, bytes):
                source_key = entry.image_handle
                if entry.media_type == "image/jpeg":
                    source_jpeg = entry.content
        with self.lock:
            result = self._schedule_image(matrix, width, height, source_key, source_jpeg)
            if saved_output is not None:
                result["saved_output"] = saved_output
            return result

    def _schedule_image(self, matrix, width, height, source_key, source_jpeg=None):
        """同一不可变源只登记一次编码，复制完成后立即归还业务线程。"""
        import cv2
        with self.lock:
            pending = self.encoding_sources.get(source_key) if source_key else None
            if pending is not None:
                return {"transport_kind": "preview-memory", "pending_image_id": pending, "width": width, "height": height}
            if len(self.images) >= 4096:
                return {"transport_kind": "preview-memory", "unavailable": "preview_image_descriptor_capacity", "width": width, "height": height}
        amount = matrix.nbytes
        with self.lock:
            if self.bytes + amount > 256 * 1024**2 or not self.capacity.acquire(blocking=False):
                return {"transport_kind": "preview-memory", "unavailable": "preview_encoding_capacity", "width": width, "height": height}
            self.bytes += amount
        identity = uuid4().hex
        try:
            # 排队任务只持有一份矩阵；编码工作区只由当前编码任务预留。
            self.bridge.reserve(identity, amount)
            owned = matrix.copy()
        except Exception as error:
            with self.lock:
                self.bytes -= amount
            self.capacity.release()
            self.bridge.reserve(identity, 0)
            return {"transport_kind": "preview-memory", "unavailable": str(error)[:256], "width": width, "height": height}

        thumbnail = Future()

        def publish_jpeg(pixels):
            """JPEG 仅用于页面显示，业务矩阵保持原样。"""
            if pixels.ndim == 3 and pixels.shape[2] == 4:
                pixels = cv2.cvtColor(pixels, cv2.COLOR_BGRA2BGR)
            ok, encoded = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                raise ValueError("preview_image_encoding_failed")
            return {"transport_kind": "preview-memory", **self.bridge.publish(encoded.tobytes(), "image/jpeg"),
                    "width": pixels.shape[1], "height": pixels.shape[0]}

        def encode():
            """先交付缩略图，再编码全尺寸 JPEG；两阶段不阻塞业务图。"""
            try:
                self.bridge.reserve("image-encoder", amount * 2 + 64 * 1024)
                scale = min(1.0, 1920 / max(width, height))
                small = cv2.resize(owned, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA) if scale < 1 else owned
                display = publish_jpeg(small)
                metadata = {**display, "display_image": display, "source_width": width, "source_height": height,
                            "display_width": display["width"], "display_height": display["height"], "display_scale": scale}
                thumbnail.set_result({**metadata, "source_image": {"transport_kind": "preview-memory", "pending_image_id": identity,
                                                                  "width": width, "height": height, "pending_source": True}} if scale < 1 else {**metadata, "source_image": display})
                source = ({"transport_kind": "preview-memory", **self.bridge.publish(source_jpeg, "image/jpeg"), "width": width, "height": height}
                          if scale < 1 and source_jpeg is not None else publish_jpeg(owned) if scale < 1 else display)
                return {**metadata, "source_image": source}
            except Exception as error:
                # Future 只保留错误描述，不能通过 traceback 长期持有大矩阵。
                unavailable = {"transport_kind": "preview-memory", "unavailable": str(error)[:256]}
                if not thumbnail.done():
                    thumbnail.set_result(unavailable)
                return unavailable
            finally:
                with self.lock:
                    self.bytes -= amount
                self.capacity.release()
                self.bridge.reserve(identity, 0)
                self.bridge.reserve("image-encoder", 0)
        with self.lock:
            self.images[identity] = (thumbnail, self.encoder.submit(encode))
            if source_key:
                self.encoding_sources[source_key] = identity
        return {"transport_kind": "preview-memory", "pending_image_id": identity, "width": width, "height": height}

    def _resolve(self, value, *, full=True):
        """只处理显示 body，执行图中的原始输出和图片引用保持不变。"""
        if isinstance(value, dict):
            if value.get("transport_kind") == "inline-base64" and isinstance(value.get("image_base64"), str):
                from base64 import b64decode
                source = value["image_base64"]
                if len(source) > 64 * 1024**2:
                    raise ValueError("preview_image_capacity")
                key = f"inline:{uuid4().hex}"
                self.bridge.reserve(key, len(source))
                try:
                    import cv2
                    import numpy as np
                    pixels = cv2.imdecode(np.frombuffer(b64decode(source, validate=True), dtype=np.uint8), cv2.IMREAD_COLOR)
                    if pixels is None:
                        raise ValueError("preview_image_decode_failed")
                    ok, encoded = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                    if not ok:
                        raise ValueError("preview_image_encoding_failed")
                    descriptor = self.bridge.publish(encoded.tobytes(), "image/jpeg")
                    return {**{k: v for k, v in value.items() if k != "image_base64"}, **descriptor, "transport_kind": "preview-memory"}
                finally:
                    self.bridge.reserve(key, 0)
            if value.get("transport_kind") == "preview-memory":
                if value.get("unavailable"):
                    raise ValueError(value["unavailable"])
                identity = value.get("pending_image_id")
                if identity:
                    with self.lock:
                        future = self.images.get(identity)
                    if future is None:
                        raise ValueError("preview_image_expired")
                    resolved = future[1 if full else 0].result()
                    if resolved.get("unavailable"):
                        raise ValueError(resolved["unavailable"])
                    if value.get("pending_source"):
                        return resolved["source_image"]
                    return {**resolved, "saved_output": value["saved_output"]} if "saved_output" in value else resolved
            return {key: self._resolve(item, full=full) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self._resolve(item, full=full) for item in value]
        return value

    def capture(self, *, node_id, definition, outputs, invocation_id, duration_ms):
        """完整值及交互参数在节点结束时排入显示通道，不使用截断的节点摘要。"""
        # 普通视觉节点的 debug_preview 也使用声明的 response-body 端口；
        # 不能只按专门的 Preview 节点 capability 过滤。
        display_ports = []
        for port in definition.output_ports:
            if port.name not in outputs:
                continue
            value = outputs.get(port.name)
            found = list(_display_bodies(value))
            if not found:
                identity = self.events.current() if self.events else {"node_id": node_id, "invocation_id": invocation_id}
                self.emit("value.updated", {**identity, "output_port": port.name,
                    "node_type_id": definition.node_type_id, "value": self.values.describe(value)})
                continue
            display_ports.extend((port.name + path, body) for path, body in found)
        for output_port, value in display_ports:
            identity = {"node_id": node_id, "node_type_id": definition.node_type_id, "output_port": output_port,
                        "invocation_id": invocation_id, "duration_ms": duration_ms}
            if self.events is not None:
                identity.update(self.events.current())
            if not self.display_capacity.acquire(blocking=False):
                self.emit("display.unavailable", {**identity, "error": "preview_display_queue_capacity"})
                continue
            budget = [4 * 1024**2 - 4096, 100_000]
            amount = 0
            reservation = f"display:{uuid4().hex}"
            try:
                if value.get("type") in {"value-preview", "table-preview"}:
                    # 完整值单独分页；画布只绘制小窗口，绝不把摘要冒充完整结果。
                    descriptor = self.values.describe(value)
                    self.emit("value.updated", {**identity, "value": descriptor})
                    if descriptor["kind"] == "json":
                        from backend.service.application.workflows.preview.values import _page
                        field = "value" if value["type"] == "value-preview" else "rows"
                        page = _page(value, [field], 0, 4)
                        value = {**value, field: page["value"], "paged": True, "value_descriptor": descriptor,
                                 "status_text": "preview_value_paged"}
                    elif descriptor["kind"] == "unavailable":
                        raise ValueError(descriptor["error"])
                copied = _copy_json(value, budget)
                amount = 4 * 1024**2 - 4096 - budget[0]
                with self.lock:
                    if self.display_bytes + amount > 8 * 1024**2:
                        amount = 0
                        raise ValueError("preview_display_queue_capacity")
                    self.display_bytes += amount
                self.bridge.reserve(reservation, amount)
            except Exception as error:
                with self.lock:
                    self.display_bytes -= amount
                self.display_capacity.release()
                self.emit("display.unavailable", {**identity, "error": str(error)[:256]})
                continue
            def send(copied=copied, identity=deepcopy(identity), amount=amount, reservation=reservation):
                """编码完成才发布完整 descriptor，错误只影响相应显示。"""
                try:
                    first = self._resolve(copied, full=False)
                    self.emit("display.updated", {**identity, "payload": first})
                    # 只补全第一阶段的 pending 引用，避免再次解码内联图或重复发布 Blob。
                    complete = self._resolve(first)
                    if complete != first:
                        self.emit("display.updated", {**identity, "payload": complete})
                except Exception as error:
                    self.emit("display.unavailable", {**identity, "error": str(error)[:256]})
                finally:
                    with self.lock:
                        self.display_bytes -= amount
                    self.display_capacity.release()
                    self.bridge.reserve(reservation, 0)
            future = self.executor.submit(send)
            future.add_done_callback(self._sent)

    def _sent(self, future):
        """显示异常已变为 unavailable；剩余异常表示控制通道损坏，不能静默成功。"""
        error = future.exception()
        if error is not None:
            with self.lock:
                self.failure = self.failure or error

    def close(self):
        """正常/取消均排空已产生的显示，并释放所有矩阵与 Future 引用。"""
        self.encoder.shutdown(wait=True)
        self.executor.shutdown(wait=True)
        if self.failure is not None:
            raise RuntimeError("preview_display_channel_failed") from self.failure

    def resolve_outputs(self, outputs):
        """排空编码后解析终态输出的内存图引用，绝不修改图中的业务值。"""
        try:
            return self._resolve(outputs)
        except ValueError as error:
            return {"preview_value": {"kind": "unavailable", "error": str(error)[:256]}}
        finally:
            self.images.clear()
            self.encoding_sources.clear()

    def video(self, request, payload):
        """读取节点已有视频到有界 SHM，不为预览复制到 ObjectStore。"""
        from backend.nodes.video_runtime_support_payloads import resolve_video_source_path
        path = resolve_video_source_path(request, video_payload=payload)
        size = path.stat().st_size
        if not 0 < size <= 64 * 1024**2:
            return {"transport_kind": "preview-memory", "unavailable": "preview_video_capacity"}
        key = f"video:{uuid4().hex}"
        self.bridge.reserve(key, size * 2)
        try:
            with path.open("rb") as source:
                content = source.read(size + 1)
            if len(content) != size:
                raise ValueError("preview_video_source_changed")
            return {**{k: v for k, v in payload.items() if k not in {"local_path", "object_key", "transport_kind"}},
                    "transport_kind": "preview-memory", **self.bridge.publish(content, payload["media_type"])}
        finally:
            self.bridge.reserve(key, 0)


def _display_bodies(value, path="", depth=0):
    """支持自定义节点的 body/data 嵌套显示，使用确定的端口路径而非节点类型特判。"""
    if depth > 8 or not isinstance(value, dict):
        return
    if value.get("type") in PREVIEW_TYPES:
        yield path, value
    else:
        # 仅沿对象查找显示声明，不扫描大型业务数组；路径按 JSON Pointer 转义。
        for key, child in islice(value.items(), 256):
            if isinstance(key, str) and isinstance(child, dict):
                escaped = key.replace("~", "~0").replace("/", "~1")
                yield from _display_bodies(child, f"{path}/{escaped}", depth + 1)
