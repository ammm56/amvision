"""恢复边界必须同时保持权重、优化器、调度器、EMA 与训练历史。"""
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest
import torch

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolov8_core.training.checkpoint import build_yolov8_detection_checkpoint_state
from backend.service.application.models.yolov8_core.training.resume import (
    YoloV8DetectionResumeValidationRequest, load_yolov8_detection_resume_checkpoint,
)


def _objects():
    """小网络只验证状态持久化语义，不作为检测模型精度验收。"""
    model = torch.nn.Linear(3, 2)
    optimizer = torch.optim.SGD(model.parameters(), lr=.01, momentum=.9)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=1, gamma=.8)
    scaler = torch.amp.GradScaler('cpu', enabled=False)
    return SimpleNamespace(model=model, optimizer=optimizer, scheduler=scheduler, scaler=scaler)


def _step(objects):
    """固定输入下一步梯度和 momentum 必须在恢复前后相同。"""
    objects.optimizer.zero_grad()
    loss = objects.model(torch.tensor([[.1, .2, .3]])).square().sum()
    loss.backward()
    objects.optimizer.step()
    objects.scheduler.step()
    return loss.detach()


def _checkpoint(objects):
    """通过正式 checkpoint builder 生成完整状态与类别信息。"""
    request = YoloV8DetectionResumeValidationRequest(
        model_type='yolov8', model_scale='nano', num_classes=2, input_size=(64, 64),
        batch_size=2, max_epochs=3, precision='fp32', validation_split_name='val',
        evaluation_interval=1, evaluation_confidence_threshold=.001, evaluation_nms_threshold=.7,
        learning_rate=.01, weight_decay=0., class_loss_weight=.5, box_loss_weight=7.5,
        dfl_loss_weight=1.5, assign_topk=10, assign_alpha=.5, assign_beta=6., min_lr_ratio=.01, grad_clip_norm=10.,
    )
    options = asdict(request)
    options.pop('num_classes')
    state = build_yolov8_detection_checkpoint_state(
        **options, model=objects.model, ema_model=deepcopy(objects.model), ema_updates=7,
        optimizer=objects.optimizer, scheduler=objects.scheduler, scaler=objects.scaler,
        category_names=('first', 'second'), epoch=1, metrics_history=[{'epoch': 1, 'loss': .3}],
        validation_history=[{'epoch': 1, 'map50_95': .2}], evaluated_epochs=(1,),
        warm_start_summary={'enabled': False}, implementation_mode='yolov8-detection-core',
        augmentation_options={}, best_metric_name='map50_95', best_metric_value=.2,
        best_checkpoint_state=None,
    )
    return state, {'expected_' + key: value for key, value in asdict(request).items()}


def test_resume_next_optimizer_step_and_metadata_are_preserved(tmp_path):
    """恢复后的下一步权重逐元素一致，验证历史、类别和 EMA 不能丢失。"""
    original = _objects()
    _step(original)
    state, expected = _checkpoint(original)
    path = tmp_path / 'resume.pt'
    torch.save(state, path)
    restored = _objects()
    result = load_yolov8_detection_resume_checkpoint(torch_module=torch, checkpoint_path=path,
                                                    **vars(restored), **expected)
    assert result.resume_epoch == 1
    assert result.ema_updates == 7
    assert result.evaluated_epochs == (1,)
    assert result.validation_history == [{'epoch': 1, 'map50_95': .2}]
    assert state['category_names'] == ['first', 'second']
    assert torch.equal(_step(original), _step(restored))
    assert all(torch.equal(value, restored.model.state_dict()[key]) for key, value in original.model.state_dict().items())


def test_resume_rejects_incompatible_class_count_before_loading_weights(tmp_path):
    """不匹配的类别配置被拒绝，目标网络保持未修改。"""
    state, expected = _checkpoint(_objects())
    path = tmp_path / 'resume.pt'
    torch.save(state, path)
    restored = _objects()
    before = deepcopy(restored.model.state_dict())
    expected['expected_num_classes'] = 3
    with pytest.raises(InvalidRequestError):
        load_yolov8_detection_resume_checkpoint(torch_module=torch, checkpoint_path=path, **vars(restored), **expected)
    assert all(torch.equal(value, restored.model.state_dict()[key]) for key, value in before.items())
