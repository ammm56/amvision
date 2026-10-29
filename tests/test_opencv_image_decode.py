"""显式解码节点保留像素，后续读取不重复读磁盘，资源按 Run 释放。"""

import json
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.nodes import ExecutionImageRegistry
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
