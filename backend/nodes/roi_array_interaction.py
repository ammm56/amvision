"""矩形网格和上游 ROI 阵列共用的图片步距取参声明。"""

from backend.nodes.debug_image_panel import build_interaction_tool


def build_array_step_tools(*, anchor, column, row, vector_parameters=False):
    """分别编辑列、行向量；方向从首槽同一特征指向相邻槽，单位为图像像素。"""
    tools = []
    for label, vector, targets in (
        (
            "Column Step",
            column,
            ["column_step_xy"] if vector_parameters else ["step_x", "column_step_y"],
        ),
        (
            "Row Step",
            row,
            ["row_step_xy"] if vector_parameters else ["row_step_x", "step_y"],
        ),
    ):
        tools.append(
            build_interaction_tool(
                "line",
                label,
                targets,
                extra={
                    "initial_points_xy": [
                        list(anchor),
                        [anchor[0] + vector[0], anchor[1] + vector[1]],
                    ]
                },
            )
        )
    return tools
