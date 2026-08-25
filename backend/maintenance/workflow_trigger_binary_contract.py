"""生成并校验 Workflow Trigger mailbox 跨语言二进制契约。"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT
    / "backend"
    / "contracts"
    / "ipc"
    / "schemas"
    / "workflow_trigger_mailbox.v1.json"
)
PYTHON_OUTPUT_PATH = (
    ROOT / "backend" / "contracts" / "ipc" / "workflow_trigger_mailbox_v1.py"
)
CSHARP_OUTPUT_PATH = (
    ROOT
    / "sdks"
    / "dotnet"
    / "src"
    / "Amvar.Vision"
    / "SharedMemory"
    / "WorkflowTriggerMailboxV1.g.cs"
)
FIXTURE_OUTPUT_PATH = (
    ROOT / "tests" / "fixtures" / "workflow_trigger_mailbox.v1.fixture.json"
)
CSHARP_FIXTURE_OUTPUT_PATH = (
    ROOT
    / "sdks"
    / "dotnet"
    / "tests"
    / "Amvar.Vision.ContractTests"
    / "WorkflowTriggerMailboxV1Fixture.g.cs"
)

_SCALAR_FORMATS = {"u32": "I", "i32": "i", "u64": "Q"}
_SCALAR_SIZES = {"u32": 4, "i32": 4, "u64": 8}


class BinaryContractError(ValueError):
    """表示 binary schema 或生成结果不合法。"""


def _load_schema() -> dict[str, Any]:
    """读取 binary contract 单一事实源。"""

    payload = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BinaryContractError("binary contract 顶层必须是 JSON object")
    return payload


def _field_size(type_name: str) -> int:
    """返回 schema 字段的固定宽度。"""

    if type_name in _SCALAR_SIZES:
        return _SCALAR_SIZES[type_name]
    if type_name.startswith("bytes:"):
        try:
            size = int(type_name.split(":", maxsplit=1)[1])
        except ValueError as error:
            raise BinaryContractError(f"非法 bytes 字段类型：{type_name}") from error
        if size <= 0:
            raise BinaryContractError(f"bytes 字段宽度必须大于 0：{type_name}")
        return size
    raise BinaryContractError(f"不支持的字段类型：{type_name}")


def _field_format(type_name: str) -> str:
    """返回 Python struct 字段格式。"""

    if type_name in _SCALAR_FORMATS:
        return _SCALAR_FORMATS[type_name]
    return f"{_field_size(type_name)}s"


def _validate_schema(schema: dict[str, Any]) -> None:
    """验证 layout 无重叠、无隐式 padding 且满足固定对齐。"""

    if schema.get("byte_order") != "little":
        raise BinaryContractError("Workflow Trigger mailbox 只允许 little-endian")
    alignment = int(schema.get("alignment_bytes", 0))
    if alignment != 8:
        raise BinaryContractError("Workflow Trigger mailbox 固定使用 8-byte 对齐")

    layouts = schema.get("layouts")
    if not isinstance(layouts, dict) or not layouts:
        raise BinaryContractError("binary contract 缺少 layouts")
    for layout_name, layout in layouts.items():
        if not isinstance(layout, dict):
            raise BinaryContractError(f"layout 必须是 object：{layout_name}")
        size = int(layout.get("size", 0))
        fields = layout.get("fields")
        if size <= 0 or size % alignment != 0 or not isinstance(fields, list):
            raise BinaryContractError(f"layout 大小或字段非法：{layout_name}")
        cursor = 0
        names: set[str] = set()
        for field in fields:
            if not isinstance(field, dict):
                raise BinaryContractError(f"字段必须是 object：{layout_name}")
            name = str(field.get("name", ""))
            type_name = str(field.get("type", ""))
            offset = int(field.get("offset", -1))
            if not name or name in names:
                raise BinaryContractError(f"字段名称为空或重复：{layout_name}.{name}")
            if offset != cursor:
                raise BinaryContractError(
                    f"字段必须连续且显式描述 padding：{layout_name}.{name} "
                    f"expected={cursor} actual={offset}"
                )
            names.add(name)
            cursor += _field_size(type_name)
        if cursor != size:
            raise BinaryContractError(
                f"layout 大小不匹配：{layout_name} expected={size} actual={cursor}"
            )
        format_text = "<" + "".join(
            _field_format(str(field["type"])) for field in fields
        )
        if struct.calcsize(format_text) != size:
            raise BinaryContractError(f"struct 大小不匹配：{layout_name}")

    checksum = schema.get("checksum")
    if not isinstance(checksum, dict) or checksum.get("algorithm") != "crc32-ieee":
        raise BinaryContractError("当前冻结契约必须使用 CRC32 IEEE")
    import zlib

    fixture_bytes = str(checksum["fixture_text_utf8"]).encode("utf-8")
    expected = int(str(checksum["fixture_value"]), 16)
    if zlib.crc32(fixture_bytes) & 0xFFFFFFFF != expected:
        raise BinaryContractError("checksum fixture 与 CRC32 IEEE 不一致")


def _constant_name(value: str) -> str:
    """把 snake_case 名称转换为大写常量名。"""

    return value.upper().replace("-", "_")


def _pascal_name(value: str) -> str:
    """把 snake_case 名称转换为 C# PascalCase 名称。"""

    return "".join(part.capitalize() for part in value.replace("-", "_").split("_"))


