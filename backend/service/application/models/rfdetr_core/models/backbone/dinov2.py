import json
import math
import os
import types

import torch
import torch.nn as nn
import torch.nn.functional as F  # noqa: N812

from backend.service.application.models.rfdetr_core.models.backbone.dinov2_with_windowed_attn import (
    WindowedDinov2WithRegistersBackbone,
    WindowedDinov2WithRegistersConfig,
)
from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

logger = get_logger()

size_to_width = {
    "tiny": 192,
    "small": 384,
    "base": 768,
    "large": 1024,
}

size_to_config = {
    "small": "dinov2_small.json",
    "base": "dinov2_base.json",
    "large": "dinov2_large.json",
}

size_to_config_with_registers = {
    "small": "dinov2_with_registers_small.json",
    "base": "dinov2_with_registers_base.json",
    "large": "dinov2_with_registers_large.json",
}


def get_config(size, use_registers):
    config_dict = size_to_config_with_registers if use_registers else size_to_config
    current_dir = os.path.dirname(os.path.abspath(__file__))
    configs_dir = os.path.join(current_dir, "dinov2_configs")
    config_path = os.path.join(configs_dir, config_dict[size])
    with open(config_path, "r") as f:
        dino_config = json.load(f)
    return dino_config


class DinoV2(nn.Module):
    def __init__(
        self,
        shape=(640, 640),
        out_feature_indexes=[2, 4, 5, 9],
        size="base",
        use_registers=True,
        use_windowed_attn=True,
        gradient_checkpointing=False,
        load_dinov2_weights=True,
        patch_size=14,
        num_windows=4,
        positional_encoding_size=37,
        drop_path_rate=0.0,
    ):
        super().__init__()

        self.shape = shape
        self.patch_size = patch_size
        self.num_windows = num_windows


        if not use_windowed_attn:
            raise ValueError(
                "当前 RF-DETR core 不启用 HuggingFace AutoBackbone 在线加载路径。"
                "请使用 windowed DINOv2 backbone，并通过本项目本地 RF-DETR checkpoint 加载权重。"
            )
        if load_dinov2_weights:
            raise ValueError(
                "当前 RF-DETR core 不从 HuggingFace 下载 DINOv2 预训练权重。"
                "请提供本地 RF-DETR checkpoint，或设置 force_no_pretrain=True 从零初始化。"
            )

        window_block_indexes = set(range(out_feature_indexes[-1] + 1))
        window_block_indexes.difference_update(out_feature_indexes)
        window_block_indexes = list(window_block_indexes)

        dino_config = get_config(size, use_registers)

        dino_config["return_dict"] = False
        dino_config["out_features"] = [f"stage{i}" for i in out_feature_indexes]
        dino_config["drop_path_rate"] = drop_path_rate

        implied_resolution = positional_encoding_size * patch_size

        if implied_resolution != dino_config["image_size"]:
            logger.warning(
                "RF-DETR core 使用的 positional encoding 数量和 DINOv2 默认配置不同，"
                "将按当前 RF-DETR 配置初始化 backbone。"
            )
            dino_config["image_size"] = implied_resolution

        if patch_size != 14:
            logger.warning(
                "RF-DETR core 使用 patch size %s，而不是 DINOv2 默认 14；"
                "将按当前 RF-DETR 配置初始化 backbone。",
                patch_size,
            )
            dino_config["patch_size"] = patch_size

        if use_registers:
            windowed_dino_config = WindowedDinov2WithRegistersConfig(
                **dino_config,
                num_windows=num_windows,
                window_block_indexes=window_block_indexes,
                gradient_checkpointing=gradient_checkpointing,
            )
        else:
            windowed_dino_config = WindowedDinov2WithRegistersConfig(
                **dino_config,
                num_windows=num_windows,
                window_block_indexes=window_block_indexes,
                num_register_tokens=0,
                gradient_checkpointing=gradient_checkpointing,
            )
        self.encoder = WindowedDinov2WithRegistersBackbone(windowed_dino_config)

        self._out_feature_channels = [size_to_width[size]] * len(out_feature_indexes)
        self._export = False

    def export(self):
        if self._export:
            return
        self._export = True
        shape = self.shape

        def make_new_interpolated_pos_encoding(position_embeddings, patch_size, height, width):

            num_positions = position_embeddings.shape[1] - 1
            dim = position_embeddings.shape[-1]
            height = height // patch_size
            width = width // patch_size

            class_pos_embed = position_embeddings[:, 0]
            patch_pos_embed = position_embeddings[:, 1:]

            patch_pos_embed = patch_pos_embed.reshape(
                1, int(math.sqrt(num_positions)), int(math.sqrt(num_positions)), dim
            )
            patch_pos_embed = patch_pos_embed.permute(0, 3, 1, 2)

            patch_pos_embed = F.interpolate(
                patch_pos_embed,
                size=(height, width),
                mode="bicubic",
                align_corners=False,
                antialias=False,
            )

            patch_pos_embed = patch_pos_embed.permute(0, 2, 3, 1).reshape(1, -1, dim)
            return torch.cat((class_pos_embed.unsqueeze(0), patch_pos_embed), dim=1)

        with torch.no_grad():
            new_positions = make_new_interpolated_pos_encoding(
                self.encoder.embeddings.position_embeddings,
                self.encoder.config.patch_size,
                shape[0],
                shape[1],
            )
        old_interpolate_pos_encoding = self.encoder.embeddings.interpolate_pos_encoding

        def new_interpolate_pos_encoding(self_mod, embeddings, height, width):
            num_patches = embeddings.shape[1] - 1
            num_positions = self_mod.position_embeddings.shape[1] - 1
            if num_patches == num_positions and height == width:
                return self_mod.position_embeddings
            return old_interpolate_pos_encoding(embeddings, height, width)

        self.encoder.embeddings.position_embeddings = nn.Parameter(new_positions)
        self.encoder.embeddings.interpolate_pos_encoding = types.MethodType(
            new_interpolate_pos_encoding, self.encoder.embeddings
        )

    def forward(self, x):
        block_size = self.patch_size * self.num_windows
        assert x.shape[2] % block_size == 0 and x.shape[3] % block_size == 0, (
            f"Backbone requires input shape to be divisible by {block_size}, but got {x.shape}"
        )
        x = self.encoder(x)
        return list(x[0])


if __name__ == "__main__":
    model = DinoV2()
    model.export()
    x = torch.randn(1, 3, 640, 640)
    logger.info(model(x))
    for j in model(x):
        logger.info(j.shape)
