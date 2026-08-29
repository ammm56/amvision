"""FastAPI 控制面冷启动导入边界测试。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_fastapi_control_plane_import_does_not_load_torch() -> None:
    """只导入 API 路由时不得加载训练、转换或评估模型运行时。"""

    repository_root = Path(__file__).resolve().parents[1]
    command = (
        "import sys; "
        "import backend.service.api.app; "
        "assert 'torch' not in sys.modules, "
        "'FastAPI control-plane import unexpectedly loaded torch'"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=repository_root,
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_fastapi_control_plane_startup_does_not_load_torch() -> None:
    """加载全部节点目录并启动空控制面时仍不得加载模型运行时。"""

    repository_root = Path(__file__).resolve().parents[1]
    command = "\n".join(
        (
            "import sys",
            "import tempfile",
            "from pathlib import Path",
            "from tests.api_test_support import create_api_test_context",
            "with tempfile.TemporaryDirectory() as directory:",
            "    context = create_api_test_context(",
            "        Path(directory),",
            "        database_name='startup-import-boundary.db',",
            "        enable_local_buffer_broker=False,",
            "    )",
            "    with context.client:",
            "        assert 'torch' not in sys.modules, (",
            "            'FastAPI startup unexpectedly loaded torch'",
            "        )",
            "    context.session_factory.engine.dispose()",
        )
    )
    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=repository_root,
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_rfdetr_pretrained_registration_does_not_load_torch() -> None:
    """启动 seeder 的 RF-DETR 元数据登记不得加载模型执行 core。"""

    repository_root = Path(__file__).resolve().parents[1]
    command = "\n".join(
        (
            "import sys",
            "from backend.service.application.models.catalog.rfdetr import (",
            "    SqlAlchemyRfdetrModelService,",
            ")",
            "from backend.service.application.models.registry.model_service import (",
            "    PretrainedRegistrationRequest,",
            ")",
            "from backend.service.infrastructure.db.schema import (",
            "    initialize_database_schema,",
            ")",
            "from backend.service.infrastructure.db.session import (",
            "    DatabaseSettings,",
            "    SessionFactory,",
            ")",
            "factory = SessionFactory(DatabaseSettings(url='sqlite:///:memory:'))",
            "initialize_database_schema(factory)",
            "SqlAlchemyRfdetrModelService(session_factory=factory).register_pretrained(",
            "    PretrainedRegistrationRequest(",
            "        model_name='rfdetr',",
            "        storage_uri='models/pretrained/rfdetr/fake.pth',",
            "        model_scale='nano',",
            "        model_version_id=(",
            "            'mv-pretrained-rfdetr-detection-nano-boundary'",
            "        ),",
            "        checkpoint_file_id='file-boundary',",
            "        task_type='detection',",
            "        metadata={",
            "            'checkpoint_model_config': {",
            "                'num_queries': 300,",
            "                'group_detr': 13,",
            "            },",
            "        },",
            "    )",
            ")",
            "assert 'torch' not in sys.modules, (",
            "    'RF-DETR metadata registration unexpectedly loaded torch'",
            ")",
            "factory.engine.dispose()",
        )
    )
    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=repository_root,
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