def _layout_format(layout: dict[str, Any]) -> str:
    """构造一个 layout 的 Python struct 格式。"""

    return "<" + "".join(
        _field_format(str(field["type"])) for field in layout["fields"]
    )


def _fixture_value(field: dict[str, Any], raw_value: object | None) -> object:
    """把 fixture JSON 值转换为 struct 可写值。"""

    type_name = str(field["type"])
    if type_name.startswith("bytes:"):
        size = _field_size(type_name)
        if raw_value is None:
            return bytes(size)
        value = bytes.fromhex(str(raw_value))
        if len(value) != size:
            raise BinaryContractError(
                f"fixture bytes 宽度不匹配：{field['name']} expected={size} actual={len(value)}"
            )
        return value
    if raw_value is None:
        return 0
    return int(raw_value)


def _pack_fixture_layout(
    *, layout: dict[str, Any], values: dict[str, Any]
) -> bytes:
    """按 layout 打包一段跨语言 fixture。"""

    arguments = [
        _fixture_value(field, values.get(str(field["name"])))
        for field in layout["fields"]
    ]
    return struct.pack(_layout_format(layout), *arguments)


def _schema_digest() -> str:
    """返回 schema 原始 bytes 的 SHA-256。"""

    return hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()


def _render_python(schema: dict[str, Any]) -> str:
    """生成 Python layout、offset 与 enum 常量。"""

    lines = [
        '"""由 workflow_trigger_mailbox.v1.json 自动生成；禁止手工修改。"""',
        "",
        "from __future__ import annotations",
        "",
        "import struct",
        "",
        f'CONTRACT_ID = {schema["contract_id"]!r}',
        f'SCHEMA_SHA256 = {_schema_digest()!r}',
        'BYTE_ORDER = "little"',
        f'ALIGNMENT_BYTES = {int(schema["alignment_bytes"])}',
        f'MAGIC = bytes.fromhex({schema["fixture"]["file_header"]["magic"]!r})',
        "VERSION = 1",
        "CHECKSUM_ALGORITHM_CRC32_IEEE = 1",
        f'RELATIVE_MMAP_PATH = {schema["path"]["relative_mmap_path"]!r}',
        f'OWNER_LOCK_SUFFIX = {schema["path"]["owner_lock_suffix"]!r}',
        f'DESCRIPTOR_GUARD_SUFFIX = {schema["path"]["descriptor_guard_suffix"]!r}',
        "",
    ]
    for name, value in schema["capacity"].items():
        lines.append(f"{_constant_name(name)} = {int(value)}")
    lines.append("")
    for layout_name, layout in schema["layouts"].items():
        prefix = _constant_name(layout_name)
        lines.append(f'{prefix}_STRUCT = struct.Struct({_layout_format(layout)!r})')
        lines.append(f"{prefix}_SIZE = {int(layout['size'])}")
        for field in layout["fields"]:
            lines.append(
                f"{prefix}_{_constant_name(str(field['name']))}_OFFSET = "
                f"{int(field['offset'])}"
            )
        lines.append("")
    for enum_name, entries in schema["enums"].items():
        prefix = _constant_name(enum_name)
        for entry_name, value in entries.items():
            lines.append(
                f"{prefix}_{_constant_name(entry_name)} = {int(value)}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_csharp(schema: dict[str, Any]) -> str:
    """生成 .NET Framework 4.7.2 可用的 layout、offset 与 enum 常量。"""

    lines = [
        "// 由 workflow_trigger_mailbox.v1.json 自动生成；禁止手工修改。",
        "namespace Amvar.Vision.SharedMemory",
        "{",
        "    internal static class WorkflowTriggerMailboxV1",
        "    {",
        f'        internal const string ContractId = "{schema["contract_id"]}";',
        f'        internal const string SchemaSha256 = "{_schema_digest()}";',
        "        internal const int Version = 1;",
        f"        internal const int AlignmentBytes = {int(schema['alignment_bytes'])};",
        "        internal const int ChecksumAlgorithmCrc32Ieee = 1;",
        f'        internal const string RelativeMmapPath = "{schema["path"]["relative_mmap_path"]}";',
        f'        internal const string OwnerLockSuffix = "{schema["path"]["owner_lock_suffix"]}";',
        f'        internal const string DescriptorGuardSuffix = "{schema["path"]["descriptor_guard_suffix"]}";',
    ]
    for name, value in schema["capacity"].items():
        lines.append(
            f"        internal const int {_pascal_name(name)} = {int(value)};"
        )
    for layout_name, layout in schema["layouts"].items():
        prefix = _pascal_name(layout_name)
        lines.append(f"        internal const int {prefix}Size = {int(layout['size'])};")
        for field in layout["fields"]:
            lines.append(
                f"        internal const int {prefix}{_pascal_name(str(field['name']))}Offset = "
                f"{int(field['offset'])};"
            )
    for enum_name, entries in schema["enums"].items():
        prefix = _pascal_name(enum_name)
        for entry_name, value in entries.items():
            lines.append(
                f"        internal const int {prefix}{_pascal_name(entry_name)} = {int(value)};"
            )
    lines.extend(["    }", "}", ""])
    return "\n".join(lines)


def _build_fixture(schema: dict[str, Any]) -> dict[str, Any]:
    """生成跨 Python/.NET 共用的固定二进制 fixture。"""

    layouts = schema["layouts"]
    fixture_values = schema["fixture"]
    packed = {
        layout_name: _pack_fixture_layout(
            layout=layout,
            values=fixture_values[layout_name],
        ).hex()
        for layout_name, layout in layouts.items()
    }
    checksum = schema["checksum"]
    return {
        "format_id": "amvision.binary-contract-fixture.v1",
        "contract_id": schema["contract_id"],
        "schema_sha256": _schema_digest(),
        "byte_order": schema["byte_order"],
        "checksum": {
            "algorithm": checksum["algorithm"],
            "algorithm_id": int(checksum["algorithm_id"]),
            "input_hex": str(checksum["fixture_text_utf8"]).encode("utf-8").hex(),
            "value": str(checksum["fixture_value"]).lower(),
        },
        "values": fixture_values,
        "packed_hex": packed,
    }


def _render_fixture(schema: dict[str, Any]) -> str:
    """返回规范化 fixture JSON。"""

    return json.dumps(
        _build_fixture(schema),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _csharp_integer_literal(type_name: str, value: int) -> str:
    """返回不会发生符号或宽度歧义的 C# 整数字面量。"""

    if type_name == "u64":
        return f"{value}UL"
    if type_name == "u32":
        return f"{value}U"
    return str(value)


def _render_csharp_fixture(schema: dict[str, Any]) -> str:
    """生成会真实写入各字段并核对 Python fixture 的 .NET 契约门禁。"""

    fixture = _build_fixture(schema)
    lines = [
        "// 由 workflow_trigger_mailbox.v1.json 自动生成；禁止手工修改。",
        "using System;",
        "using System.Text;",
        "using Amvar.Vision.SharedMemory;",
        "",
        "namespace Amvar.Vision.ContractTests",
        "{",
        "    internal static class WorkflowTriggerMailboxV1Fixture",
        "    {",
        "        internal static void Verify()",
        "        {",
        f'            AssertHex(BuildFileHeader(), "{fixture["packed_hex"]["file_header"]}", "file header");',
        f'            AssertHex(BuildDescriptorHeader(), "{fixture["packed_hex"]["descriptor_header"]}", "descriptor header");',
        f'            AssertHex(BuildPageHeader(), "{fixture["packed_hex"]["page_header"]}", "page header");',
        f'            var checksumInput = Encoding.UTF8.GetBytes("{schema["checksum"]["fixture_text_utf8"]}");',
        f"            if (Crc32Ieee.Compute(checksumInput) != {int(str(schema['checksum']['fixture_value']), 16)}U)",
        "            {",
        '                throw new InvalidOperationException("CRC32 IEEE fixture 不一致。");',
        "            }",
        "        }",
        "",
    ]
    for layout_name, method_name in (
        ("file_header", "BuildFileHeader"),
        ("descriptor_header", "BuildDescriptorHeader"),
        ("page_header", "BuildPageHeader"),
    ):
        layout = schema["layouts"][layout_name]
        values = schema["fixture"][layout_name]
        prefix = _pascal_name(layout_name)
        lines.extend(
            [
                f"        private static byte[] {method_name}()",
                "        {",
                f"            var buffer = new byte[WorkflowTriggerMailboxV1.{prefix}Size];",
            ]
        )
        for field in layout["fields"]:
            field_name = str(field["name"])
            type_name = str(field["type"])
            if field_name not in values:
                continue
            offset_name = f"{prefix}{_pascal_name(field_name)}Offset"
            raw_value = values[field_name]
            if type_name.startswith("bytes:"):
                lines.append(
                    f'            CopyHex(buffer, WorkflowTriggerMailboxV1.{offset_name}, "{raw_value}");'
                )
            elif type_name == "u64":
                lines.append(
                    f"            WriteUInt64(buffer, WorkflowTriggerMailboxV1.{offset_name}, "
                    f"{_csharp_integer_literal(type_name, int(raw_value))});"
                )
            elif type_name == "u32":
                lines.append(
                    f"            WriteUInt32(buffer, WorkflowTriggerMailboxV1.{offset_name}, "
                    f"{_csharp_integer_literal(type_name, int(raw_value))});"
                )
            elif type_name == "i32":
                lines.append(
                    f"            WriteInt32(buffer, WorkflowTriggerMailboxV1.{offset_name}, "
                    f"{_csharp_integer_literal(type_name, int(raw_value))});"
                )
            else:
                raise BinaryContractError(f"fixture 不支持字段类型：{type_name}")
        lines.extend(["            return buffer;", "        }", ""])
    lines.extend(
        [
            "        private static void WriteUInt32(byte[] buffer, int offset, uint value)",
            "        {",
            "            buffer[offset] = (byte)value;",
            "            buffer[offset + 1] = (byte)(value >> 8);",
            "            buffer[offset + 2] = (byte)(value >> 16);",
            "            buffer[offset + 3] = (byte)(value >> 24);",
            "        }",
            "",
            "        private static void WriteInt32(byte[] buffer, int offset, int value)",
            "        {",
            "            WriteUInt32(buffer, offset, unchecked((uint)value));",
            "        }",
            "",
            "        private static void WriteUInt64(byte[] buffer, int offset, ulong value)",
            "        {",
            "            WriteUInt32(buffer, offset, (uint)value);",
            "            WriteUInt32(buffer, offset + 4, (uint)(value >> 32));",
            "        }",
            "",
            "        private static void CopyHex(byte[] buffer, int offset, string text)",
            "        {",
            "            for (var index = 0; index < text.Length; index += 2)",
            "            {",
            "                buffer[offset + index / 2] = Convert.ToByte(text.Substring(index, 2), 16);",
            "            }",
            "        }",
            "",
            "        private static void AssertHex(byte[] actual, string expected, string name)",
            "        {",
            "            var text = new StringBuilder(actual.Length * 2);",
            "            foreach (var value in actual)",
            "            {",
            '                text.Append(value.ToString("x2"));',
            "            }",
            "",
            "            if (!string.Equals(text.ToString(), expected, StringComparison.Ordinal))",
            "            {",
            '                throw new InvalidOperationException(name + " fixture 不一致。");',
            "            }",
            "        }",
            "    }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def _outputs(schema: dict[str, Any]) -> dict[Path, str]:
    """返回全部生成目标及内容。"""

    return {
        PYTHON_OUTPUT_PATH: _render_python(schema),
        CSHARP_OUTPUT_PATH: _render_csharp(schema),
        FIXTURE_OUTPUT_PATH: _render_fixture(schema),
        CSHARP_FIXTURE_OUTPUT_PATH: _render_csharp_fixture(schema),
    }


def write_outputs() -> None:
    """校验 schema 并覆盖全部生成文件。"""

    schema = _load_schema()
    _validate_schema(schema)
    for path, content in _outputs(schema).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def check_outputs() -> list[Path]:
    """返回缺失或与 schema 不一致的生成文件。"""

    schema = _load_schema()
    _validate_schema(schema)
    mismatches: list[Path] = []
    for path, expected in _outputs(schema).items():
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            mismatches.append(path)
    return mismatches


def main(argv: list[str] | None = None) -> int:
    """执行生成或只读一致性检查。"""

    parser = argparse.ArgumentParser(
        description="生成或校验 Workflow Trigger mailbox binary contract"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="覆盖生成文件")
    mode.add_argument("--check", action="store_true", help="仅检查生成文件")
    args = parser.parse_args(argv)
    if args.write:
        write_outputs()
        return 0
    mismatches = check_outputs()
    if mismatches:
        for path in mismatches:
            print(f"binary contract 生成文件不一致：{path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
