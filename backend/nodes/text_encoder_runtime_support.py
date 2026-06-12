"""节点运行时的本地文本编码器 helper。"""

from __future__ import annotations

import gzip
import html
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock

import torch

from backend.service.application.errors import InvalidRequestError

try:
    import regex as regex_re
except ImportError as exc:  # pragma: no cover - 当前环境已安装 regex
    raise RuntimeError("当前运行环境缺少 regex，无法加载本地文本编码器") from exc

try:
    import ftfy
except ImportError:  # pragma: no cover - 开发环境可选依赖
    ftfy = None


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEXT_ENCODERS_ROOT = REPOSITORY_ROOT / "data" / "files" / "models" / "pretrained" / "text-encoders"
CLIP_TOKENIZER_ROOT = TEXT_ENCODERS_ROOT / "clip" / "tokenizer"
CLIP_TOKENIZER_BPE_PATH = CLIP_TOKENIZER_ROOT / "bpe_simple_vocab_16e6.txt.gz"
CLIP_VIT_B_32_ROOT = TEXT_ENCODERS_ROOT / "clip" / "vit-b-32"
CLIP_VIT_B_32_PATH = CLIP_VIT_B_32_ROOT / "ViT-B-32.pt"
MOBILECLIP_BLT_ROOT = TEXT_ENCODERS_ROOT / "mobileclip" / "blt"
MOBILECLIP_BLT_TS_PATH = MOBILECLIP_BLT_ROOT / "mobileclip_blt.ts"


@dataclass(frozen=True)
class TextEncoderAssets:
    """描述当前节点运行时需要的文本编码器资产。"""

    clip_tokenizer_bpe_path: Path
    mobileclip_blt_ts_path: Path
    clip_vit_b_32_path: Path | None


class ClipSimpleTokenizer:
    """本地 CLIP BPE tokenizer。"""

    def __init__(self, *, bpe_path: Path) -> None:
        self.bpe_path = bpe_path
        self.byte_encoder = _bytes_to_unicode()
        self.byte_decoder = {value: key for key, value in self.byte_encoder.items()}
        merges = gzip.open(bpe_path, "rt", encoding="utf-8").read().split("\n")
        merges = merges[1 : 49152 - 256 - 2 + 1]
        merge_pairs = [tuple(merge.split()) for merge in merges if merge.strip()]
        vocab = list(_bytes_to_unicode().values())
        vocab += [f"{value}</w>" for value in vocab]
        vocab.extend("".join(merge) for merge in merge_pairs)
        vocab.extend(["<|startoftext|>", "<|endoftext|>"])
        self.encoder = dict(zip(vocab, range(len(vocab))))
        self.decoder = {value: key for key, value in self.encoder.items()}
        self.bpe_ranks = dict(zip(merge_pairs, range(len(merge_pairs))))
        self.cache = {"<|startoftext|>": "<|startoftext|>", "<|endoftext|>": "<|endoftext|>"}
        self.pattern = regex_re.compile(
            r"""<\|startoftext\|>|<\|endoftext\|>|'s|'t|'re|'ve|'m|'ll|'d|[\p{L}]+|[\p{N}]|[^\s\p{L}\p{N}]+""",
            regex_re.IGNORECASE,
        )
        self.sot_token_id = self.encoder["<|startoftext|>"]
        self.eot_token_id = self.encoder["<|endoftext|>"]
        self.context_length = 77

    def encode(self, text: str) -> list[int]:
        """把文本编码为 BPE token id 列表。"""

        bpe_tokens: list[int] = []
        normalized_text = _whitespace_clean(_basic_clean(text)).lower()
        for token in regex_re.findall(self.pattern, normalized_text):
            byte_encoded = "".join(self.byte_encoder[value] for value in token.encode("utf-8"))
            bpe_tokens.extend(self.encoder[bpe_token] for bpe_token in self._bpe(byte_encoded).split(" "))
        return bpe_tokens

    def __call__(
        self,
        texts: str | list[str],
        *,
        context_length: int | None = None,
        truncate: bool = True,
    ) -> torch.LongTensor:
        """返回 CLIP 风格的 token tensor。"""

        normalized_texts = [texts] if isinstance(texts, str) else list(texts)
        normalized_context_length = context_length or self.context_length
        result = torch.zeros(len(normalized_texts), normalized_context_length, dtype=torch.long)
        for index, text in enumerate(normalized_texts):
            tokens = [self.sot_token_id, *self.encode(text), self.eot_token_id]
            if len(tokens) > normalized_context_length:
                if not truncate:
                    raise InvalidRequestError(
                        "文本提示长度超过 CLIP tokenizer 最大上下文长度",
                        details={
                            "context_length": normalized_context_length,
                            "text_length": len(tokens),
                        },
                    )
                tokens = tokens[:normalized_context_length]
                tokens[-1] = self.eot_token_id
            result[index, : len(tokens)] = torch.as_tensor(tokens, dtype=torch.long)
        return result

    def _bpe(self, token: str) -> str:
        """执行一次 BPE merge。"""

        cached_value = self.cache.get(token)
        if cached_value is not None:
            return cached_value
        word = (*tuple(token[:-1]), f"{token[-1]}</w>")
        pairs = _get_pairs(word)
        if not pairs:
            return f"{token}</w>"

        while True:
            bigram = min(pairs, key=lambda pair: self.bpe_ranks.get(pair, float("inf")))
            if bigram not in self.bpe_ranks:
                break
            first, second = bigram
            new_word: list[str] = []
            cursor = 0
            while cursor < len(word):
                try:
                    next_index = word.index(first, cursor)
                    new_word.extend(word[cursor:next_index])
                    cursor = next_index
                except ValueError:
                    new_word.extend(word[cursor:])
                    break

                if cursor < len(word) - 1 and word[cursor] == first and word[cursor + 1] == second:
                    new_word.append(first + second)
                    cursor += 2
                else:
                    new_word.append(word[cursor])
                    cursor += 1
            word = tuple(new_word)
            if len(word) == 1:
                break
            pairs = _get_pairs(word)
        merged_word = " ".join(word)
        self.cache[token] = merged_word
        return merged_word


