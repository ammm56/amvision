"""Barcode/QR 协议节点规格定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


NODE_PACK_ID = "barcode.protocol-nodes"
NODE_PACK_VERSION = "0.1.0"
DRAW_BARCODE_RESULTS_NODE_TYPE_ID = "custom.barcode.draw-results"


@dataclass(frozen=True)
class BarcodeNodeSpec:
    """描述单个 Barcode decode 节点的稳定规格。

    字段：
    - node_type_id：节点类型 id。
    - display_name：节点显示名称。
    - description：节点职责说明。
    - format_member_name：zxingcpp.BarcodeFormat 的成员名称。
    - requested_format：节点面向 workflow 暴露的目标格式或扫描范围名称。
    - capability_slug：节点能力标签后缀。
    - family_key：节点所属条码家族标识。
    - variant_key：节点所属变体标识。
    - scope_kind：节点匹配范围，支持 exact 或 group。
    """

    node_type_id: str
    display_name: str
    description: str
    format_member_name: str
    requested_format: str
    capability_slug: str
    family_key: str
    variant_key: str
    scope_kind: Literal["exact", "group"] = "exact"


def _spec(
    node_type_id: str,
    display_name: str,
    description: str,
    format_member_name: str,
    requested_format: str,
    capability_slug: str,
    family_key: str,
    variant_key: str,
    *,
    scope_kind: Literal["exact", "group"] = "exact",
) -> BarcodeNodeSpec:
    """构造单个 BarcodeNodeSpec。"""

    return BarcodeNodeSpec(
        node_type_id=node_type_id,
        display_name=display_name,
        description=description,
        format_member_name=format_member_name,
        requested_format=requested_format,
        capability_slug=capability_slug,
        family_key=family_key,
        variant_key=variant_key,
        scope_kind=scope_kind,
    )


BARCODE_NODE_SPECS: tuple[BarcodeNodeSpec, ...] = (
    _spec(
        "custom.barcode.all-readable-decode",
        "Decode All Readable Barcodes",
        "扫描输入图片中 zxing 当前可读取的全部条码与二维码制式，适合未知制式混扫场景。",
        "AllReadable",
        "All Readable",
        "all-readable",
        "mixed",
        "all-readable",
        scope_kind="group",
    ),
    _spec(
        "custom.barcode.all-linear-decode",
        "Decode All Linear Barcodes",
        "扫描输入图片中的全部一维条码制式，适合物流、零售与工业通用线性码场景。",
        "AllLinear",
        "All Linear",
        "all-linear",
        "linear",
        "all-linear",
        scope_kind="group",
    ),
    _spec(
        "custom.barcode.all-matrix-decode",
        "Decode All Matrix Barcodes",
        "扫描输入图片中的全部矩阵码制式，适合票据、证件、标签与文档二维码场景。",
        "AllMatrix",
        "All Matrix",
        "all-matrix",
        "matrix",
        "all-matrix",
        scope_kind="group",
    ),
    _spec(
        "custom.barcode.all-retail-decode",
        "Decode All Retail Barcodes",
        "扫描输入图片中的全部零售条码制式，适合 EAN、UPC、DataBar 等零售识读场景。",
        "AllRetail",
        "All Retail",
        "all-retail",
        "retail",
        "all-retail",
        scope_kind="group",
    ),
    _spec(
        "custom.barcode.all-industrial-decode",
        "Decode All Industrial Barcodes",
        "扫描输入图片中的全部工业条码制式，适合物流、追踪、制造与医药标识场景。",
        "AllIndustrial",
        "All Industrial",
        "all-industrial",
        "industrial",
        "all-industrial",
        scope_kind="group",
    ),
    _spec(
        "custom.barcode.all-gs1-decode",
        "Decode All GS1 Barcodes",
        "扫描输入图片中的全部 GS1 相关条码制式，适合带 AI 编码的供应链与追溯场景。",
        "AllGS1",
        "All GS1",
        "all-gs1",
        "gs1",
        "all-gs1",
        scope_kind="group",
    ),
    _spec(
        "custom.barcode.ean-upc-decode",
        "Decode EAN/UPC Family",
        "扫描输入图片中的 EAN/UPC 家族条码，适合标准零售主码与附加码识读场景。",
        "EANUPC",
        "EAN/UPC Family",
        "ean-upc",
        "retail",
        "ean-upc-family",
        scope_kind="group",
    ),
    _spec(
        "custom.barcode.databar-decode",
        "Decode DataBar Family",
        "扫描输入图片中的 DataBar 家族条码，适合 GS1 零售与扩展属性识读场景。",
        "DataBar",
        "DataBar Family",
        "databar-family",
        "retail",
        "databar-family",
        scope_kind="group",
    ),
    _spec(
        "custom.barcode.ean13-decode",
        "EAN-13 Decode",
        "从输入图片中解码 EAN-13 条码。",
        "EAN13",
        "EAN-13",
        "ean13",
        "retail",
        "ean13",
    ),
    _spec(
        "custom.barcode.ean8-decode",
        "EAN-8 Decode",
        "从输入图片中解码 EAN-8 条码。",
        "EAN8",
        "EAN-8",
        "ean8",
        "retail",
        "ean8",
    ),
    _spec(
        "custom.barcode.ean5-decode",
        "EAN-5 Decode",
        "从输入图片中解码 EAN-5 附加码。",
        "EAN5",
        "EAN-5",
        "ean5",
        "retail",
        "ean5",
    ),
    _spec(
        "custom.barcode.ean2-decode",
        "EAN-2 Decode",
        "从输入图片中解码 EAN-2 附加码。",
        "EAN2",
        "EAN-2",
        "ean2",
        "retail",
        "ean2",
    ),
    _spec(
        "custom.barcode.upca-decode",
        "UPC-A Decode",
        "从输入图片中解码 UPC-A 条码。",
        "UPCA",
        "UPC-A",
        "upca",
        "retail",
        "upca",
    ),
    _spec(
        "custom.barcode.upce-decode",
        "UPC-E Decode",
        "从输入图片中解码 UPC-E 条码。",
        "UPCE",
        "UPC-E",
        "upce",
        "retail",
        "upce",
    ),
    _spec(
        "custom.barcode.isbn-decode",
        "ISBN Decode",
        "从输入图片中解码 ISBN 图书条码。",
        "ISBN",
        "ISBN",
        "isbn",
        "retail",
        "isbn",
    ),
    _spec(
        "custom.barcode.databar-omnidirectional-decode",
        "DataBar Omnidirectional Decode",
        "从输入图片中解码 DataBar Omnidirectional 条码。",
        "DataBarOmni",
        "DataBar Omnidirectional",
        "databar-omnidirectional",
        "retail",
        "databar-omnidirectional",
    ),
    _spec(
        "custom.barcode.databar-stacked-decode",
        "DataBar Stacked Decode",
        "从输入图片中解码 DataBar Stacked 条码。",
        "DataBarStk",
        "DataBar Stacked",
        "databar-stacked",
        "retail",
        "databar-stacked",
    ),
    _spec(
        "custom.barcode.databar-limited-decode",
        "DataBar Limited Decode",
        "从输入图片中解码 DataBar Limited 条码。",
        "DataBarLimited",
        "DataBar Limited",
        "databar-limited",
        "retail",
        "databar-limited",
    ),
    _spec(
        "custom.barcode.databar-expanded-decode",
        "DataBar Expanded Decode",
        "从输入图片中解码 DataBar Expanded 条码。",
        "DataBarExpanded",
        "DataBar Expanded",
        "databar-expanded",
        "retail",
        "databar-expanded",
    ),
    _spec(
        "custom.barcode.databar-expanded-stacked-decode",
        "DataBar Expanded Stacked Decode",
        "从输入图片中解码 DataBar Expanded Stacked 条码。",
        "DataBarExpStk",
        "DataBar Expanded Stacked",
        "databar-expanded-stacked",
        "retail",
        "databar-expanded-stacked",
    ),
    _spec(
        "custom.barcode.codabar-decode",
        "Codabar Decode",
        "从输入图片中解码 Codabar 条码。",
        "Codabar",
        "Codabar",
        "codabar",
        "industrial",
        "codabar",
    ),
    _spec(
        "custom.barcode.code39-standard-decode",
        "Code 39 Standard Decode",
        "从输入图片中解码 Code 39 Standard 条码。",
        "Code39Std",
        "Code 39 Standard",
        "code39-standard",
        "industrial",
        "code39-standard",
    ),
    _spec(
        "custom.barcode.code39-extended-decode",
        "Code 39 Extended Decode",
        "从输入图片中解码 Code 39 Extended 条码。",
        "Code39Ext",
        "Code 39 Extended",
        "code39-extended",
        "industrial",
        "code39-extended",
    ),
    _spec(
        "custom.barcode.pzn-decode",
        "PZN Decode",
        "从输入图片中解码 PZN 医药条码。",
        "PZN",
        "PZN",
        "pzn",
        "industrial",
        "pzn",
    ),
    _spec(
        "custom.barcode.code32-decode",
        "Code 32 Decode",
        "从输入图片中解码 Code 32 条码。",
        "Code32",
        "Code 32",
        "code32",
        "industrial",
        "code32",
    ),
    _spec(
        "custom.barcode.code93-decode",
        "Code 93 Decode",
        "从输入图片中解码 Code 93 条码。",
        "Code93",
        "Code 93",
        "code93",
        "industrial",
        "code93",
    ),
    _spec(
        "custom.barcode.code128-decode",
        "Code 128 Decode",
        "从输入图片中解码 Code 128 条码。",
        "Code128",
        "Code 128",
        "code128",
        "industrial",
        "code128",
    ),
    _spec(
        "custom.barcode.itf-decode",
        "ITF Decode",
        "从输入图片中解码 ITF 条码。",
        "ITF",
        "ITF",
        "itf",
        "industrial",
        "itf",
    ),
    _spec(
        "custom.barcode.itf14-decode",
        "ITF-14 Decode",
        "从输入图片中解码 ITF-14 条码。",
        "ITF14",
        "ITF-14",
        "itf14",
        "industrial",
        "itf14",
    ),
    _spec(
        "custom.barcode.aztec-code-decode",
        "Aztec Code Decode",
        "从输入图片中解码 Aztec Code。",
        "AztecCode",
        "Aztec Code",
        "aztec-code",
        "matrix",
        "aztec-code",
    ),
    _spec(
        "custom.barcode.aztec-rune-decode",
        "Aztec Rune Decode",
        "从输入图片中解码 Aztec Rune。",
        "AztecRune",
        "Aztec Rune",
        "aztec-rune",
        "matrix",
        "aztec-rune",
    ),
    _spec(
        "custom.barcode.datamatrix-decode",
        "Data Matrix ECC200 Decode",
        "从输入图片中解码 Data Matrix ECC200。",
        "DataMatrix",
        "Data Matrix ECC200",
        "datamatrix",
        "matrix",
        "datamatrix-ecc200",
    ),
    _spec(
        "custom.barcode.maxicode-decode",
        "MaxiCode Decode",
        "从输入图片中解码 MaxiCode；当前运行时以 partial read support 为主。",
        "MaxiCode",
        "MaxiCode",
        "maxicode",
        "matrix",
        "maxicode",
    ),
    _spec(
        "custom.barcode.pdf417-decode",
        "PDF417 Decode",
        "从输入图片中解码 PDF417。",
        "PDF417",
        "PDF417",
        "pdf417",
        "matrix",
        "pdf417",
    ),
    _spec(
        "custom.barcode.compact-pdf417-decode",
        "Compact PDF417 Decode",
        "从输入图片中解码 Compact PDF417。",
        "CompactPDF417",
        "Compact PDF417",
        "compact-pdf417",
        "matrix",
        "compact-pdf417",
    ),
    _spec(
        "custom.barcode.micro-pdf417-decode",
        "MicroPDF417 Decode",
        "从输入图片中解码 MicroPDF417。",
        "MicroPDF417",
        "MicroPDF417",
        "micro-pdf417",
        "matrix",
        "micro-pdf417",
    ),
    _spec(
        "custom.barcode.qr-code-decode",
        "QR Code Decode",
        "从输入图片中解码 QR Code，覆盖常规 QR Code 识读场景。",
        "QRCode",
        "QR Code",
        "qr-code",
        "matrix",
        "qr-code",
    ),
    _spec(
        "custom.barcode.qr-code-model1-decode",
        "QR Code Model 1 Decode",
        "从输入图片中解码 QR Code Model 1。",
        "QRCodeModel1",
        "QR Code Model 1",
        "qr-code-model1",
        "matrix",
        "qr-code-model1",
    ),
    _spec(
        "custom.barcode.qr-code-model2-decode",
        "QR Code Model 2 Decode",
        "从输入图片中解码 QR Code Model 2。",
        "QRCodeModel2",
        "QR Code Model 2",
        "qr-code-model2",
        "matrix",
        "qr-code-model2",
    ),
    _spec(
        "custom.barcode.micro-qr-code-decode",
        "Micro QR Code Decode",
        "从输入图片中解码 Micro QR Code。",
        "MicroQRCode",
        "Micro QR Code",
        "micro-qr-code",
        "matrix",
        "micro-qr-code",
    ),
    _spec(
        "custom.barcode.rmqr-code-decode",
        "rMQR Decode",
        "从输入图片中解码 rMQR。",
        "RMQRCode",
        "rMQR",
        "rmqr",
        "matrix",
        "rmqr",
    ),
)


def build_common_parameter_schema() -> dict[str, object]:
    """构造 Barcode decode 节点共享参数 schema。"""

    return {
        "type": "object",
        "properties": {
            "try_rotate": {"type": "boolean"},
            "try_downscale": {"type": "boolean"},
            "try_invert": {"type": "boolean"},
            "is_pure": {"type": "boolean"},
            "return_errors": {"type": "boolean"},
            "text_mode": {
                "type": "string",
                "enum": ["plain", "hri", "escaped", "hex", "eci", "hex-eci"],
            },
            "binarizer": {
                "type": "string",
                "enum": ["local-average", "global-histogram", "fixed-threshold", "bool-cast"],
            },
            "ean_add_on_symbol": {
                "type": "string",
                "enum": ["ignore", "read", "require"],
            },
        },
    }


def get_barcode_node_specs() -> tuple[BarcodeNodeSpec, ...]:
    """返回当前 pack 全部 Barcode 节点规格。"""

    return BARCODE_NODE_SPECS


def build_decode_node_module_name(node_type_id: str) -> str:
    """把节点类型 id 映射为 backend/nodes 目录下的模块文件名。

    参数：
    - node_type_id：节点类型 id。

    返回：
    - str：不带 .py 的模块名称。
    """

    prefix = "custom.barcode."
    normalized_node_type_id = node_type_id.strip()
    if not normalized_node_type_id.startswith(prefix):
        raise ValueError("barcode 节点类型 id 必须以 custom.barcode. 开头")
    return normalized_node_type_id[len(prefix) :].replace("-", "_")

