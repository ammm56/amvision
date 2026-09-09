"""通用页面权限、PATCH、默认登录与管理保护回归。"""

from tests.test_local_auth_api import _create_local_auth_test_client


def test_pages_patch_session_and_admin_protection(tmp_path):
    """实际 API 验证空/null/省略、Token 主体及末位管理员保护。"""
    client, factory = _create_local_auth_test_client(tmp_path, database_name="pages.db")
    try:
        with client:
            admin = client.post(
                "/api/v1/auth/bootstrap-admin",
                json={
                    "username": "admin",
                    "password": "Admin12345",
                },
            ).json()
            headers = {"Authorization": f"Bearer {admin['access_token']}"}
            body = {
                "username": "reader",
                "password": "Reader12345",
                "scopes": ["workflows:read", "workflows:invoke", "projects:files:read"],
                "allowed_pages": ["settings-startup", "workflow-app-mode"],
            }
            response = client.post("/api/v1/auth/users", headers=headers, json=body)
            assert response.status_code == 201, response.text
            user = response.json()["user"]
            token = response.json()["initial_user_token"]["token"]
            me = client.get(
                "/api/v1/system/me", headers={"Authorization": f"Bearer {token}"}
            ).json()
            assert me["allowed_pages"] == body["allowed_pages"]
            url = f"/api/v1/auth/users/{user['user_id']}"
            changed = client.patch(
                url, headers=headers, json={"display_name": "Reader"}
            )
            assert changed.json()["allowed_pages"] == body["allowed_pages"]
            assert (
                client.patch(url, headers=headers, json={"allowed_pages": []}).json()[
                    "allowed_pages"
                ]
                == []
            )
            assert (
                client.patch(url, headers=headers, json={"allowed_pages": None}).json()[
                    "allowed_pages"
                ]
                is None
            )
            assert (
                client.patch(
                    url, headers=headers, json={"allowed_pages": ["unknown"]}
                ).status_code
                == 400
            )
            assert (
                client.patch(
                    url,
                    headers={**headers, "If-Match": user["updated_at"]},
                    json={"allowed_pages": []},
                ).status_code
                == 412
            )
            admin_url = f"/api/v1/auth/users/{admin['user']['user_id']}"
            assert (
                client.patch(
                    admin_url, headers=headers, json={"is_active": False}
                ).status_code
                == 403
            )
            assert client.get("/api/v1/system/me", headers=headers).status_code == 200
            login = client.post(
                "/api/v1/auth/login",
                json={"username": "reader", "password": "Reader12345"},
            ).json()
            assert login["user"]["allowed_pages"] is None
            refreshed = client.post(
                "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
            ).json()
            assert refreshed["user"]["allowed_pages"] is None
    finally:
        factory.engine.dispose()