class MobileClipTorchScriptTextEncoder:
    """本地 MobileCLIP TorchScript 文本编码器。"""

    def __init__(self, *, weight_path: Path, tokenizer: ClipSimpleTokenizer, device: str) -> None:
        self.weight_path = weight_path
        self.tokenizer = tokenizer
        try:
            self.device = torch.device(device)
        except Exception as exc:  # pragma: no cover - 非法 device 由调用参数触发
            raise InvalidRequestError("文本编码器收到的 device 不是有效 torch device") from exc
        try:
            self.encoder = torch.jit.load(str(weight_path), map_location=self.device)
        except Exception as exc:  # pragma: no cover - 文件损坏或设备不支持
            raise InvalidRequestError(
                "无法加载本地 MobileCLIP TorchScript 文本编码器",
                details={"weight_path": str(weight_path), "device": str(self.device)},
            ) from exc
        self.encoder.eval()

    def tokenize(self, texts: str | list[str], *, truncate: bool = True) -> torch.LongTensor:
        """把文本编码为 MobileCLIPTS 使用的 token tensor。"""

        return clip_tokenize(texts, tokenizer=self.tokenizer, truncate=truncate).to(self.device)

    @torch.inference_mode()
    def encode_text(self, tokens: torch.Tensor, *, dtype: torch.dtype = torch.float32) -> torch.Tensor:
        """执行本地 MobileCLIPTS 文本编码。"""

        return self.encoder(tokens).to(dtype)


_MOBILECLIP_BLT_ENCODER_CACHE: dict[tuple[str, str, str], MobileClipTorchScriptTextEncoder] = {}
_MOBILECLIP_BLT_ENCODER_CACHE_LOCK = Lock()


def resolve_text_encoder_assets() -> TextEncoderAssets:
    """解析当前项目本地文本编码器资产。"""

    clip_tokenizer_bpe_path = _require_existing_file(
        CLIP_TOKENIZER_BPE_PATH,
        message="缺少本地 CLIP tokenizer BPE 词表文件",
    )
    mobileclip_blt_ts_path = _require_existing_file(
        MOBILECLIP_BLT_TS_PATH,
        message="缺少本地 MobileCLIP TorchScript 文本编码器权重",
    )
    clip_vit_b_32_path = CLIP_VIT_B_32_PATH if CLIP_VIT_B_32_PATH.is_file() else None
    return TextEncoderAssets(
        clip_tokenizer_bpe_path=clip_tokenizer_bpe_path,
        mobileclip_blt_ts_path=mobileclip_blt_ts_path,
        clip_vit_b_32_path=clip_vit_b_32_path,
    )


def resolve_clip_tokenizer_bpe_path() -> Path:
    """返回本地 CLIP tokenizer BPE 词表路径。"""

    return resolve_text_encoder_assets().clip_tokenizer_bpe_path


