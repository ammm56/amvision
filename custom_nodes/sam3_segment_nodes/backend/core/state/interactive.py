"""SAM3 interactive 单图运行时状态容器。"""

from __future__ import annotations

from dataclasses import dataclass, field

import torch


@dataclass
class Sam3InteractiveMemoryEntry:
    """描述一帧已编码完成的 memory。"""

    maskmem_features: torch.Tensor
    maskmem_pos_enc: list[torch.Tensor]
    pred_masks: torch.Tensor
    obj_ptr: torch.Tensor
    object_score_logits: torch.Tensor


@dataclass
class Sam3InteractiveImageFeatures:
    """描述单图 interactive 推理所需的图像特征。"""

    vision_feats: list[torch.Tensor]
    vision_pos_embeds: list[torch.Tensor]
    feat_sizes: list[tuple[int, int]]
    high_res_features: list[torch.Tensor]


@dataclass
class Sam3InteractiveState:
    """管理单图 interactive 推理中的对象索引和 memory bank。"""

    max_object_count: int
    hidden_dim: int
    device: torch.device
    torch_dtype: torch.dtype
    object_id_to_index: dict[int, int] = field(default_factory=dict)
    index_to_object_id: dict[int, int] = field(default_factory=dict)
    active_indices: set[int] = field(default_factory=set)
    memory_bank: list[Sam3InteractiveMemoryEntry] = field(default_factory=list)
    image_features: Sam3InteractiveImageFeatures | None = None

    def allocate_object_index(self, object_id: int) -> int:
        """为 object id 分配稳定索引。"""

        normalized_object_id = int(object_id)
        existing_index = self.object_id_to_index.get(normalized_object_id)
        if existing_index is not None:
            return existing_index
        for candidate_index in range(self.max_object_count):
            if candidate_index not in self.index_to_object_id:
                self.object_id_to_index[normalized_object_id] = candidate_index
                self.index_to_object_id[candidate_index] = normalized_object_id
                return candidate_index
        raise RuntimeError(f"SAM3 interactive 状态超出最大对象数限制: {self.max_object_count}")

    def set_image_features(self, image_features: Sam3InteractiveImageFeatures) -> None:
        """写入当前图像特征。"""

        self.image_features = image_features

    def append_memory_entry(self, memory_entry: Sam3InteractiveMemoryEntry) -> None:
        """追加一帧 memory。"""

        self.memory_bank.append(memory_entry)

    def build_memory_attention_inputs(self, *, maskmem_tpos_enc: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """把 memory bank 规整为 memory attention 输入。"""

        to_cat_memory: list[torch.Tensor] = []
        to_cat_memory_pos_embed: list[torch.Tensor] = []
        for memory_entry in self.memory_bank:
            to_cat_memory.append(memory_entry.maskmem_features.flatten(2).permute(2, 0, 1))
            memory_pos_encoding = memory_entry.maskmem_pos_enc[-1].flatten(2).permute(2, 0, 1)
            memory_pos_encoding = memory_pos_encoding + maskmem_tpos_enc
            to_cat_memory_pos_embed.append(memory_pos_encoding)
        return torch.cat(to_cat_memory, dim=0), torch.cat(to_cat_memory_pos_embed, dim=0)
