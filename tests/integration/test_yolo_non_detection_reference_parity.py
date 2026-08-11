"""YOLO 非 detection 任务与开发参考仓库的数值一致性测试。

该测试仅在开发机存在 ``projectsrc/ultralytics`` 和 M 规格预训练权重时运行；
产品运行时不导入参考仓库。
"""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_ROOT = ROOT / "projectsrc" / "ultralytics"
PRETRAINED_ROOT = ROOT / "data" / "files" / "models" / "pretrained"
FAMILIES = ("yolov8", "yolo11", "yolo26")


def _load_project_family(family: str) -> tuple[Any, Any]:
    """返回 family 对应的模型构建与 checkpoint 加载入口。"""

    if family == "yolov8":
        from backend.service.application.models.yolov8_core import (
            build_yolov8_model,
            load_yolov8_checkpoint_file,
        )

        return build_yolov8_model, load_yolov8_checkpoint_file
    if family == "yolo11":
        from backend.service.application.models.yolo11_core import (
            build_yolo11_model,
            load_yolo11_checkpoint_file,
        )

        return build_yolo11_model, load_yolo11_checkpoint_file
    from backend.service.application.models.yolo26_core import (
        build_yolo26_model,
        load_yolo26_checkpoint_file,
    )

    return build_yolo26_model, load_yolo26_checkpoint_file


def _load_models(*, family: str, task: str, torch_module: Any) -> tuple[Any, Any, Any]:
    """加载同一 checkpoint 的参考模型与项目模型。"""

    suffix = {
        "classification": "-cls",
        "segmentation": "-seg",
        "pose": "-pose",
        "obb": "-obb",
    }[task]
    checkpoint = (
        PRETRAINED_ROOT
        / family
        / task
        / "m"
        / "default"
        / "checkpoints"
        / f"{family}m{suffix}.pt"
    )
    if not checkpoint.is_file():
        pytest.skip(f"缺少开发预训练权重: {checkpoint}")

    sys.path.insert(0, str(REFERENCE_ROOT))
    try:
        from ultralytics import YOLO

        reference_model = YOLO(str(checkpoint)).model.float()
    finally:
        sys.path.remove(str(REFERENCE_ROOT))
    num_classes = int(getattr(reference_model.model[-1], "nc", len(reference_model.names)))
    overrides: dict[str, object] = {}
    if hasattr(reference_model.model[-1], "kpt_shape"):
        overrides["kpt_shape"] = list(reference_model.model[-1].kpt_shape)
    build_model, load_checkpoint = _load_project_family(family)
    project_model = build_model(
        task_type=task,
        model_scale="m",
        num_classes=num_classes,
        model_config_overrides=overrides or None,
    ).float()
    result = load_checkpoint(
        torch_module=torch_module,
        model=project_model,
        checkpoint_path=checkpoint,
        minimum_loadable_ratio=1.0,
        strict_shape=True,
    )
    assert result.coverage.loadable_ratio == pytest.approx(1.0)
    return reference_model, project_model, num_classes


def _configure_reference(reference_model: Any, **overrides: object) -> None:
    """配置参考 criterion 使用的固定超参数。"""

    reference_model.args = SimpleNamespace(
        **dict(reference_model.args),
        box=7.5,
        cls=0.5,
        dfl=1.5,
        epochs=200,
        **overrides,
    )
    reference_model.criterion = reference_model.init_criterion()
    reference_model.train()


def _assert_common_raw_outputs_close(
    *,
    torch_module: Any,
    reference_output: Any,
    project_output: Any,
    end2end: bool,
    keys: tuple[str, ...],
) -> None:
    """比较普通或 end-to-end head 的共有 raw tensor。"""

    branches = ("one2many", "one2one") if end2end else (None,)
    for branch in branches:
        reference_branch = reference_output if branch is None else reference_output[branch]
        project_branch = project_output if branch is None else project_output[branch]
        for key in keys:
            torch_module.testing.assert_close(
                project_branch[key],
                reference_branch[key],
                rtol=2e-4,
                atol=2e-3,
            )


