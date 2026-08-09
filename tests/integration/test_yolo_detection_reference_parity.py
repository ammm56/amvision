"""YOLOv8/11/26 detection 与开发参考仓库的数值一致性测试。

该测试只在开发机同时存在 ``projectsrc/ultralytics`` 和对应预训练权重时执行，
不会让产品运行时依赖参考仓库。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_ROOT = ROOT / "projectsrc" / "ultralytics"


@dataclass(frozen=True)
class _FamilyCase:
    """描述单个 YOLO family 的参考一致性入口。"""

    name: str
    checkpoint: Path
    build_model: Any
    load_checkpoint: Any
    compute_loss: Any
    target_type: Any
    end2end: bool = False


def _load_family_cases() -> tuple[_FamilyCase, ...]:
    """延迟导入项目实现，避免参考资源缺失时污染默认测试。"""

    from backend.service.application.models.yolo11_core import (
        build_yolo11_model,
        load_yolo11_checkpoint_file,
    )
    from backend.service.application.models.yolo11_core.data.detection import (
        Yolo11DetectionPreparedTarget,
    )
    from backend.service.application.models.yolo11_core.losses import (
        compute_yolo11_detection_loss,
    )
    from backend.service.application.models.yolo26_core import (
        build_yolo26_model,
        load_yolo26_checkpoint_file,
    )
    from backend.service.application.models.yolo26_core.data.detection import (
        Yolo26DetectionPreparedTarget,
    )
    from backend.service.application.models.yolo26_core.training.detection import (
        compute_yolo26_detection_training_loss,
    )
    from backend.service.application.models.yolov8_core import (
        build_yolov8_model,
        load_yolov8_checkpoint_file,
    )
    from backend.service.application.models.yolov8_core.data.detection_types import (
        YoloV8DetectionPreparedTarget,
    )
    from backend.service.application.models.yolov8_core.losses import (
        compute_yolov8_detection_loss,
    )

    pretrained_root = ROOT / "data" / "files" / "models" / "pretrained"
    return (
        _FamilyCase(
            name="yolov8",
            checkpoint=pretrained_root
            / "yolov8/detection/m/default/checkpoints/yolov8m.pt",
            build_model=build_yolov8_model,
            load_checkpoint=load_yolov8_checkpoint_file,
            compute_loss=compute_yolov8_detection_loss,
            target_type=YoloV8DetectionPreparedTarget,
        ),
        _FamilyCase(
            name="yolo11",
            checkpoint=pretrained_root
            / "yolo11/detection/m/default/checkpoints/yolo11m.pt",
            build_model=build_yolo11_model,
            load_checkpoint=load_yolo11_checkpoint_file,
            compute_loss=compute_yolo11_detection_loss,
            target_type=Yolo11DetectionPreparedTarget,
        ),
        _FamilyCase(
            name="yolo26",
            checkpoint=pretrained_root
            / "yolo26/detection/m/default/checkpoints/yolo26m.pt",
            build_model=build_yolo26_model,
            load_checkpoint=load_yolo26_checkpoint_file,
            compute_loss=compute_yolo26_detection_training_loss,
            target_type=Yolo26DetectionPreparedTarget,
            end2end=True,
        ),
    )


@pytest.mark.skipif(
    not REFERENCE_ROOT.is_dir(),
    reason="开发参考仓库 projectsrc/ultralytics 不存在",
)
@pytest.mark.parametrize("family_index", [0, 1, 2])
def test_detection_core_forward_and_loss_match_reference(family_index: int) -> None:
    """验证模型图、预训练权重、head 输出和 detection loss 逐项一致。"""

    torch = pytest.importorskip("torch")
    family = _load_family_cases()[family_index]
    if not family.checkpoint.is_file():
        pytest.skip(f"缺少开发预训练权重: {family.checkpoint}")

    sys.path.insert(0, str(REFERENCE_ROOT))
    try:
        from ultralytics import YOLO

        reference_model = YOLO(str(family.checkpoint)).model.float()
    finally:
        sys.path.remove(str(REFERENCE_ROOT))
    reference_model.args = SimpleNamespace(
        **dict(reference_model.args),
        box=7.5,
        cls=0.5,
        dfl=1.5,
        epochs=200,
    )
    reference_model.criterion = reference_model.init_criterion()
    reference_model.train()

    project_model = family.build_model(
        task_type="detection",
        model_scale="m",
        num_classes=80,
    ).float()
    load_result = family.load_checkpoint(
        torch_module=torch,
        model=project_model,
        checkpoint_path=family.checkpoint,
        minimum_loadable_ratio=1.0,
        strict_shape=True,
    )
    project_model.train()

    assert load_result.coverage.loadable_ratio == pytest.approx(1.0)
    project_state_keys = set(project_model.state_dict())
    reference_only_keys = set(reference_model.state_dict()) - project_state_keys
    # v8/11 参考实现把固定 DFL projection 注册成冻结 Conv parameter；项目实现
    # 以等价 buffer 保存，避免它进入 optimizer，数值前向保持一致。
    assert reference_only_keys in (
        set(),
        {f"model.{len(project_model.model) - 1}.dfl.conv.weight"},
    )
    reference_parameter_count = sum(p.numel() for p in reference_model.parameters())
    project_parameter_count = sum(p.numel() for p in project_model.parameters())
    assert reference_parameter_count - project_parameter_count in {0, 16}

    torch.manual_seed(123)
    image = torch.randn(1, 3, 128, 128)
    reference_output = reference_model(image)
    project_output = project_model(image)
    _assert_raw_outputs_close(
        torch_module=torch,
        reference_output=reference_output,
        project_output=project_output,
        end2end=family.end2end,
    )

    reference_batch = {
        "batch_idx": torch.tensor([0]),
        "cls": torch.tensor([[2.0]]),
        "bboxes": torch.tensor([[0.5, 0.5, 0.5, 0.5]]),
    }
    project_target = (
        family.target_type(
            image_id=1,
            image_width=128,
            image_height=128,
            boxes_xyxy=((32.0, 32.0, 96.0, 96.0),),
            category_indexes=(2,),
        ),
    )
    if family.end2end:
        reference_loss, reference_components = reference_model.criterion(
            reference_output,
            reference_batch,
        )
        reference_loss = reference_loss.sum()
        project_loss_payload = family.compute_loss(
            torch_module=torch,
            model=project_model,
            raw_outputs=project_output,
            batch_targets=project_target,
            class_loss_weight=0.5,
            box_loss_weight=7.5,
            dfl_loss_weight=1.5,
            assign_topk=10,
            assign_alpha=0.5,
            assign_beta=6.0,
            epoch=1,
            max_epochs=200,
        )
    else:
        reference_loss, reference_components = reference_model.criterion.loss(
            reference_output,
            reference_batch,
        )
        reference_loss = reference_loss.sum()
        project_loss_payload = family.compute_loss(
            torch_module=torch,
            detect_head=project_model.model[-1],
            raw_outputs=project_output,
            batch_targets=project_target,
            class_loss_weight=0.5,
            box_loss_weight=7.5,
            dfl_loss_weight=1.5,
            assign_topk=10,
            assign_alpha=0.5,
            assign_beta=6.0,
        )
    torch.testing.assert_close(
        project_loss_payload["loss"],
        reference_loss,
        rtol=2e-5,
        atol=2e-5,
    )
    component_names = (
        ("box_loss", "box_loss"),
        ("class_loss", "cls_loss"),
        ("dfl_loss", "l1_loss" if family.end2end else "dfl_loss"),
    )
    for project_name, reference_name in component_names:
        torch.testing.assert_close(
            project_loss_payload[project_name],
            reference_components[reference_name],
            rtol=2e-5,
            atol=2e-5,
        )


def _assert_raw_outputs_close(
    *,
    torch_module: Any,
    reference_output: dict[str, Any],
    project_output: dict[str, Any],
    end2end: bool,
) -> None:
    """比较普通或 end-to-end head 的原始 boxes/scores。"""

    branches = ("one2many", "one2one") if end2end else (None,)
    for branch in branches:
        reference_branch = reference_output if branch is None else reference_output[branch]
        project_branch = project_output if branch is None else project_output[branch]
        for key in ("boxes", "scores"):
            torch_module.testing.assert_close(
                project_branch[key],
                reference_branch[key],
                rtol=2e-5,
                atol=2e-4,
            )
