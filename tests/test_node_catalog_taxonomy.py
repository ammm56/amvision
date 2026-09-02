"""Core 与 OpenCV 两层节点分类回归测试。"""

from __future__ import annotations

import re
from collections import Counter

from backend.nodes.core_catalog import get_core_workflow_node_definitions
from custom_nodes.opencv_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_document,
)


EXPECTED_CORE_CATEGORY_COUNTS = {
    "core.input.prompt": 8,
    "core.io.image": 8,
    "core.io.file": 14,
    "core.io.input": 6,
    "core.io.response": 4,
    "core.io.video": 5,
    "core.ui.preview": 4,
    "core.logic.condition": 4,
    "core.logic.collection": 16,
    "core.logic.branch": 7,
    "core.logic.iteration": 4,
    "core.logic.parallel": 2,
    "core.logic.object": 9,
    "core.logic.transform": 28,
    "core.logic.value": 7,
    "core.logic.variable": 3,
    "core.logic.rule": 6,
    "core.model.inference": 13,
    "core.model.lifecycle": 5,
    "core.dataset.import": 1,
    "core.dataset.export": 2,
    "core.deployment.runtime": 7,
    "core.task.observation": 2,
    "core.inspection.record": 5,
    "core.vision.roi": 6,
    "core.vision.region": 12,
    "core.vision.geometry": 5,
    "core.vision.position": 4,
    "core.vision.assembly": 4,
    "core.vision.continuity": 8,
    "core.vision.defect": 8,
    "core.vision.video": 2,
}

EXPECTED_OPENCV_CATEGORY_COUNTS = {
    "opencv.image.color": 6,
    "opencv.image.enhancement": 7,
    "opencv.image.filter": 6,
    "opencv.image.edge": 4,
    "opencv.image.threshold": 4,
    "opencv.image.transform": 22,
    "opencv.mask.operation": 7,
    "opencv.mask.morphology": 2,
    "opencv.segmentation.image": 4,
    "opencv.segmentation.region": 5,
    "opencv.feature.detection": 6,
    "opencv.matching.feature": 3,
    "opencv.matching.template": 4,
    "opencv.matching.registration": 4,
    "opencv.geometry.detection": 7,
    "opencv.geometry.contour": 5,
    "opencv.geometry.shape": 18,
    "opencv.calibration.camera": 10,
    "opencv.calibration.pose": 6,
    "opencv.measurement.edge": 5,
    "opencv.measurement.circle": 4,
    "opencv.measurement.geometry": 11,
    "opencv.inspection.statistics": 4,
    "opencv.inspection.batch": 5,
    "opencv.inspection.difference": 7,
    "opencv.output.render": 13,
    "opencv.output.workflow": 2,
}

_TWO_LEVEL_CATEGORY_PATTERN = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+(?:-[a-z0-9]+)*$"
)
_HAN_PATTERN = re.compile(r"[\u3400-\u9fff]")


def test_core_catalog_uses_confirmed_two_level_taxonomy() -> None:
    """验证 219 个 Core 节点完整落入严格两级分类。"""

    definitions = get_core_workflow_node_definitions()
    category_counts = Counter(item.category for item in definitions)

    assert len(definitions) == 219
    assert category_counts == EXPECTED_CORE_CATEGORY_COUNTS
    assert all(
        _TWO_LEVEL_CATEGORY_PATTERN.fullmatch(item.category) for item in definitions
    )
    assert all("/" not in item.category for item in definitions)


def test_opencv_catalog_uses_confirmed_two_level_taxonomy_and_english_names() -> None:
    """验证 181 个 OpenCV 节点分类完整且节点标题固定为英文。"""

    catalog = build_custom_node_catalog_document()
    category_counts = Counter(item.category for item in catalog.node_definitions)

    assert len(catalog.node_definitions) == 181
    assert category_counts == EXPECTED_OPENCV_CATEGORY_COUNTS
    assert all(
        _TWO_LEVEL_CATEGORY_PATTERN.fullmatch(item.category)
        for item in catalog.node_definitions
    )
    assert all("/" not in item.category for item in catalog.node_definitions)
    assert min(category_counts.values()) >= 2
    assert all(
        not _HAN_PATTERN.search(item.display_name) for item in catalog.node_definitions
    )
    assert all(
        "display_name" not in item.metadata.get("i18n", {})
        for item in catalog.node_definitions
        if isinstance(item.metadata.get("i18n"), dict)
    )
    assert {item.node_pack_version for item in catalog.node_definitions} == {"0.1.3"}
