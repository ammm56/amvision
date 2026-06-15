"""RF-DETR core 模型结构模块：`models.backbone.dinov2_with_windowed_attn`。"""

import collections.abc
import math
from typing import Dict, List, Optional, Set, Tuple, Union

import torch
from torch import nn
from torch.nn import BCEWithLogitsLoss, CrossEntropyLoss, MSELoss
from transformers import BackboneConfigMixin, BackboneMixin
from transformers.activations import ACT2FN
from transformers.configuration_utils import PretrainedConfig
from transformers.modeling_outputs import (
    BackboneOutput,
    BaseModelOutput,
    BaseModelOutputWithPooling,
    ImageClassifierOutput,
)
from transformers.modeling_utils import PreTrainedModel
from transformers.pytorch_utils import prune_linear_layer
from transformers.utils import (
    add_start_docstrings,
    add_start_docstrings_to_model_forward,
    logging,
    replace_return_docstrings,
    torch_int,
)

logger = logging.get_logger(__name__)


def _find_pruneable_heads_and_indices(
    heads: Set[int], n_heads: int, head_size: int, already_pruned_heads: Set[int]
) -> Tuple[Set[int], torch.LongTensor]:
    """执行 `_find_pruneable_heads_and_indices`。
    
    参数：
    - `heads`：传入的 `heads` 参数。
    - `n_heads`：传入的 `n_heads` 参数。
    - `head_size`：传入的 `head_size` 参数。
    - `already_pruned_heads`：传入的 `already_pruned_heads` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    mask = torch.ones(n_heads, head_size)
    heads = set(heads) - already_pruned_heads
    for head in heads:
        head -= sum(1 if h < head else 0 for h in already_pruned_heads)
        mask[head] = 0
    mask = mask.view(-1).contiguous().eq(1)
    index = torch.arange(len(mask))[mask].long()
    return heads, index


def _align_output_features_output_indices(
    out_features: Optional[List[str]],
    out_indices: Optional[Union[List[int], Tuple[int, ...]]],
    stage_names: List[str],
) -> Tuple[List[str], List[int]]:
    if out_indices is None and out_features is None:
        out_indices = [len(stage_names) - 1]
        out_features = [stage_names[-1]]
    elif out_indices is None and out_features is not None:
        out_indices = [stage_names.index(layer) for layer in out_features]
    elif out_features is None and out_indices is not None:
        out_features = [stage_names[idx] for idx in out_indices]
    return out_features, out_indices


def _get_aligned_output_features_output_indices(
    out_features: Optional[List[str]],
    out_indices: Optional[Union[List[int], Tuple[int, ...]]],
    stage_names: List[str],
) -> Tuple[List[str], List[int]]:
    """执行 `_get_aligned_output_features_output_indices`。
    
    参数：
    - `out_features`：传入的 `out_features` 参数。
    - `out_indices`：传入的 `out_indices` 参数。
    - `stage_names`：传入的 `stage_names` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    out_indices = list(out_indices) if out_indices is not None else None
    out_features, out_indices = _align_output_features_output_indices(
        out_features=out_features, out_indices=out_indices, stage_names=stage_names
    )
    return out_features, out_indices


_CONFIG_FOR_DOC = "WindowedDinov2WithRegistersConfig"