@pytest.mark.skipif(
    not REFERENCE_ROOT.is_dir(),
    reason="开发参考仓库 projectsrc/ultralytics 不存在",
)
@pytest.mark.parametrize("family", FAMILIES)
def test_classification_forward_and_loss_match_reference(family: str) -> None:
    """验证 classification logits、概率契约和 cross entropy 一致。"""

    torch = pytest.importorskip("torch")
    reference, project, _ = _load_models(
        family=family,
        task="classification",
        torch_module=torch,
    )
    _configure_reference(reference)
    project.train()
    torch.manual_seed(123)
    image = torch.randn(2, 3, 64, 64)
    reference_output = reference(image)
    project_output = project(image)
    torch.testing.assert_close(project_output, reference_output, rtol=2e-4, atol=2e-4)

    if family == "yolov8":
        from backend.service.application.models.yolov8_core.losses import (
            compute_yolov8_classification_loss as compute_loss,
        )
    elif family == "yolo11":
        from backend.service.application.models.yolo11_core.losses import (
            compute_yolo11_classification_loss as compute_loss,
        )
    else:
        from backend.service.application.models.yolo26_core.losses import (
            compute_yolo26_classification_loss as compute_loss,
        )
    targets = torch.tensor([0, 1], dtype=torch.long)
    reference_loss, _ = reference.criterion(reference_output, {"cls": targets})
    project_loss, probabilities = compute_loss(
        torch_module=torch,
        outputs=project_output,
        targets=targets,
    )
    torch.testing.assert_close(project_loss, reference_loss, rtol=2e-5, atol=2e-5)
    torch.testing.assert_close(probabilities, project_output.softmax(1))


@pytest.mark.skipif(
    not REFERENCE_ROOT.is_dir(),
    reason="开发参考仓库 projectsrc/ultralytics 不存在",
)
@pytest.mark.parametrize("family", FAMILIES)
def test_pose_forward_and_loss_match_reference(family: str) -> None:
    """验证 pose head、TAL、OKS/keypoint/RLE loss 一致。"""

    torch = pytest.importorskip("torch")
    reference, project, num_classes = _load_models(
        family=family,
        task="pose",
        torch_module=torch,
    )
    _configure_reference(reference, pose=12.0, kobj=1.0, rle=1.0)
    project.train()
    torch.manual_seed(123)
    image = torch.randn(1, 3, 128, 128)
    reference_output = reference(image)
    project_output = project(image)
    _assert_common_raw_outputs_close(
        torch_module=torch,
        reference_output=reference_output,
        project_output=project_output,
        end2end=family == "yolo26",
        keys=("boxes", "scores", "kpts"),
    )
    normalized_keypoints = torch.tensor([[[0.5, 0.5, 2.0]] * 17])
    reference_batch = {
        "batch_idx": torch.tensor([0]),
        "cls": torch.tensor([[0.0]]),
        "bboxes": torch.tensor([[0.5, 0.5, 0.5, 0.5]]),
        "keypoints": normalized_keypoints,
    }
    flat_keypoints = [value for _ in range(17) for value in (64.0, 64.0, 2.0)]
    if family == "yolov8":
        from backend.service.application.models.yolov8_core.data.pose import (
            YoloV8PosePreparedTarget as Target,
        )
        from backend.service.application.models.yolov8_core.losses import (
            compute_yolov8_pose_loss as compute_loss,
        )
    elif family == "yolo11":
        from backend.service.application.models.yolo11_core.data.pose import (
            Yolo11PosePreparedTarget as Target,
        )
        from backend.service.application.models.yolo11_core.losses import (
            compute_yolo11_pose_loss as compute_loss,
        )
    else:
        from backend.service.application.models.yolo26_core.data.pose import (
            Yolo26PosePreparedTarget as Target,
        )
        from backend.service.application.models.yolo26_core.losses import (
            combine_yolo26_end2end_loss_payloads,
            compute_yolo26_pose_loss as compute_loss,
            resolve_yolo26_end2end_loss_weights,
        )
    project_targets = (
        Target(
            boxes_xyxy=[[32.0, 32.0, 96.0, 96.0]],
            category_indexes=[0],
            keypoints=[flat_keypoints],
        ),
    )
    if family == "yolo26":
        reference_loss, reference_components = reference.criterion(
            reference_output,
            reference_batch,
        )
        one2many = compute_loss(
            torch=torch,
            model=project,
            raw_outputs=project_output["one2many"],
            batch_targets=project_targets,
            num_classes=num_classes,
        )
        one2one = compute_loss(
            torch=torch,
            model=project,
            raw_outputs=project_output["one2one"],
            batch_targets=project_targets,
            num_classes=num_classes,
            assign_topk=7,
            assign_topk2=1,
        )
        weights = resolve_yolo26_end2end_loss_weights(epoch=1, max_epochs=200)
        payload = combine_yolo26_end2end_loss_payloads(
            one2many_payload=one2many,
            one2one_payload=one2one,
            one2many_weight=weights[0],
            one2one_weight=weights[1],
        )
    else:
        reference_loss, reference_components = reference.criterion.loss(
            reference_output,
            reference_batch,
        )
        payload = compute_loss(
            torch=torch,
            model=project,
            raw_outputs=project_output,
            batch_targets=project_targets,
            num_classes=num_classes,
        )
    torch.testing.assert_close(payload["loss"], reference_loss.sum(), rtol=2e-5, atol=5e-5)
    assert all(torch.isfinite(value).all() for value in payload.values() if torch.is_tensor(value))
    assert all(torch.isfinite(value).all() for value in reference_components.values())


