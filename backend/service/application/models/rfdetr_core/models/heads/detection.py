"""RF-DETR core 模型结构模块：`models.heads.detection`。"""

import torch.nn as nn

from backend.service.application.models.rfdetr_core.models.math import MLP


class DetectionHead(nn.Module):
    """RF-DETR core 类：`DetectionHead`。"""

    def __init__(self, hidden_dim: int, num_classes: int) -> None:
        super().__init__()
        self.class_embed = nn.Linear(hidden_dim, num_classes)
        self.bbox_embed = MLP(hidden_dim, hidden_dim, 4, 3)

    def forward(self, hs):
        """执行 `forward`。
        
        参数：
        - `hs`：传入的 `hs` 参数。
        """
        outputs_class = self.class_embed(hs)
        outputs_coord = self.bbox_embed(hs).sigmoid()
        return outputs_class, outputs_coord
