"""显式解码节点保留像素，后续读取不重复读磁盘，资源按 Run 释放。"""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from backend.nodes import ExecutionImageRegistry
from backend.contracts.buffers import BufferRef
from backend.contracts.workflows.workflow_graph import NodeDefinition
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.basic.backend.nodes.image_decode import (
    handle_node,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix


@pytest.mark.parametrize(
    "dtype,channels", [(np.uint8, 1), (np.uint8, 3), (np.uint16, 1), (np.uint8, 4)]
)
def test_decode_preserves_pixels_and_run_lifetime(tmp_path, dtype, channels):
    """输入文件删除后仍能复用原图；重复解码原始引用不新增句柄或改动像素。"""
    shape = (30, 40) if channels == 1 else (30, 40, channels)
    expected = np.arange(np.prod(shape), dtype=dtype).reshape(shape)
    path = tmp_path / "source.png"
    path.write_bytes(cv2.imencode(".png", expected)[1].tobytes())
    registry = ExecutionImageRegistry(decoded_cache_max_bytes=1)
    definition = NodeDefinition.model_validate(
        json.loads(
            Path(
                "custom_nodes/opencv_nodes/categories/basic/workflow/catalog_sources/nodes/image_decode.json"
            ).read_text("utf-8")
        )
    )
    source = {
        "transport_kind": "local-path",
        "local_path": str(path),
        "media_type": "image/png",
        "roi_id": "sample",
        "mapped_source": {"source_from_crop": np.eye(3).tolist()},
    }
    request = WorkflowNodeExecutionRequest(
        node_id="decode",
        node_definition=definition,
        input_values={"image": source},
        parameters={},
        execution_metadata={"execution_image_registry": registry},
    )
    try:
        output = handle_node(request)["image"]
        assert registry.decoded_cache_total_bytes == 0
        assert (
            output["roi_id"] == "sample"
            and output["mapped_source"] == source["mapped_source"]
        )
        path.unlink()
        next_request = replace(request, input_values={"image": output})
        for _ in range(3):
            assert handle_node(next_request)["image"] == output
            actual = load_image_matrix(
                next_request, imdecode_flags=cv2.IMREAD_UNCHANGED
            )[2]
            np.testing.assert_array_equal(actual, expected)
            assert actual.dtype == expected.dtype
    finally:
        registry.clear()

    with pytest.raises(Exception, match="不存在"):
        registry.read_matrix(output["image_handle"])


@pytest.mark.parametrize("method", ["opencv", "bmp-bgr24"])
@pytest.mark.parametrize("raw", [False, True])
def test_decode_shared_buffer_preserves_pixels_without_encoded_copy(method, raw):
    """高性能输入的原始像素和上传 BMP 都读取借用视图，不额外复制编码数据。"""
    expected = np.arange(30 * 17 * 3, dtype=np.uint8).reshape(30, 17, 3)
    content = bytearray(
        expected.tobytes() if raw else cv2.imencode(".bmp", expected)[1].tobytes()
    )
    metadata = (
        dict(shape=[30, 17, 3], dtype="uint8", layout="HWC", pixel_format="bgr24")
        if raw
        else {}
    )
    media = "image/raw" if raw else "image/bmp"
    ref = BufferRef(
        buffer_id="local-buffer-main:0",
        lease_id="lease-1",
        arena_id="local-buffer-main",
        descriptor_index=0,
        descriptor_generation=1,
        broker_epoch="1" * 32,
        offset=0,
        content_length=len(content),
        allocation_capacity_bytes=1024 * 1024,
        media_type=media,
        readonly=True,
        **metadata,
    ).model_dump(mode="json")

    def no_copy(_ref):
        """借用视图可用时不应调用复制读取。"""
        raise AssertionError("unexpected encoded copy")

    reader = SimpleNamespace(
        read_buffer_ref_view=lambda _: memoryview(content).toreadonly(),
        read_buffer_ref=no_copy,
        read_frame_ref=no_copy,
    )
    registry = ExecutionImageRegistry(decoded_cache_max_bytes=1)
    definition = NodeDefinition.model_validate(
        json.loads(
            Path(
                "custom_nodes/opencv_nodes/categories/basic/workflow/catalog_sources/nodes/image_decode.json"
            ).read_text("utf-8")
        )
    )
    request = WorkflowNodeExecutionRequest(
        node_id="decode",
        node_definition=definition,
        parameters={"decode_method": method},
        input_values={
            "image": {
                "transport_kind": "buffer",
                "buffer_ref": ref,
                "media_type": media,
                "width": 17,
                "height": 30,
                **metadata,
            }
        },
        execution_metadata={
            "execution_image_registry": registry,
            "local_buffer_reader": reader,
        },
    )
    try:
        for _ in range(2):
            output = handle_node(request)["image"]
            np.testing.assert_array_equal(
                registry.read_matrix(output["image_handle"]), expected
            )
    finally:
        registry.clear()
    with pytest.raises(Exception, match="不存在"):
        registry.read_matrix(output["image_handle"])


def test_explicit_bmp_decoder_matches_default_identity(tmp_path):
    """优化读取不改变 image-ref 的像素身份，且注册后不依赖源文件。"""
    definition = NodeDefinition.model_validate(
        json.loads(
            Path(
                "custom_nodes/opencv_nodes/categories/basic/workflow/catalog_sources/nodes/image_decode.json"
            ).read_text("utf-8")
        )
    )
    path = tmp_path / "像素.bmp"
    expected = np.arange(30 * 17 * 3, dtype=np.uint8).reshape(30, 17, 3)
    path.write_bytes(cv2.imencode(".bmp", expected)[1].tobytes())
    registry = ExecutionImageRegistry(decoded_cache_max_bytes=1)
    request = WorkflowNodeExecutionRequest(
        node_id="decode",
        node_definition=definition,
        input_values={
            "image": {
                "transport_kind": "local-path",
                "local_path": str(path),
                "media_type": "image/bmp",
            }
        },
        parameters={},
        execution_metadata={"execution_image_registry": registry},
    )
    try:
        regular = handle_node(request)["image"]
        direct = handle_node(
            replace(request, parameters={"decode_method": "bmp-bgr24"})
        )["image"]
        assert regular["content_sha256"] == direct["content_sha256"]
        encoded = registry.register_image_bytes(
            content=path.read_bytes(), media_type="image/bmp"
        )
        memory_request = replace(
            request,
            input_values={
                "image": {
                    "transport_kind": "memory",
                    "image_handle": encoded.image_handle,
                    "media_type": "image/bmp",
                }
            },
            parameters={"decode_method": "bmp-bgr24"},
        )
        # 反复读取上传式编码内存输入，不消耗或修改原始内容。
        for _ in range(2):
            uploaded = handle_node(memory_request)["image"]
            assert uploaded["content_sha256"] == direct["content_sha256"]
        path.unlink()
        assert (
            handle_node(
                replace(
                    request,
                    input_values={"image": direct},
                    parameters={"decode_method": "bmp-bgr24"},
                )
            )["image"]
            == direct
        )
        np.testing.assert_array_equal(
            registry.read_matrix(direct["image_handle"]), expected
        )
    finally:
        registry.clear()
