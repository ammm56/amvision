"""项目文档本地链接门禁。"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTATION_ROOT = REPOSITORY_ROOT / "docs"
MARKDOWN_LINK_PATTERN = re.compile(
    r"!?\[[^\]]*\]\("
    r"(?P<target><[^>]+>|[^)\s]+)"
    r"(?:\s+[\"'][^\"']*[\"'])?"
    r"\)"
)


def _iter_project_markdown_files() -> list[Path]:
    """返回纳入正式文档门禁的 Markdown 文件。"""

    return [
        REPOSITORY_ROOT / "README.md",
        REPOSITORY_ROOT / "AGENTS.md",
        *sorted(DOCUMENTATION_ROOT.rglob("*.md")),
    ]


def _resolve_local_link(source_path: Path, target: str) -> Path | None:
    """把 Markdown 链接解析为本地路径；网络地址与页内锚点返回空。"""

    normalized_target = target.removeprefix("<").removesuffix(">")
    if not normalized_target or normalized_target.startswith("#"):
        return None
    parsed = urlparse(normalized_target)
    if parsed.scheme or normalized_target.startswith("//"):
        return None
    path_text = unquote(normalized_target.split("#", maxsplit=1)[0])
    if not path_text:
        return None
    target_path = Path(path_text)
    if target_path.is_absolute():
        return target_path
    return (source_path.parent / target_path).resolve()


def test_project_markdown_local_links_resolve() -> None:
    """确保正式文档中的本地 Markdown 链接都有真实目标。"""

    broken_links: list[str] = []
    for source_path in _iter_project_markdown_files():
        source_text = source_path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK_PATTERN.finditer(source_text):
            target = match.group("target")
            resolved_path = _resolve_local_link(source_path, target)
            if resolved_path is None or resolved_path.exists():
                continue
            source_display = source_path.relative_to(REPOSITORY_ROOT).as_posix()
            broken_links.append(f"{source_display} -> {target}")

    assert broken_links == [], "发现失效的本地文档链接：\n" + "\n".join(
        broken_links
    )
