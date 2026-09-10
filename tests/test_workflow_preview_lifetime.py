"""预览最后消费者与并行返回值的确定性释放验证。"""
from types import SimpleNamespace as NS

import numpy as np
import pytest

from backend.nodes.runtime_support import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.preview.lifetime import PreviewLifetimes
from backend.service.application.workflows.preview.session import PreviewSessionManager


def image(registry):
    """创建真实矩阵引用，避免仅用 mock 计数掩盖悬空图片。"""
    entry = registry.register_image_matrix(matrix=np.zeros((32, 48, 3), dtype=np.uint8), width=48, height=32)
    return build_memory_image_payload(image_handle=entry.image_handle, media_type=entry.media_type)


def template(edges=(), outputs=()):
    return NS(edges=[NS(source_node_id=a, source_port=p, target_node_id=b) for a, p, b in edges],
              template_outputs=[NS(source_node_id=a, source_port=p) for a, p in outputs], template_inputs=[])


def test_aliases_survive_until_last_consumer_and_drop_before_long_tail():
    images = ExecutionImageRegistry()
    lifetime = PreviewLifetimes(images)
    payload = image(images)
    scope = lifetime.scope(template([('source', 'image', 'a'), ('source', 'image', 'b')]), {}, {})
    scope['source', 'image'] = payload
    scope.complete('source')
    scope.complete('a')
    assert images.get_entry(payload['image_handle']).matrix is not None
    scope.complete('b')
    assert not scope and not lifetime.counts
    with pytest.raises(Exception, match='不存在'):
        images.get_entry(payload['image_handle'])
    images.clear()


def test_parallel_handoff_keeps_nested_source_until_parent_adopts_it():
    images = ExecutionImageRegistry()
    lifetime = PreviewLifetimes(images)
    metadata = {}
    parent = lifetime.scope(template([('join', 'value', 'later')]), {}, metadata)
    child = lifetime.scope(template(outputs=[('child', 'value')]), {}, dict(metadata))
    payload = image(images)
    nested = {'roi': {'source_image': payload}, 'same_image': [payload]}
    child['child', 'value'] = nested
    child.finish(nested)
    assert images.get_entry(payload['image_handle'])
    parent['join', 'value'] = nested
    parent.complete('join')
    assert images.get_entry(payload['image_handle'])
    parent.complete('later')
    assert not lifetime.counts
    images.clear()


def test_consumed_uploaded_input_releases_all_worker_binding_containers():
    """大输入不能在完成消费后被 request/校验字典继续固定持有。"""
    images = ExecutionImageRegistry()
    lifetime = PreviewLifetimes(images)
    payload = {"image_base64": "encoded-input"}
    original, validated, inputs = {"binding": payload}, {"binding": dict(payload)}, {"input": payload}
    lifetime.adopt_bindings(NS(bindings=[NS(direction="input", template_port_id="input", binding_id="binding")]), original, validated)
    graph = template()
    graph.template_inputs = [NS(input_id="input", target_node_id="decode")]
    scope = lifetime.scope(graph, inputs, {})
    scope.complete("other")
    assert original and validated and inputs
    scope.complete("decode")
    assert not original and not validated and not inputs
    images.clear()


def test_receipt_requires_complete_transfer_and_all_subscribers():
    manager = PreviewSessionManager()
    try:
        sid = manager.create(principal_id='p', project_id='p', application_id='a', editor_session_id='e')['session_id']
        first, _ = manager.subscribe(sid, 'p')
        second, _ = manager.subscribe(sid, 'p')
        block = manager.buffers.allocate(sid, 4, media_type='image/jpeg')
        manager.buffers.write_chunk(sid, block, 0, b'data')
        descriptor = manager.buffers.commit(sid, block)
        manager.authorize(sid, 'p').displays['display'] = {'transport_kind': 'preview-memory', **descriptor}
        with pytest.raises(ValueError, match='receipt'):
            manager.received_blob(sid, first, block, 'forged')
        receipt = manager.issue_receipt(sid, block)
        manager.received_blob(sid, first, block, receipt)
        assert manager.buffers.stats()['blocks'] == 1
        with manager.buffers.borrow(sid, block) as content:
            manager.received_blob(sid, second, block, receipt)
            assert bytes(content) == b'data'
            assert manager.buffers.stats()['pins'] == 1
        assert manager.buffers.stats()['blocks'] == 0
        manager.received_blob(sid, first, block, receipt)
    finally:
        manager.close()
