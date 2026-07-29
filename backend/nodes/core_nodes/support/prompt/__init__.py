"""共享 Prompt payload 构造与校验工具。"""

from .payloads import (
    build_image_reference_identity,
    build_prompt_regions_payload,
    build_text_prompts_payload,
    merge_prompt_regions_payloads,
    merge_text_prompts_payloads,
    require_non_empty_text,
    validate_applied_prompt_source_identity,
    validate_prompt_geometry_bounds,
)

__all__ = [
    "build_image_reference_identity",
    "build_prompt_regions_payload",
    "build_text_prompts_payload",
    "merge_prompt_regions_payloads",
    "merge_text_prompts_payloads",
    "require_non_empty_text",
    "validate_applied_prompt_source_identity",
    "validate_prompt_geometry_bounds",
]
