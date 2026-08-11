"""模型独立评估使用的 manifest split 选择规则。"""

from __future__ import annotations


def select_independent_evaluation_split(
    split_entries: object,
) -> dict[str, object] | None:
    """按 test、validation、首个有效 split 的顺序选择唯一数据划分。"""

    entries = split_entries if isinstance(split_entries, list) else []
    valid_splits = [entry for entry in entries if isinstance(entry, dict)]
    for preferred_names in (("test",), ("val", "valid", "validation")):
        selected = next(
            (
                split
                for split in valid_splits
                if str(split.get("name", "")).strip().lower() in preferred_names
            ),
            None,
        )
        if selected is not None:
            return selected
    return valid_splits[0] if valid_splits else None


__all__ = ["select_independent_evaluation_split"]