def resolve_mobileclip_blt_ts_path() -> Path:
    """返回本地 MobileCLIP BLT TorchScript 权重路径。"""

    return resolve_text_encoder_assets().mobileclip_blt_ts_path


def clip_tokenize(
    texts: str | list[str],
    *,
    tokenizer: ClipSimpleTokenizer | None = None,
    context_length: int = 77,
    truncate: bool = True,
) -> torch.LongTensor:
    """提供 project-native 的 clip.tokenize 等价接口。"""

    clip_tokenizer = tokenizer or load_clip_simple_tokenizer()
    return clip_tokenizer(texts, context_length=context_length, truncate=truncate)


def load_clip_simple_tokenizer(*, bpe_path: Path | None = None) -> ClipSimpleTokenizer:
    """加载本地 CLIP tokenizer。"""

    target_path = bpe_path or resolve_clip_tokenizer_bpe_path()
    return _load_clip_simple_tokenizer_cached(str(target_path))


@lru_cache(maxsize=4)
def _load_clip_simple_tokenizer_cached(bpe_path: str) -> ClipSimpleTokenizer:
    """缓存 CLIP tokenizer。"""

    return ClipSimpleTokenizer(bpe_path=Path(bpe_path))


def get_or_create_mobileclip_blt_text_encoder(*, device: str) -> MobileClipTorchScriptTextEncoder:
    """返回可复用的本地 MobileCLIP BLT 文本编码器。"""

    assets = resolve_text_encoder_assets()
    normalized_device = str(device or "cpu").strip().lower() or "cpu"
    cache_key = (
        str(assets.mobileclip_blt_ts_path),
        str(assets.clip_tokenizer_bpe_path),
        normalized_device,
    )
    with _MOBILECLIP_BLT_ENCODER_CACHE_LOCK:
        cached_encoder = _MOBILECLIP_BLT_ENCODER_CACHE.get(cache_key)
        if cached_encoder is not None:
            return cached_encoder
        encoder = MobileClipTorchScriptTextEncoder(
            weight_path=assets.mobileclip_blt_ts_path,
            tokenizer=load_clip_simple_tokenizer(bpe_path=assets.clip_tokenizer_bpe_path),
            device=normalized_device,
        )
        _MOBILECLIP_BLT_ENCODER_CACHE[cache_key] = encoder
        return encoder


@lru_cache(maxsize=1)
def _bytes_to_unicode() -> dict[int, str]:
    """构造 CLIP tokenizer 的 byte 到 unicode 映射。"""

    byte_values = list(range(ord("!"), ord("~") + 1))
    byte_values += list(range(ord("¡"), ord("¬") + 1))
    byte_values += list(range(ord("®"), ord("ÿ") + 1))
    unicode_values = byte_values[:]
    extra_index = 0
    for value in range(2**8):
        if value not in byte_values:
            byte_values.append(value)
            unicode_values.append(2**8 + extra_index)
            extra_index += 1
    unicode_chars = [chr(value) for value in unicode_values]
    return dict(zip(byte_values, unicode_chars))


def _get_pairs(word: tuple[str, ...]) -> set[tuple[str, str]]:
    """读取 token 序列中的相邻 pair。"""

    pairs: set[tuple[str, str]] = set()
    previous = word[0]
    for current in word[1:]:
        pairs.add((previous, current))
        previous = current
    return pairs


def _basic_clean(text: str) -> str:
    """执行最小文本清洗。"""

    normalized_text = text
    if ftfy is not None:
        normalized_text = ftfy.fix_text(normalized_text)
    normalized_text = html.unescape(html.unescape(normalized_text))
    return normalized_text.strip()


def _whitespace_clean(text: str) -> str:
    """压缩多余空白。"""

    return regex_re.sub(r"\s+", " ", text).strip()


def _require_existing_file(path: Path, *, message: str) -> Path:
    """要求路径必须存在且为文件。"""

    if not path.is_file():
        raise InvalidRequestError(
            message,
            details={"expected_path": str(path)},
        )
    return path


__all__ = [
    "CLIP_TOKENIZER_BPE_PATH",
    "CLIP_VIT_B_32_PATH",
    "MOBILECLIP_BLT_TS_PATH",
    "ClipSimpleTokenizer",
    "MobileClipTorchScriptTextEncoder",
    "TextEncoderAssets",
    "clip_tokenize",
    "get_or_create_mobileclip_blt_text_encoder",
    "load_clip_simple_tokenizer",
    "resolve_clip_tokenizer_bpe_path",
    "resolve_mobileclip_blt_ts_path",
    "resolve_text_encoder_assets",
]
