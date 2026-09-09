"""项目公开文件独立读取权限和默认登录兼容。"""

from backend.service.settings import (
    BackendServiceAuthConfig,
    BackendServiceLocalAuthConfig,
)
from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
)
from tests.test_local_auth_api import _create_local_auth_test_client


def test_file_read_and_default_token_remain_independent(tmp_path):
    """真实创建账号验证默认登录关闭，但原 Token 仍全权限且文件目录不扩大。"""
    client, factory = _create_local_auth_test_client(
        tmp_path,
        database_name="file-access.db",
        auth_config=BackendServiceAuthConfig(
            mode="local",
            local_auth=BackendServiceLocalAuthConfig(
                initialize_default_user_on_empty_db=True
            ),
        ),
    )
    admin = {"Authorization": f"Bearer {DEFAULT_LOCAL_AUTH_TOKEN}"}
    try:
        with client:
            assert (
                client.get("/api/v1/system/bootstrap?include_devices=false").json()[
                    "default_auto_login_allowed"
                ]
                is True
            )
            created = client.post(
                "/api/v1/auth/users",
                headers=admin,
                json={
                    "username": "file-reader",
                    "password": "Reader12345",
                    "scopes": ["projects:files:read"],
                    "allowed_pages": [],
                    "project_ids": ["default"],
                },
            )
            assert created.status_code == 201, created.text
            data = created.json()
            user_id = data["user"]["user_id"]
            reader = {"Authorization": f"Bearer {data['initial_user_token']['token']}"}
            assert (
                client.get("/api/v1/system/bootstrap?include_devices=false").json()[
                    "default_auto_login_allowed"
                ]
                is False
            )
            assert client.get("/api/v1/system/me", headers=admin).json()["scopes"] == [
                "*"
            ]
            storage = client.app.state.dataset_storage
            object_key = "projects/default/results/access-test.txt"
            storage.write_bytes(object_key, b"real-file-content")
            content = client.get("/api/v1/projects/default/files/content", headers=reader, params={"object_key": object_key})
            assert content.status_code == 200, content.text
            assert content.content == b"real-file-content"
            # 已知目录中的缺失文件应到达资源层；不能因没有 models:read 而拒绝授权。
            response = client.get(
                "/api/v1/projects/default/files/content",
                headers=reader,
                params={"object_key": "projects/default/results/missing.png"},
            )
            assert response.status_code == 404, response.text
            assert client.get(
                "/api/v1/projects/default/files/content",
                headers=reader,
                params={"object_key": "config/secrets.json"},
            ).status_code in (400, 404)
            assert client.get(
                "/api/v1/projects/other/files/content",
                headers=reader,
                params={"object_key": "projects/other/results/missing.png"},
            ).status_code in (403, 404)
            assert (
                client.patch(
                    f"/api/v1/auth/users/{user_id}",
                    headers=admin,
                    json={"is_active": False},
                ).status_code
                == 200
            )
            assert (
                client.get("/api/v1/system/bootstrap?include_devices=false").json()[
                    "default_auto_login_allowed"
                ]
                is False
            )
            assert (
                client.delete(
                    f"/api/v1/auth/users/{user_id}", headers=admin
                ).status_code
                == 204
            )
            assert (
                client.get("/api/v1/system/bootstrap?include_devices=false").json()[
                    "default_auto_login_allowed"
                ]
                is True
            )
    finally:
        factory.engine.dispose()
