"""本地输入输出类 core node 支撑函数。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.local_io.csv import flatten_mapping_for_csv
from backend.nodes.core_nodes.support.local_io.files import (
    build_directory_file_record,
    build_local_file_summary,
    read_local_image_file,
    require_file_record_list,
)
from backend.nodes.core_nodes.support.local_io.inputs import resolve_value_or_result_input
from backend.nodes.core_nodes.support.local_io.paths import (
    resolve_local_directory_path_from_request,
    resolve_local_file_path_from_request,
    resolve_local_output_file_path,
    resolve_local_path_value_from_request,
)

__all__ = [
    "build_directory_file_record",
    "build_local_file_summary",
    "flatten_mapping_for_csv",
    "read_local_image_file",
    "require_file_record_list",
    "resolve_local_directory_path_from_request",
    "resolve_local_file_path_from_request",
    "resolve_local_output_file_path",
    "resolve_local_path_value_from_request",
    "resolve_value_or_result_input",
]