@pytest.mark.skipif(
    not REFERENCE_ROOT.is_dir(),
    reason="开发参考仓库 projectsrc/ultralytics 不存在",
)
@pytest.mark.parametrize("family", FAMILIES)
def test_obb_loss_matches_reference(family: str) -> None:
    """验证 OBB rotated TAL、ProbIoU、DFL/L1 与 angle loss 一致。"""

    torch = pytest.importorskip("torch")
    reference, project, num_classes = _load_models(
        family=family,
        task="obb",
        torch_module=torch,
    )
    _configure_reference(reference, angle=1.0)
    project.train()
    torch.manual_seed(123)
    image = torch.randn(1, 3, 128, 128)
    reference_output = reference(image)
    project_output = project(image)
    # v8/11 的项目 head 保留 angle logits，并在 loss 内解码；参考训练态
    # head 直接返回解码角度。因此这里只比较同语义的 box/class raw 输出。
    _assert_common_raw_outputs_close(
        torch_module=torch,
        reference_output=reference_output,
        project_output=project_output,
        end2end=family == "yolo26",
        keys=("boxes", "scores"),
    )
    reference_batch = {
        "batch_idx": torch.tensor([0]),
        "cls": torch.tensor([[2.0]]),
        "bboxes": torch.tensor([[0.5, 0.5, 0.5, 0.25, 0.25]]),
    }
    if family == "yolov8":
        from backend.service.application.models.yolov8_core.data.obb import (
            YoloV8ObbPreparedTarget as Target,
        )
        from backend.service.application.models.yolov8_core.losses import (
            compute_yolov8_obb_loss as compute_loss,
        )
    elif family == "yolo11":
        from backend.service.application.models.yolo11_core.data.obb import (
            Yolo11ObbPreparedTarget as Target,
        )
        from backend.service.application.models.yolo11_core.losses import (
            compute_yolo11_obb_loss as compute_loss,
        )
    else:
        from backend.service.application.models.yolo26_core.data.obb import (
            Yolo26ObbPreparedTarget as Target,
        )
        from backend.service.application.models.yolo26_core.losses import (
            combine_yolo26_end2end_loss_payloads,
            compute_yolo26_obb_loss as compute_loss,
            resolve_yolo26_end2end_loss_weights,
        )
    project_targets = (
        Target(
            boxes_xywhr=[[64.0, 64.0, 64.0, 32.0, 0.25]],
            category_indexes=[2],
        ),
    )
    if family == "yolo26":
        reference_loss, _ = reference.criterion(reference_output, reference_batch)
        one2many = compute_loss(
            torch=torch,
            model=project,
            raw_outputs=project_output["one2many"],
            batch_targets=project_targets,
            num_classes=num_classes,
        )
        one2one = compute_loss(
            torch=torch,
            model=project,
            raw_outputs=project_output["one2one"],
            batch_targets=project_targets,
            num_classes=num_classes,
            assign_topk=7,
            assign_topk2=1,
        )
        weights = resolve_yolo26_end2end_loss_weights(epoch=1, max_epochs=200)
        payload = combine_yolo26_end2end_loss_payloads(
            one2many_payload=one2many,
            one2one_payload=one2one,
            one2many_weight=weights[0],
            one2one_weight=weights[1],
        )
    else:
        reference_loss, _ = reference.criterion.loss(reference_output, reference_batch)
        payload = compute_loss(
            torch=torch,
            model=project,
            raw_outputs=project_output,
            batch_targets=project_targets,
            num_classes=num_classes,
        )
    torch.testing.assert_close(payload["loss"], reference_loss.sum(), rtol=2e-5, atol=5e-5)


