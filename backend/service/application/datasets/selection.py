"""Worker 对不可变版本执行选择；不把类别筛选误解释为删除其他标注。"""

from backend.contracts.datasets.sample_selection import DatasetSampleSelection
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import (
    DatasetSample,
    DatasetVersion,
)


def select_samples(
    version: DatasetVersion, raw: dict | None
) -> tuple[DatasetSample, ...]:
    """返回完整样本及其全部标注，外部版本或失效 ID 会阻止执行。"""
    if raw is None:
        return version.samples
    selection = DatasetSampleSelection.model_validate(raw)
    if selection.mode == "ids":
        wanted = set(selection.sample_ids)
        selected = tuple(s for s in version.samples if s.sample_id in wanted)
        if len(selected) != len(wanted):
            raise InvalidRequestError("选择包含不属于当前版本的样本")
    else:
        selected = tuple(
            s
            for s in version.samples
            if (
                not selection.q
                or selection.q.casefold() in s.file_name.casefold()
                or selection.q.casefold() in s.sample_id.casefold()
            )
            and (not selection.split or selection.split == s.split)
            and (
                selection.category_id is None
                or any(a.category_id == selection.category_id for a in s.annotations)
            )
            and (
                not selection.annotation_state
                or bool(s.annotations) == (selection.annotation_state == "annotated")
            )
        )
    if not selected:
        raise InvalidRequestError("当前选择没有样本，请重新选择")
    return selected
