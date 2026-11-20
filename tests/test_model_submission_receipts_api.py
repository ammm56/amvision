"""验证训练、转换的提交回执与任务创建互斥。"""

from pathlib import Path
from uuid import uuid4

import pytest

from tests.test_yolox_conversion_tasks_api import (
    _build_headers as conversion_headers,
)
from tests.test_yolox_conversion_tasks_api import (
    _seed_placeholder_model_version,
)
from tests.test_yolox_training_api import (
    _build_training_headers,
    _create_test_client,
    _seed_completed_dataset_export,
    _training_execution,
)


@pytest.mark.parametrize('kind', ['training', 'conversion'])
def test_model_submission_receipt_prevents_duplicate_and_late_creates(
    tmp_path: Path, kind: str,
) -> None:
    """已提交时返回同一任务；先查询时封闭原编号，需用新编号提交。"""
    client, session_factory, storage, _queue = _create_test_client(tmp_path)
    base = f'/api/v1/models/detection/{kind}-tasks'
    body = {'project_id': 'project-1', 'model_type': 'yolox'}
    if kind == 'training':
        export = _seed_completed_dataset_export(
            session_factory=session_factory,
            dataset_storage=storage,
            dataset_export_id='dataset-export-receipt',
            manifest_object_key='projects/project-1/datasets/dataset-1/exports/receipt/manifest.json',
        )
        path = base
        headers = _build_training_headers()
        body.update(
            dataset_export_id=export.dataset_export_id, recipe_id='yolox-default',
            model_scale='s', output_model_name='receipt-training',
            execution=_training_execution(),
        )
    else:
        path = f'{base}/onnx'
        headers = conversion_headers()
        body.update(source_model_version_id=_seed_placeholder_model_version(
            session_factory=session_factory, dataset_storage=storage,
        ), display_name='receipt-conversion')

    def submit(token: str):
        return client.post(path, headers={**headers, 'X-Model-Submission-Id': token}, json=body)

    def resolve(token: str):
        return client.post(f'/api/v1/model-submissions/{token}/resolve', headers=headers,
                           json={'project_id': 'project-1'})

    try:
        with client:
            closed, sent = str(uuid4()), str(uuid4())
            resolve_closed = resolve(closed)
            assert resolve_closed.status_code == 200, resolve_closed.text
            assert resolve_closed.json() == {'status': 'not_created', 'task_id': None}
            late = submit(closed)
            assert late.status_code == 409, late.text
            assert resolve(closed).json() == resolve_closed.json()
            submitted = submit(sent)
            assert submitted.status_code == 202, submitted.text
            task_id = submitted.json()['task_id']
            assert resolve(sent).json() == {'status': 'accepted', 'task_id': task_id}
            duplicate = submit(sent)
            assert duplicate.status_code == 409, duplicate.text
            assert duplicate.json()['error']['details']['submission_id'] == sent
            assert resolve(sent).json() == {'status': 'accepted', 'task_id': task_id}
            listed = client.get(base, headers=headers, params={'project_id': 'project-1'})
            assert listed.status_code == 200, listed.text
            assert [task['task_id'] for task in listed.json()] == [task_id]
    finally:
        session_factory.engine.dispose()