def _adapt_segmentation_output_for_reference(value: Any) -> Any:
    """把项目 segmentation raw key 适配为参考 criterion 的输入契约。"""

    if not isinstance(value, dict):
        return value
    result = {
        key: _adapt_segmentation_output_for_reference(child)
        for key, child in value.items()
        if key != "semseg"
    }
    if isinstance(result.get("feats"), tuple):
        result["feats"] = list(result["feats"])
    if "mask_coefficients" in result:
        result["mask_coefficient"] = result.pop("mask_coefficients")
    if "semseg" in value:
        result["proto"] = (result["proto"], value["semseg"])
    return result


def _compute_v8_segmentation_payload(
    *,
    torch_module: Any,
    model: Any,
    raw_outputs: dict[str, Any],
    targets: list[dict[str, Any]],
    num_classes: int,
) -> dict[str, Any]:
    """调用 YOLOv8 segmentation 的 core assigner/loss 边界。"""

    from backend.service.application.models.yolo_core_common.geometry import make_anchors
    from backend.service.application.models.yolov8_core.assigners import (
        assign_yolov8_segmentation_targets,
    )
    from backend.service.application.models.yolov8_core.losses import (
        compute_yolov8_segmentation_detection_loss,
        compute_yolov8_segmentation_mask_loss,
    )

    head = model.model[-1]
    anchors, strides = make_anchors(
        feature_maps=raw_outputs["feats"],
        strides=tuple(int(value) for value in head.strides),
    )
    decoded = head.dfl(raw_outputs["boxes"])
    predictions = torch_module.cat(
        (
            decoded.permute(0, 2, 1),
            raw_outputs["scores"].permute(0, 2, 1),
            raw_outputs["mask_coefficients"].permute(0, 2, 1),
        ),
        dim=-1,
    ).contiguous()
    distance_logits = raw_outputs["boxes"].permute(0, 2, 1).contiguous()
    assignment = assign_yolov8_segmentation_targets(
        torch_module=torch_module,
        targets=targets[0],
        prediction=predictions[0],
        anchor_points=anchors,
        stride_tensor=strides,
        topk=10,
        alpha=0.5,
        beta=6.0,
        num_classes=num_classes,
    )
    class_loss, box_loss, dfl_loss = compute_yolov8_segmentation_detection_loss(
        torch_module=torch_module,
        prediction=predictions[0],
        assignment=assignment,
        anchor_points=anchors,
        stride_tensor=strides,
        dfl_weight=1.5,
        num_classes=num_classes,
        distance_logits=distance_logits[0],
        reg_max=int(head.reg_max),
    )
    mask_loss = compute_yolov8_segmentation_mask_loss(
        torch_module=torch_module,
        prediction=predictions[0],
        proto=raw_outputs["proto"][0],
        foreground_mask=assignment.fg_mask,
        target_masks=assignment.mask_targets,
        target_mask_valid=assignment.mask_valid,
        matched_gt_indices=assignment.matched_gt_indices,
        num_classes=num_classes,
        target_boxes=assignment.box_targets,
        image_size=(128, 128),
    )
    return {
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
        "mask_loss": mask_loss,
        "semantic_loss": box_loss * 0.0,
    }


