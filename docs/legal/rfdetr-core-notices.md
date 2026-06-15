# RF-DETR core 来源声明

本文档记录 `backend/service/application/models/rfdetr_core/` 中复制和改写代码的来源。`rfdetr_core` 根目录保留 Apache-2.0 许可证文本，详细来源说明统一放在本文档，代码文件不再逐个保留 SPDX 和来源声明文件头。

## 适用范围

- `backend/service/application/models/rfdetr_core/models/`
- `backend/service/application/models/rfdetr_core/export/_onnx/`
- `backend/service/application/models/rfdetr_core/export/_tensorrt.py`
- `backend/service/application/models/rfdetr_core/training/`
- `backend/service/application/models/rfdetr_core/datasets/`
- `backend/service/application/models/rfdetr_core/evaluation/`
- `backend/service/application/models/rfdetr_core/assets/`
- `backend/service/application/models/rfdetr_core/utilities/`
- `backend/service/application/models/rfdetr_core/visualize/`
- `backend/service/application/models/rfdetr_core/supervision_compat.py`
- `backend/service/application/models/rfdetr_core/config.py`
- `backend/service/application/models/rfdetr_core/_namespace.py`

## 上游项目

- RF-DETR
  - Copyright (c) 2025 Roboflow. All Rights Reserved.
  - Licensed under the Apache License, Version 2.0.
- LW-DETR
  - Copyright (c) 2024 Baidu. All Rights Reserved.
  - Licensed under the Apache License, Version 2.0.
- Conditional DETR
  - Copyright (c) 2021 Microsoft. All Rights Reserved.
  - Licensed under the Apache License, Version 2.0.
- DETR
  - Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved.
- Deformable DETR
  - Copyright (c) 2020 SenseTime. All Rights Reserved.
  - Licensed under the Apache License, Version 2.0.
- Deformable-Convolution-V2-PyTorch
  - 部分 MSDeformAttn 代码路径由 Deformable DETR 继续引用该实现。
- HuggingFace Transformers
  - 部分 DINOv2 windowed attention 代码参考 HuggingFace Transformers 实现。
  - Licensed under the Apache License, Version 2.0.
- ViTDet / Detectron2
  - 部分 projector 结构参考 ViTDet。
  - Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved.
- Supervision
  - `supervision_compat.py` 只参考 `projectsrc/supervision/src/supervision` 的对象边界，按本项目需要重写最小兼容层，不依赖 `supervision` pip 包。

## 本项目修改规则

- 运行时代码不得依赖 `projectsrc/`。
- RF-DETR core 默认只读取本地权重，不做隐式下载。
- 项目新增 docstring 和注释使用中文，专有名词保持英文。
- 当前不启用 `rfdetr_plus`，plus 模型、plus 下载表和 plus 权重查找不属于本项目运行边界。
- 当前不启用 `LightningCLI`，不把 `jsonargparse` 作为项目依赖。
- 当前不启用 LoRA / PEFT 微调，不把 `peft` 作为项目依赖。
- 当前不依赖外部 `supervision` 包，RF-DETR 数据包装、绘图和 ONNX 辅助推理由 `supervision_compat.py` 提供最小实现。
- 当前不保留 `assets/model_weights.py`、`platform/`、`datasets/_develop.py` 或下载 helper，预训练权重由本项目 `data/files/models/pretrained/` 目录显式提供。
- 当前不保留 WandB、MLflow、ClearML、IPython 或 ipywidgets 训练输出分支。
- 如果后续继续复制新的上游文件，需要同步更新本文档。