class WindowedDinov2WithRegistersConfig(BackboneConfigMixin, PretrainedConfig):
    """RF-DETR core 类：`WindowedDinov2WithRegistersConfig`。"""

    model_type = "dinov2_with_registers"

    def __init__(
        self,
        hidden_size=768,
        num_hidden_layers=12,
        num_attention_heads=12,
        mlp_ratio=4,
        hidden_act="gelu",
        hidden_dropout_prob=0.0,
        attention_probs_dropout_prob=0.0,
        initializer_range=0.02,
        layer_norm_eps=1e-6,
        image_size=224,
        patch_size=16,
        num_channels=3,
        qkv_bias=True,
        layerscale_value=1.0,
        drop_path_rate=0.0,
        use_swiglu_ffn=False,
        num_register_tokens=4,
        out_features=None,
        out_indices=None,
        apply_layernorm=True,
        reshape_hidden_states=True,
        num_windows=1,
        window_block_indexes=None,
        gradient_checkpointing=False,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.hidden_size = hidden_size
        self.num_hidden_layers = num_hidden_layers
        self.num_attention_heads = num_attention_heads
        self.mlp_ratio = mlp_ratio
        self.hidden_act = hidden_act
        self.hidden_dropout_prob = hidden_dropout_prob
        self.attention_probs_dropout_prob = attention_probs_dropout_prob
        self.initializer_range = initializer_range
        self.layer_norm_eps = layer_norm_eps
        self.image_size = image_size
        self.patch_size = patch_size
        self.num_channels = num_channels
        self.qkv_bias = qkv_bias
        self.layerscale_value = layerscale_value
        self.drop_path_rate = drop_path_rate
        self.use_swiglu_ffn = use_swiglu_ffn
        self.num_register_tokens = num_register_tokens
        self.stage_names = ["stem"] + [f"stage{idx}" for idx in range(1, num_hidden_layers + 1)]
        self._out_features, self._out_indices = _get_aligned_output_features_output_indices(
            out_features=out_features, out_indices=out_indices, stage_names=self.stage_names
        )
        self.apply_layernorm = apply_layernorm
        self.reshape_hidden_states = reshape_hidden_states
        self.num_windows = num_windows
        self.window_block_indexes = (
            list(range(num_hidden_layers)) if window_block_indexes is None else window_block_indexes
        )
        self.gradient_checkpointing = gradient_checkpointing


class Dinov2WithRegistersPatchEmbeddings(nn.Module):
    """RF-DETR core 类：`Dinov2WithRegistersPatchEmbeddings`。"""

    def __init__(self, config):
        super().__init__()
        image_size, patch_size = config.image_size, config.patch_size
        num_channels, hidden_size = config.num_channels, config.hidden_size

        image_size = image_size if isinstance(image_size, collections.abc.Iterable) else (image_size, image_size)
        patch_size = patch_size if isinstance(patch_size, collections.abc.Iterable) else (patch_size, patch_size)
        num_patches = (image_size[1] // patch_size[1]) * (image_size[0] // patch_size[0])
        self.image_size = image_size
        self.patch_size = patch_size
        self.num_channels = num_channels
        self.num_patches = num_patches

        self.projection = nn.Conv2d(num_channels, hidden_size, kernel_size=patch_size, stride=patch_size)

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        num_channels = pixel_values.shape[1]
        if num_channels != self.num_channels:
            raise ValueError(
                "Make sure that the channel dimension of the pixel values match with the one set in the configuration."
                f" Expected {self.num_channels} but got {num_channels}."
            )
        embeddings = self.projection(pixel_values).flatten(2).transpose(1, 2)
        return embeddings


class WindowedDinov2WithRegistersEmbeddings(nn.Module):
    """RF-DETR core 类：`WindowedDinov2WithRegistersEmbeddings`。"""

    def __init__(self, config: WindowedDinov2WithRegistersConfig) -> None:
        super().__init__()

        self.cls_token = nn.Parameter(torch.randn(1, 1, config.hidden_size))
        self.mask_token = nn.Parameter(torch.zeros(1, config.hidden_size))
        self.register_tokens = (
            nn.Parameter(torch.zeros(1, config.num_register_tokens, config.hidden_size))
            if config.num_register_tokens > 0
            else None
        )
        self.patch_embeddings = Dinov2WithRegistersPatchEmbeddings(config)
        num_patches = self.patch_embeddings.num_patches
        self.position_embeddings = nn.Parameter(torch.randn(1, num_patches + 1, config.hidden_size))
        self.dropout = nn.Dropout(config.hidden_dropout_prob)
        self.patch_size = config.patch_size
        self.config = config

    def interpolate_pos_encoding(self, embeddings: torch.Tensor, height: int, width: int) -> torch.Tensor:
        """执行 `interpolate_pos_encoding`。
        
        参数：
        - `embeddings`：传入的 `embeddings` 参数。
        - `height`：传入的 `height` 参数。
        - `width`：传入的 `width` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        num_patches = embeddings.shape[1] - 1
        num_positions = self.position_embeddings.shape[1] - 1

        if not torch.jit.is_tracing() and num_patches == num_positions and height == width:
            return self.position_embeddings

        class_pos_embed = self.position_embeddings[:, 0]
        patch_pos_embed = self.position_embeddings[:, 1:]
        dim = embeddings.shape[-1]

        height = height // self.config.patch_size
        width = width // self.config.patch_size

        sqrt_num_positions = torch_int(num_positions**0.5)
        patch_pos_embed = patch_pos_embed.reshape(1, sqrt_num_positions, sqrt_num_positions, dim)
        patch_pos_embed = patch_pos_embed.permute(0, 3, 1, 2)

        target_dtype = patch_pos_embed.dtype

        patch_pos_embed = nn.functional.interpolate(
            patch_pos_embed.to(dtype=torch.float32),
            size=(torch_int(height), torch_int(width)),
            mode="bicubic",
            align_corners=False,
            antialias=False,
        ).to(dtype=target_dtype)

        if not torch.jit.is_tracing():
            if int(height) != patch_pos_embed.shape[-2] or int(width) != patch_pos_embed.shape[-1]:
                raise ValueError("Width or height does not match with the interpolated position embeddings")

        patch_pos_embed = patch_pos_embed.permute(0, 2, 3, 1).view(1, -1, dim)

        return torch.cat((class_pos_embed.unsqueeze(0), patch_pos_embed), dim=1)

    def forward(self, pixel_values: torch.Tensor, bool_masked_pos: Optional[torch.Tensor] = None) -> torch.Tensor:
        """执行 `forward`。
        
        参数：
        - `pixel_values`：传入的 `pixel_values` 参数。
        - `bool_masked_pos`：传入的 `bool_masked_pos` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        batch_size, _, height, width = pixel_values.shape
        divisor = self.patch_size * self.config.num_windows
        if height % divisor != 0 or width % divisor != 0:
            raise ValueError(
                f"Input spatial dimensions must be divisible by patch_size * num_windows "
                f"({self.patch_size} * {self.config.num_windows} = {divisor}), "
                f"but got height={height}, width={width}."
            )
        target_dtype = self.patch_embeddings.projection.weight.dtype
        embeddings = self.patch_embeddings(pixel_values.to(dtype=target_dtype))

        if bool_masked_pos is not None:
            embeddings = torch.where(
                bool_masked_pos.unsqueeze(-1), self.mask_token.to(embeddings.dtype).unsqueeze(0), embeddings
            )

        cls_tokens = self.cls_token.expand(batch_size, -1, -1)
        embeddings = torch.cat((cls_tokens, embeddings), dim=1)

        embeddings = embeddings + self.interpolate_pos_encoding(embeddings, height, width)

        if self.config.num_windows > 1:
            num_h_patches = height // self.config.patch_size
            num_w_patches = width // self.config.patch_size
            cls_token_with_pos_embed = embeddings[:, :1]
            pixel_tokens_with_pos_embed = embeddings[:, 1:]
            pixel_tokens_with_pos_embed = pixel_tokens_with_pos_embed.view(batch_size, num_h_patches, num_w_patches, -1)
            num_w_patches_per_window = num_w_patches // self.config.num_windows
            num_h_patches_per_window = num_h_patches // self.config.num_windows
            num_windows = self.config.num_windows
            windowed_pixel_tokens = pixel_tokens_with_pos_embed.reshape(
                batch_size * num_windows, num_h_patches_per_window, num_windows, num_w_patches_per_window, -1
            )
            windowed_pixel_tokens = windowed_pixel_tokens.permute(0, 2, 1, 3, 4)
            windowed_pixel_tokens = windowed_pixel_tokens.reshape(
                batch_size * num_windows**2, num_h_patches_per_window * num_w_patches_per_window, -1
            )
            windowed_cls_token_with_pos_embed = cls_token_with_pos_embed.repeat(num_windows**2, 1, 1)
            embeddings = torch.cat((windowed_cls_token_with_pos_embed, windowed_pixel_tokens), dim=1)

        embeddings = (
            torch.cat(
                (embeddings[:, :1], self.register_tokens.expand(embeddings.shape[0], -1, -1), embeddings[:, 1:]), dim=1
            )
            if self.config.num_register_tokens > 0
            else embeddings
        )

        embeddings = self.dropout(embeddings)

        return embeddings


class Dinov2WithRegistersSelfAttention(nn.Module):
    def __init__(self, config: WindowedDinov2WithRegistersConfig) -> None:
        super().__init__()
        if config.hidden_size % config.num_attention_heads != 0 and not hasattr(config, "embedding_size"):
            raise ValueError(
                f"The hidden size {(config.hidden_size,)} is not a multiple of the number of attention "
                f"heads {config.num_attention_heads}."
            )

        self.num_attention_heads = config.num_attention_heads
        self.attention_head_size = int(config.hidden_size / config.num_attention_heads)
        self.all_head_size = self.num_attention_heads * self.attention_head_size

        self.query = nn.Linear(config.hidden_size, self.all_head_size, bias=config.qkv_bias)
        self.key = nn.Linear(config.hidden_size, self.all_head_size, bias=config.qkv_bias)
        self.value = nn.Linear(config.hidden_size, self.all_head_size, bias=config.qkv_bias)

        self.dropout = nn.Dropout(config.attention_probs_dropout_prob)

    def transpose_for_scores(self, x: torch.Tensor) -> torch.Tensor:
        new_x_shape = x.size()[:-1] + (self.num_attention_heads, self.attention_head_size)
        x = x.view(new_x_shape)
        return x.permute(0, 2, 1, 3)

    def forward(
        self, hidden_states: torch.Tensor, output_attentions: bool = False
    ) -> Union[Tuple[torch.Tensor, torch.Tensor], Tuple[torch.Tensor]]:
        mixed_query_layer = self.query(hidden_states)

        key_layer = self.transpose_for_scores(self.key(hidden_states))
        value_layer = self.transpose_for_scores(self.value(hidden_states))
        query_layer = self.transpose_for_scores(mixed_query_layer)

        attention_scores = torch.matmul(query_layer, key_layer.transpose(-1, -2))

        attention_scores = attention_scores / math.sqrt(self.attention_head_size)

        attention_probs = nn.functional.softmax(attention_scores, dim=-1)

        attention_probs = self.dropout(attention_probs)

        context_layer = torch.matmul(attention_probs, value_layer)

        context_layer = context_layer.permute(0, 2, 1, 3).contiguous()
        new_context_layer_shape = context_layer.size()[:-2] + (self.all_head_size,)
        context_layer = context_layer.view(new_context_layer_shape)

        outputs = (context_layer, attention_probs) if output_attentions else (context_layer,)

        return outputs


class Dinov2WithRegistersSdpaSelfAttention(Dinov2WithRegistersSelfAttention):
    def __init__(self, config: WindowedDinov2WithRegistersConfig) -> None:
        super().__init__(config)
        self.attention_probs_dropout_prob = config.attention_probs_dropout_prob

    def forward(
        self, hidden_states: torch.Tensor, output_attentions: bool = False
    ) -> Union[Tuple[torch.Tensor, torch.Tensor], Tuple[torch.Tensor]]:
        if output_attentions:
            logger.warning_once(
                "Dinov2WithRegistersModel is using Dinov2WithRegistersSdpaSelfAttention, "
                "but `torch.nn.functional.scaled_dot_product_attention` does not support "
                "`output_attentions=True`. Falling back to the manual attention implementation. "
                "To avoid this fallback, call `model.set_attn_implementation('eager')` "
                'or pass `attn_implementation="eager"` when instantiating the model.'
            )
            return super().forward(hidden_states=hidden_states, output_attentions=output_attentions)

        mixed_query_layer = self.query(hidden_states)

        key_layer = self.transpose_for_scores(self.key(hidden_states))
        value_layer = self.transpose_for_scores(self.value(hidden_states))
        query_layer = self.transpose_for_scores(mixed_query_layer)

        context_layer = torch.nn.functional.scaled_dot_product_attention(
            query_layer,
            key_layer,
            value_layer,
            None,
            self.attention_probs_dropout_prob if self.training else 0.0,
            is_causal=False,
            scale=None,
        )

        context_layer = context_layer.permute(0, 2, 1, 3).contiguous()
        new_context_layer_shape = context_layer.size()[:-2] + (self.all_head_size,)
        context_layer = context_layer.view(new_context_layer_shape)

        return context_layer, None


class Dinov2WithRegistersSelfOutput(nn.Module):
    """RF-DETR core 类：`Dinov2WithRegistersSelfOutput`。"""

    def __init__(self, config: WindowedDinov2WithRegistersConfig) -> None:
        super().__init__()
        self.dense = nn.Linear(config.hidden_size, config.hidden_size)
        self.dropout = nn.Dropout(config.hidden_dropout_prob)

    def forward(self, hidden_states: torch.Tensor, input_tensor: torch.Tensor) -> torch.Tensor:
        hidden_states = self.dense(hidden_states)
        hidden_states = self.dropout(hidden_states)

        return hidden_states


class Dinov2WithRegistersAttention(nn.Module):
    def __init__(self, config: WindowedDinov2WithRegistersConfig) -> None:
        super().__init__()
        self.attention = Dinov2WithRegistersSelfAttention(config)
        self.output = Dinov2WithRegistersSelfOutput(config)
        self.pruned_heads = set()

    def prune_heads(self, heads: Set[int]) -> None:
        if len(heads) == 0:
            return
        heads, index = _find_pruneable_heads_and_indices(
            heads, self.attention.num_attention_heads, self.attention.attention_head_size, self.pruned_heads
        )

        self.attention.query = prune_linear_layer(self.attention.query, index)
        self.attention.key = prune_linear_layer(self.attention.key, index)
        self.attention.value = prune_linear_layer(self.attention.value, index)
        self.output.dense = prune_linear_layer(self.output.dense, index, dim=1)

        self.attention.num_attention_heads = self.attention.num_attention_heads - len(heads)
        self.attention.all_head_size = self.attention.attention_head_size * self.attention.num_attention_heads
        self.pruned_heads = self.pruned_heads.union(heads)

    def forward(
        self,
        hidden_states: torch.Tensor,
        output_attentions: bool = False,
    ) -> Union[Tuple[torch.Tensor, torch.Tensor], Tuple[torch.Tensor]]:
        self_outputs = self.attention(hidden_states, output_attentions)

        attention_output = self.output(self_outputs[0], hidden_states)

        outputs = (attention_output,) + self_outputs[1:]
        return outputs


class Dinov2WithRegistersSdpaAttention(Dinov2WithRegistersAttention):
    def __init__(self, config: WindowedDinov2WithRegistersConfig) -> None:
        super().__init__(config)
        self.attention = Dinov2WithRegistersSdpaSelfAttention(config)


class Dinov2WithRegistersLayerScale(nn.Module):
    def __init__(self, config) -> None:
        super().__init__()
        self.lambda1 = nn.Parameter(config.layerscale_value * torch.ones(config.hidden_size))

    def forward(self, hidden_state: torch.Tensor) -> torch.Tensor:
        return hidden_state * self.lambda1


def drop_path(input: torch.Tensor, drop_prob: float = 0.0, training: bool = False) -> torch.Tensor:
    """执行 `drop_path`。
    
    参数：
    - `input`：传入的 `input` 参数。
    - `drop_prob`：传入的 `drop_prob` 参数。
    - `training`：传入的 `training` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if drop_prob == 0.0 or not training:
        return input
    keep_prob = 1 - drop_prob
    shape = (input.shape[0],) + (1,) * (input.ndim - 1)
    random_tensor = keep_prob + torch.rand(shape, dtype=input.dtype, device=input.device)
    random_tensor.floor_()
    output = input.div(keep_prob) * random_tensor
    return output


class Dinov2WithRegistersDropPath(nn.Module):
    """RF-DETR core 类：`Dinov2WithRegistersDropPath`。"""

    def __init__(self, drop_prob: Optional[float] = None) -> None:
        super().__init__()
        self.drop_prob = drop_prob

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        return drop_path(hidden_states, self.drop_prob, self.training)

    def extra_repr(self) -> str:
        return "p={}".format(self.drop_prob)


class Dinov2WithRegistersMLP(nn.Module):
    def __init__(self, config) -> None:
        super().__init__()
        in_features = out_features = config.hidden_size
        hidden_features = int(config.hidden_size * config.mlp_ratio)
        self.fc1 = nn.Linear(in_features, hidden_features, bias=True)
        if isinstance(config.hidden_act, str):
            self.activation = ACT2FN[config.hidden_act]
        else:
            self.activation = config.hidden_act
        self.fc2 = nn.Linear(hidden_features, out_features, bias=True)

    def forward(self, hidden_state: torch.Tensor) -> torch.Tensor:
        hidden_state = self.fc1(hidden_state)
        hidden_state = self.activation(hidden_state)
        hidden_state = self.fc2(hidden_state)
        return hidden_state


class Dinov2WithRegistersSwiGLUFFN(nn.Module):
    def __init__(self, config) -> None:
        super().__init__()
        in_features = out_features = config.hidden_size
        hidden_features = int(config.hidden_size * config.mlp_ratio)
        hidden_features = (int(hidden_features * 2 / 3) + 7) // 8 * 8

        self.weights_in = nn.Linear(in_features, 2 * hidden_features, bias=True)
        self.weights_out = nn.Linear(hidden_features, out_features, bias=True)

    def forward(self, hidden_state: torch.Tensor) -> torch.Tensor:
        hidden_state = self.weights_in(hidden_state)
        x1, x2 = hidden_state.chunk(2, dim=-1)
        hidden = nn.functional.silu(x1) * x2
        return self.weights_out(hidden)


DINOV2_WITH_REGISTERS_ATTENTION_CLASSES = {
    "eager": Dinov2WithRegistersAttention,
    "sdpa": Dinov2WithRegistersSdpaAttention,
}


class WindowedDinov2WithRegistersLayer(nn.Module):
    """RF-DETR core 类：`WindowedDinov2WithRegistersLayer`。"""

    def __init__(self, config: WindowedDinov2WithRegistersConfig) -> None:
        super().__init__()

        self.num_windows = config.num_windows

        self.norm1 = nn.LayerNorm(config.hidden_size, eps=config.layer_norm_eps)
        self.attention = DINOV2_WITH_REGISTERS_ATTENTION_CLASSES[config._attn_implementation](config)
        self.layer_scale1 = Dinov2WithRegistersLayerScale(config)
        self.drop_path = (
            Dinov2WithRegistersDropPath(config.drop_path_rate) if config.drop_path_rate > 0.0 else nn.Identity()
        )

        self.norm2 = nn.LayerNorm(config.hidden_size, eps=config.layer_norm_eps)

        if config.use_swiglu_ffn:
            self.mlp = Dinov2WithRegistersSwiGLUFFN(config)
        else:
            self.mlp = Dinov2WithRegistersMLP(config)
        self.layer_scale2 = Dinov2WithRegistersLayerScale(config)

    def forward(
        self,
        hidden_states: torch.Tensor,
        output_attentions: bool = False,
        run_full_attention: bool = False,
    ) -> Union[Tuple[torch.Tensor, torch.Tensor], Tuple[torch.Tensor]]:
        assert not output_attentions, "output_attentions is not supported for windowed attention"
        shortcut = hidden_states
        if run_full_attention:
            batch_windows, tokens_per_window, channels = hidden_states.shape
            num_windows_squared = self.num_windows**2
            hidden_states = hidden_states.view(
                batch_windows // num_windows_squared, num_windows_squared * tokens_per_window, channels
            )

        self_attention_outputs = self.attention(
            self.norm1(hidden_states),
            output_attentions=output_attentions,
        )
        attention_output = self_attention_outputs[0]

        if run_full_attention:
            batch_windows, tokens_per_window, channels = hidden_states.shape
            num_windows_squared = self.num_windows**2
            attention_output = attention_output.view(
                batch_windows * num_windows_squared, tokens_per_window // num_windows_squared, channels
            )

        attention_output = self.layer_scale1(attention_output)
        outputs = self_attention_outputs[1:]

        hidden_states = self.drop_path(attention_output) + shortcut

        layer_output = self.norm2(hidden_states)
        layer_output = self.mlp(layer_output)
        layer_output = self.layer_scale2(layer_output)

        layer_output = self.drop_path(layer_output) + hidden_states

        outputs = (layer_output,) + outputs

        return outputs


class WindowedDinov2WithRegistersEncoder(nn.Module):
    def __init__(self, config: WindowedDinov2WithRegistersConfig) -> None:
        super().__init__()
        self.config = config
        self.layer = nn.ModuleList([WindowedDinov2WithRegistersLayer(config) for _ in range(config.num_hidden_layers)])
        self.gradient_checkpointing = config.gradient_checkpointing

    def forward(
        self,
        hidden_states: torch.Tensor,
        output_attentions: bool = False,
        output_hidden_states: bool = False,
        return_dict: bool = True,
    ) -> Union[tuple, BaseModelOutput]:
        all_hidden_states = () if output_hidden_states else None
        all_self_attentions = () if output_attentions else None

        for i, layer_module in enumerate(self.layer):
            if output_hidden_states:
                all_hidden_states = all_hidden_states + (hidden_states,)

            if i > int(self.config.out_features[-1][5:]):
                break

            run_full_attention = i not in self.config.window_block_indexes

            if self.gradient_checkpointing and self.training:
                layer_outputs = self._gradient_checkpointing_func(
                    layer_module.__call__,
                    hidden_states,
                    output_attentions,
                    run_full_attention,
                )
            else:
                layer_outputs = layer_module(hidden_states, output_attentions, run_full_attention)

            hidden_states = layer_outputs[0]

            if output_attentions:
                all_self_attentions = all_self_attentions + (layer_outputs[1],)

        if output_hidden_states:
            all_hidden_states = all_hidden_states + (hidden_states,)

        if not return_dict:
            return tuple(v for v in [hidden_states, all_hidden_states, all_self_attentions] if v is not None)
        return BaseModelOutput(
            last_hidden_state=hidden_states,
            hidden_states=all_hidden_states,
            attentions=all_self_attentions,
        )


class WindowedDinov2WithRegistersPreTrainedModel(PreTrainedModel):
    """RF-DETR core 类：`WindowedDinov2WithRegistersPreTrainedModel`。"""

    config_class = WindowedDinov2WithRegistersConfig
    base_model_prefix = "dinov2_with_registers"
    main_input_name = "pixel_values"
    supports_gradient_checkpointing = True
    _no_split_modules = ["Dinov2WithRegistersSwiGLUFFN"]
    _supports_sdpa = True

    def _init_weights(self, module: Union[nn.Linear, nn.Conv2d, nn.LayerNorm]) -> None:
        """执行 `_init_weights`。
        
        参数：
        - `module`：传入的 `module` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if isinstance(module, (nn.Linear, nn.Conv2d)):
            module.weight.data = nn.init.trunc_normal_(
                module.weight.data.to(torch.float32), mean=0.0, std=self.config.initializer_range
            ).to(module.weight.dtype)
            if module.bias is not None:
                module.bias.data.zero_()
        elif isinstance(module, nn.LayerNorm):
            module.bias.data.zero_()
            module.weight.data.fill_(1.0)
        elif isinstance(module, WindowedDinov2WithRegistersEmbeddings):
            module.position_embeddings.data = nn.init.trunc_normal_(
                module.position_embeddings.data.to(torch.float32),
                mean=0.0,
                std=self.config.initializer_range,
            ).to(module.position_embeddings.dtype)

            module.cls_token.data = nn.init.trunc_normal_(
                module.cls_token.data.to(torch.float32),
                mean=0.0,
                std=self.config.initializer_range,
            ).to(module.cls_token.dtype)


DINOV2_WITH_REGISTERS_START_DOCSTRING = r"""
    这是基于 PyTorch `torch.nn.Module` 的 DINOv2 with registers 模型模块。
    本项目只在 RF-DETR core 内部调用该模块，权重通过本地 checkpoint 加载，不走在线 `from_pretrained()` 路径。

    参数：
        config ([`Dinov2WithRegistersConfig`])：模型配置对象，包含模型结构参数。
            只传入 config 不会加载权重，只会创建对应结构。
"""

DINOV2_WITH_REGISTERS_BASE_INPUTS_DOCSTRING = r"""
    参数：
        pixel_values (`torch.FloatTensor` of shape `(batch_size, num_channels, height, width)`):
            输入图像 tensor，形状为 `(batch_size, num_channels, height, width)`。

        bool_masked_pos (`torch.BoolTensor` of shape `(batch_size, sequence_length)`):
            patch mask 标记，1 表示被遮挡，0 表示未遮挡；只用于 pre-training。

        output_attentions (`bool`, *optional*):
            是否返回各 attention 层的 attention tensor。
        output_hidden_states (`bool`, *optional*):
            是否返回各层 hidden state。
        return_dict (`bool`, *optional*):
            是否返回 `ModelOutput`，否则返回普通 tuple。
"""


@add_start_docstrings(
    "DINOv2 with registers backbone，输出 hidden state，不挂接额外任务 head。",
    DINOV2_WITH_REGISTERS_START_DOCSTRING,
)
class WindowedDinov2WithRegistersModel(WindowedDinov2WithRegistersPreTrainedModel):
    def __init__(self, config: WindowedDinov2WithRegistersConfig):
        super().__init__(config)
        self.config = config

        self.embeddings = WindowedDinov2WithRegistersEmbeddings(config)
        self.encoder = WindowedDinov2WithRegistersEncoder(config)

        self.layernorm = nn.LayerNorm(config.hidden_size, eps=config.layer_norm_eps)

        self.post_init()

    def get_input_embeddings(self) -> Dinov2WithRegistersPatchEmbeddings:
        return self.embeddings.patch_embeddings

    def _prune_heads(self, heads_to_prune: Dict[int, List[int]]) -> None:
        """执行 `_prune_heads`。
        
        参数：
        - `heads_to_prune`：传入的 `heads_to_prune` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        for layer, heads in heads_to_prune.items():
            self.encoder.layer[layer].attention.prune_heads(heads)

    def set_attn_implementation(self, attn_implementation: str) -> None:
        """执行 `set_attn_implementation`。
        
        参数：
        - `attn_implementation`：传入的 `attn_implementation` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if attn_implementation not in DINOV2_WITH_REGISTERS_ATTENTION_CLASSES:
            raise ValueError(
                f"Unknown attn_implementation {attn_implementation!r}. "
                f"Choose from {sorted(DINOV2_WITH_REGISTERS_ATTENTION_CLASSES)}."
            )
        self.config._attn_implementation = attn_implementation
        for layer in self.encoder.layer:
            layer.attention = DINOV2_WITH_REGISTERS_ATTENTION_CLASSES[attn_implementation](self.config)

    @add_start_docstrings_to_model_forward(DINOV2_WITH_REGISTERS_BASE_INPUTS_DOCSTRING)
    @replace_return_docstrings(output_type=BaseModelOutputWithPooling, config_class=_CONFIG_FOR_DOC)
    def forward(
        self,
        pixel_values: Optional[torch.Tensor] = None,
        bool_masked_pos: Optional[torch.Tensor] = None,
        output_attentions: Optional[bool] = None,
        output_hidden_states: Optional[bool] = None,
        return_dict: Optional[bool] = None,
    ) -> Union[Tuple, BaseModelOutputWithPooling]:
        """执行 `forward`。
        
        参数：
        - `pixel_values`：传入的 `pixel_values` 参数。
        - `bool_masked_pos`：传入的 `bool_masked_pos` 参数。
        - `output_attentions`：传入的 `output_attentions` 参数。
        - `output_hidden_states`：传入的 `output_hidden_states` 参数。
        - `return_dict`：传入的 `return_dict` 参数。
        
        Returns:
        """
        output_attentions = output_attentions if output_attentions is not None else self.config.output_attentions
        output_hidden_states = (
            output_hidden_states if output_hidden_states is not None else self.config.output_hidden_states
        )
        return_dict = return_dict if return_dict is not None else self.config.use_return_dict

        if pixel_values is None:
            raise ValueError("You have to specify pixel_values")

        embedding_output = self.embeddings(pixel_values, bool_masked_pos=bool_masked_pos)

        encoder_outputs = self.encoder(
            embedding_output,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            return_dict=return_dict,
        )
        sequence_output = encoder_outputs[0]
        sequence_output = self.layernorm(sequence_output)
        pooled_output = sequence_output[:, 0, :]

        if not return_dict:
            head_outputs = (sequence_output, pooled_output)
            return head_outputs + encoder_outputs[1:]

        return BaseModelOutputWithPooling(
            last_hidden_state=sequence_output,
            pooler_output=pooled_output,
            hidden_states=encoder_outputs.hidden_states,
            attentions=encoder_outputs.attentions,
        )


DINOV2_WITH_REGISTERS_INPUTS_DOCSTRING = r"""
    参数：
        pixel_values (`torch.FloatTensor` of shape `(batch_size, num_channels, height, width)`):
            输入图像 tensor，形状为 `(batch_size, num_channels, height, width)`。

        output_attentions (`bool`, *optional*):
            是否返回各 attention 层的 attention tensor。
        output_hidden_states (`bool`, *optional*):
            是否返回各层 hidden state。
        return_dict (`bool`, *optional*):
            是否返回 `ModelOutput`，否则返回普通 tuple。
"""


@add_start_docstrings(
    """
    DINOv2 with registers 图像分类模型，在 backbone 输出上挂接线性分类 head。
    """,
    DINOV2_WITH_REGISTERS_START_DOCSTRING,
)
class WindowedDinov2WithRegistersForImageClassification(WindowedDinov2WithRegistersPreTrainedModel):
    def __init__(self, config: WindowedDinov2WithRegistersConfig) -> None:
        super().__init__(config)

        self.num_labels = config.num_labels
        self.dinov2_with_registers = WindowedDinov2WithRegistersModel(config)

        self.classifier = (
            nn.Linear(config.hidden_size * 2, config.num_labels) if config.num_labels > 0 else nn.Identity()
        )

        self.post_init()

    @add_start_docstrings_to_model_forward(DINOV2_WITH_REGISTERS_INPUTS_DOCSTRING)
    @replace_return_docstrings(
        output_type=ImageClassifierOutput,
        config_class=_CONFIG_FOR_DOC,
    )
    def forward(
        self,
        pixel_values: Optional[torch.Tensor] = None,
        labels: Optional[torch.Tensor] = None,
        output_attentions: Optional[bool] = None,
        output_hidden_states: Optional[bool] = None,
        return_dict: Optional[bool] = None,
    ) -> Union[tuple, ImageClassifierOutput]:
        """执行 `forward`。
        
        参数：
        - `pixel_values`：传入的 `pixel_values` 参数。
        - `labels`：传入的 `labels` 参数。
        - `output_attentions`：传入的 `output_attentions` 参数。
        - `output_hidden_states`：传入的 `output_hidden_states` 参数。
        - `return_dict`：传入的 `return_dict` 参数。
        
        Returns:
        """
        return_dict = return_dict if return_dict is not None else self.config.use_return_dict

        outputs = self.dinov2_with_registers(
            pixel_values,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            return_dict=return_dict,
        )

        sequence_output = outputs[0]

        cls_token = sequence_output[:, 0]
        patch_tokens = sequence_output[:, 1:]

        linear_input = torch.cat([cls_token, patch_tokens.mean(dim=1)], dim=1)

        logits = self.classifier(linear_input)

        loss = None
        if labels is not None:
            labels = labels.to(logits.device)
            if self.config.problem_type is None:
                if self.num_labels == 1:
                    self.config.problem_type = "regression"
                elif self.num_labels > 1 and (labels.dtype == torch.long or labels.dtype == torch.int):
                    self.config.problem_type = "single_label_classification"
                else:
                    self.config.problem_type = "multi_label_classification"

            if self.config.problem_type == "regression":
                loss_fct = MSELoss()
                if self.num_labels == 1:
                    loss = loss_fct(logits.squeeze(), labels.squeeze())
                else:
                    loss = loss_fct(logits, labels)
            elif self.config.problem_type == "single_label_classification":
                loss_fct = CrossEntropyLoss()
                loss = loss_fct(logits.view(-1, self.num_labels), labels.view(-1))
            elif self.config.problem_type == "multi_label_classification":
                loss_fct = BCEWithLogitsLoss()
                loss = loss_fct(logits, labels)

        if not return_dict:
            output = (logits,) + outputs[2:]
            return ((loss,) + output) if loss is not None else output

        return ImageClassifierOutput(
            loss=loss,
            logits=logits,
            hidden_states=outputs.hidden_states,
            attentions=outputs.attentions,
        )


@add_start_docstrings(
    """
    DINOv2 with registers backbone，用于 DETR / MaskFormer 这类视觉模型框架。
    """,
    DINOV2_WITH_REGISTERS_START_DOCSTRING,
)
class WindowedDinov2WithRegistersBackbone(WindowedDinov2WithRegistersPreTrainedModel, BackboneMixin):
    def __init__(self, config: WindowedDinov2WithRegistersConfig):
        super().__init__(config)
        self._init_transformers_backbone()
        self.num_features = [config.hidden_size for _ in range(config.num_hidden_layers + 1)]
        self.embeddings = WindowedDinov2WithRegistersEmbeddings(config)
        self.encoder = WindowedDinov2WithRegistersEncoder(config)

        self.layernorm = nn.LayerNorm(config.hidden_size, eps=config.layer_norm_eps)

        self.num_register_tokens = config.num_register_tokens

        self.post_init()

    def get_input_embeddings(self) -> Dinov2WithRegistersPatchEmbeddings:
        return self.embeddings.patch_embeddings

    @add_start_docstrings_to_model_forward(DINOV2_WITH_REGISTERS_INPUTS_DOCSTRING)
    @replace_return_docstrings(output_type=BackboneOutput, config_class=_CONFIG_FOR_DOC)
    def forward(
        self,
        pixel_values: torch.Tensor,
        output_hidden_states: Optional[bool] = None,
        output_attentions: Optional[bool] = None,
        return_dict: Optional[bool] = None,
    ) -> BackboneOutput:
        """执行 `forward`。
        
        参数：
        - `pixel_values`：传入的 `pixel_values` 参数。
        - `output_hidden_states`：传入的 `output_hidden_states` 参数。
        - `output_attentions`：传入的 `output_attentions` 参数。
        - `return_dict`：传入的 `return_dict` 参数。
        
        Returns:
        """
        return_dict = return_dict if return_dict is not None else self.config.use_return_dict
        output_hidden_states = (
            output_hidden_states if output_hidden_states is not None else self.config.output_hidden_states
        )
        output_attentions = output_attentions if output_attentions is not None else self.config.output_attentions

        embedding_output = self.embeddings(pixel_values)

        outputs = self.encoder(
            embedding_output, output_hidden_states=True, output_attentions=output_attentions, return_dict=return_dict
        )

        hidden_states = outputs.hidden_states if return_dict else outputs[1]

        feature_maps = ()
        for stage, hidden_state in zip(self.stage_names, hidden_states):
            if stage in self.out_features:
                if self.config.apply_layernorm:
                    hidden_state = self.layernorm(hidden_state)
                if self.config.reshape_hidden_states:
                    hidden_state = hidden_state[:, self.num_register_tokens + 1 :]
                    batch_size, _, height, width = pixel_values.shape
                    patch_size = self.config.patch_size

                    num_h_patches = height // patch_size
                    num_w_patches = width // patch_size

                    if self.config.num_windows > 1:
                        num_windows_squared = self.config.num_windows**2
                        batch_windows, tokens_per_window, channels = hidden_state.shape
                        num_h_patches_per_window = num_h_patches // self.config.num_windows
                        num_w_patches_per_window = num_w_patches // self.config.num_windows
                        hidden_state = hidden_state.reshape(
                            batch_windows // num_windows_squared,
                            num_windows_squared * tokens_per_window,
                            channels,
                        )
                        hidden_state = hidden_state.reshape(
                            (batch_windows // num_windows_squared) * self.config.num_windows,
                            self.config.num_windows,
                            num_h_patches_per_window,
                            num_w_patches_per_window,
                            channels,
                        )
                        hidden_state = hidden_state.permute(0, 2, 1, 3, 4)

                    hidden_state = hidden_state.reshape(batch_size, num_h_patches, num_w_patches, -1)
                    hidden_state = hidden_state.permute(0, 3, 1, 2).contiguous()

                feature_maps += (hidden_state,)

        if not return_dict:
            if output_hidden_states:
                output = (feature_maps,) + outputs[1:]
            else:
                output = (feature_maps,) + outputs[2:]
            return output

        return BackboneOutput(
            feature_maps=feature_maps,
            hidden_states=outputs.hidden_states if output_hidden_states else None,
            attentions=outputs.attentions if output_attentions else None,
        )


__all__ = [
    "WindowedDinov2WithRegistersPreTrainedModel",
    "WindowedDinov2WithRegistersModel",
    "WindowedDinov2WithRegistersForImageClassification",
    "WindowedDinov2WithRegistersBackbone",
]
