"""从真实执行结果生成跨语言读取样本，不手工伪造估计来源。"""

import json
from pathlib import Path

from tests.integration.metrology3d.test_envelope_runtime import (
    fixture,
    extract,
    extents,
)
from tests.integration.metrology3d.workpiece_recipe import envelope, profile_extents
from custom_nodes.metrology3d_nodes.shared.boundary_preview import curve_display
from tests.test_metrology3d_preview import preview_policy
from backend.contracts.workflows.boundary3d_preview import BoundaryDisplay


def main():
    """仅生成回归资产，解析矩形用于契约测试而非真实工件页面验收。"""
    values, params, measured = fixture()
    scope, runtime, cloud, *_ = values
    try:
        group = extract(values, params, measured)
        body = dict(
            observation_id=cloud.observation_id,
            spatial=cloud.spatial.model_dump(mode="json"),
            bounds=dict(min=[0, 0, 0], max=[30, 30, 10]),
            geometry=dict(
                format_id="amvision.geometry-preview.v1",
                observation_id=cloud.observation_id,
                frame_id="fixture",
                length_unit="mm",
                planes=[],
                rois=[],
                frame=None,
                curves=[
                    curve_display(
                        runtime,
                        group.items[0],
                        policy=preview_policy(),
                        remaining_points=1000,
                        cancel=lambda: None,
                    )
                ],
            ),
            measurements=extents(runtime, group).model_dump(mode="json"),
        )
        output = dict(
            boundary=envelope("A_top_L").model_dump(mode="json"),
            dimension=profile_extents("A_top_L").model_dump(mode="json"),
            payload=body,
        )
        body["geometry"]["curves"] = [
            BoundaryDisplay.model_validate(item).model_dump(mode="json")
            for item in body["geometry"]["curves"]
        ]
        path = Path(__file__).parents[2] / "frontend/workflows/fixtures/envelope.json"
        path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    finally:
        assert not scope.close() and runtime.budget.used == 0


if __name__ == "__main__":
    main()