@pytest.mark.skipif(
    not REFERENCE_ROOT.is_dir(),
    reason="开发参考仓库 projectsrc/ultralytics 不存在",
)
@pytest.mark.parametrize("family", FAMILIES)
def test_segmentation_loss_matches_reference(family: str) -> None:
    """验证 segmentation TAL、box/DFL、instance mask 与 semantic loss 一致。"""

    torch = pytest.importorskip("torch")
    reference, project, num_classes = _load_models(
        family=family,
        task="segmentation",
        torch_module=torch,
    )
    _configure_reference(reference, overlap_mask=True)
    project.train()
    torch.manual_seed(123)
    image = torch.randn(1, 3, 128, 128)
    reference_output = reference(image)
    project_output = project(image)
    _assert_common_raw_outputs_close(
        torch_module=torch,
        reference_output=reference_output,
        project_output=project_output,
        end2end=family == "yolo26",
        keys=("boxes", "scores"),
    )
    mask = torch.zeros((1, 32, 32), dtype=torch.float32)
    mask[:, 8:24, 8:24] = 1.0
    reference_batch = {
        "batch_idx": torch.tensor([0]),
        "cls": torch.tensor([[0.0]]),
        "bboxes": torch.tensor([[0.5, 0.5, 0.5, 0.5]]),
        "masks": mask,
        "sem_masks": torch.zeros((1, 32, 32), dtype=torch.long),
    }
    targets = [
        {
            "boxes": [[32.0, 32.0, 96.0, 96.0]],
            "class_ids": [0],
            "masks": mask,
            "mask_valid": torch.tensor([True]),
        }
    ]
    reference_input = _adapt_segmentation_output_for_reference(project_output)
    if family == "yolo26":
        reference_loss, reference_components = reference.criterion(
            reference_input,
            reference_batch,
        )
        from backend.service.application.models.training.yolo26_segmentation_training import (
            _compute_yolo26_segmentation_training_loss,
        )

        payload = _compute_yolo26_segmentation_training_loss(
            imports=SimpleNamespace(torch=torch),
            model=project,
            raw_outputs=project_output,
            targets_list=targets,
            stride_values=(8, 16, 32),
            device="cpu",
            num_classes=num_classes,
            assign_topk=10,
            assign_topk2=None,
            assign_alpha=0.5,
            assign_beta=6.0,
            dfl_loss_weight=1.5,
            epoch=1,
            max_epochs=200,
        )
    else:
        reference_loss, reference_components = reference.criterion.loss(
            reference_input,
            reference_batch,
        )
        if family == "yolov8":
            payload = _compute_v8_segmentation_payload(
                torch_module=torch,
                model=project,
                raw_outputs=project_output,
                targets=targets,
                num_classes=num_classes,
            )
        else:
            from backend.service.application.models.training.yolo11_segmentation_training import (
                _compute_yolo11_segmentation_training_loss,
            )

            payload = _compute_yolo11_segmentation_training_loss(
                imports=SimpleNamespace(torch=torch),
                model=project,
                raw_outputs=project_output,
                targets_list=targets,
                stride_values=(8, 16, 32),
                device="cpu",
                num_classes=num_classes,
                assign_topk=10,
                assign_alpha=0.5,
                assign_beta=6.0,
                dfl_loss_weight=1.5,
            )
    weighted_total = (
        payload["box_loss"] * 7.5
        + payload["mask_loss"] * 7.5
        + payload["class_loss"] * 0.5
        + payload["dfl_loss"] * 1.5
        + payload.get("semantic_loss", payload["box_loss"] * 0.0) * 7.5
    )
    torch.testing.assert_close(
        weighted_total.sum(),
        reference_loss.sum(),
        rtol=2e-5,
        atol=5e-5,
    )
    assert all(torch.isfinite(value).all() for value in reference_components.values())
