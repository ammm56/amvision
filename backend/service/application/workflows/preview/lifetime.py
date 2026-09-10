"""编辑预览的输出消费计划与图像引用；正式 Runtime 不创建此管理器。"""

from collections import Counter, defaultdict
from threading import RLock
from uuid import uuid4


def image_handles(value):
    """只遍历端口 JSON 容器，合并嵌套 ROI/列表中的图片别名。"""
    found, visited = set(), set()
    stack = [value]
    while stack:
        item = stack.pop()
        if not isinstance(item, (dict, list, tuple)) or id(item) in visited:
            continue
        visited.add(id(item))
        if isinstance(item, dict):
            if item.get("transport_kind") == "memory" and isinstance(item.get("image_handle"), str):
                found.add(item["image_handle"])
            stack.extend(item.values())
        else:
            stack.extend(item)
    return found


class PreviewLifetimes:
    """跨并行作用域共享引用计数，交付任务独立复制后不再借用业务图片。"""

    def __init__(self, images):
        """images 是本次执行的 registry，计数不跨运行持久化。"""
        self.images = images
        self.lock = RLock()
        self.counts = Counter()
        self.handoffs = defaultdict(list)
        self.decode_keys = defaultdict(set)
        self.released_count = 0
        self.binding_owners = []
        self.binding_ids = defaultdict(set)

    def adopt_bindings(self, application, *owners):
        """校验完成后接管 Preview 专有输入字典，最后消费时移除大 Base64/JSON 引用。"""
        self.binding_owners = owners
        for binding in application.bindings:
            if binding.direction == "input":
                self.binding_ids[binding.template_port_id].add(binding.binding_id)

    def retain(self, value):
        """端口或作用域获得图片所有权；同一容器重复引用只计一次。"""
        handles = image_handles(value)
        with self.lock:
            self.counts.update(handles)
        return handles

    def release(self, handles):
        """只释放最后一个使用者归还的图片及对应解码缓存。"""
        with self.lock:
            for handle in handles:
                self.counts[handle] -= 1
                if self.counts[handle] > 0:
                    continue
                del self.counts[handle]
                self.images.release(handle)
                self.images.release_decoded_matrices(self.decode_keys.pop(handle, ()))
                self.released_count += 1

    def track_decode(self, handle, key):
        """记录已存在的解码 key，回收时不扫描其他图片或重算 hash。"""
        if handle:
            with self.lock:
                self.decode_keys[handle].add(key)

    def scope(self, template, inputs, metadata, collapsed=None, final_keys=None):
        """为当前图/循环轮次建立一次性消费索引。"""
        return PreviewOutputScope(self, template, inputs, metadata, collapsed or {}, final_keys)


class PreviewOutputScope(dict):
    """沿用执行器字典接口，节点结束仅处理该节点涉及的消费项。"""

    def __init__(self, manager, template, inputs, metadata, collapsed, final_keys):
        super().__init__()
        self.manager, self.metadata = manager, metadata
        self.identity = uuid4().hex
        self.parent = metadata.get("_preview_scope")
        metadata["_preview_scope"] = self.identity
        self.handles, self.consumers = {}, defaultdict(set)
        self.input_values, self.input_ids = inputs, defaultdict(set)
        self.incoming, self.produced, self.inputs = defaultdict(set), defaultdict(set), defaultdict(list)
        self.held, self.variable_ids = [], {}
        self.closed = False
        for edge in template.edges:
            key = (edge.source_node_id, edge.source_port)
            consumer = collapsed.get(edge.target_node_id, edge.target_node_id)
            self.consumers[key].add(consumer)
            self.incoming[consumer].add(key)
        finals = final_keys if final_keys is not None else {(out.source_node_id, out.source_port) for out in template.template_outputs}
        for key in finals:
            self.consumers[key].add(None)
        for port in template.template_inputs:
            consumer = collapsed.get(port.target_node_id, port.target_node_id)
            self.inputs[consumer].append(manager.retain(inputs.get(port.input_id)))
            self.input_ids[consumer].add(port.input_id)

    def __setitem__(self, key, value):
        handles = self.manager.retain(value)
        old = self.handles.pop(key, set())
        super().__setitem__(key, value)
        self.handles[key] = handles
        self.produced[key[0]].add(key)
        self.manager.release(old)

    def discard(self, key):
        """移除输出字典和注册表的对应持有。"""
        super().pop(key, None)
        self.manager.release(self.handles.pop(key, set()))

    def complete(self, node_id, *, opaque=False):
        """先接管变量和子作用域返回值，再注销本节点消费；不扫描整图。"""
        for name, value in self.metadata.get("workflow_variables", {}).items():
            if self.variable_ids.get(name) != id(value):
                self.held.append(self.manager.retain(value))
                self.variable_ids[name] = id(value)
        if opaque:
            # 未声明内部持有关系的扩展节点保留其已知输入至作用域结束。
            for key in self.incoming[node_id]:
                if key in self:
                    self.held.append(self.manager.retain(self[key]))
        with self.manager.lock:
            handoffs = self.manager.handoffs.pop(self.identity, [])
        for handles in handoffs:
            self.manager.release(handles)
        for key in self.incoming[node_id] | self.produced[node_id]:
            self.consumers[key].discard(node_id)
            if not self.consumers[key]:
                self.discard(key)
        for handles in self.inputs.pop(node_id, []):
            self.manager.release(handles)
        for input_id in self.input_ids.pop(node_id, ()):
            self.input_values.pop(input_id, None)
            if self.parent is None:
                for owner in self.manager.binding_owners:
                    for binding in self.manager.binding_ids.get(input_id, ()):
                        owner.pop(binding, None)

    def finish(self, outputs):
        """返回值先移交父作用域；根结果保留至 Worker 完成业务输出交接。"""
        if self.closed:
            return
        self.closed = True
        with self.manager.lock:
            self.manager.handoffs[self.parent].append(self.manager.retain(outputs))
        for key in list(self):
            self.discard(key)
        for handles in self.held + [item for values in self.inputs.values() for item in values]:
            self.manager.release(handles)
        self.inputs.clear()
        self.held.clear()
        self.metadata["_preview_scope"] = self.parent
