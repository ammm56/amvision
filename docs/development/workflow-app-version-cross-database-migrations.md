# Workflow App 版本迁移跨数据库门禁

## 目标

Workflow App 版本管理迁移以 SQLite 作为默认开发路径，同时需要保持
MySQL 8 和 PostgreSQL 的 DDL 兼容。门禁分为两层：

- 默认方言门禁不连接外部服务，编译 MySQL/PostgreSQL DDL，并在隔离
  SQLite 数据库验证实际 upgrade、失败恢复和 schema 检查。
- 可选集成门禁连接 CI 提供的专用空数据库，执行真实
  `e6 -> head -> e6 -> head` 往返。

方言编译不能替代真实数据库。它可以发现不受支持的 DDL、方言语法和
metadata 漂移，但不能覆盖服务器版本、驱动、事务行为、反射结果和锁行为。

## 默认门禁

默认测试不要求 Docker、MySQL/PostgreSQL 驱动或外部数据库：

```powershell
python -m pytest -q tests/test_workflow_app_version_migration_dialects.py
```

该门禁覆盖：

- f7/f9 的 nullable `worker_instance_id`；
- f8 的命名内容去重唯一约束及 nullable key；
- Runtime revision 的两条命名外键；
- fa lifecycle 复合主键、Boolean 默认值和普通索引；
- fa 在非事务 DDL 中断后补齐缺失索引，并拒绝同名错列索引；
- 当前 ORM metadata 与迁移 schema 的一致性。

## 可选真实数据库门禁

测试文件位于：

`tests/integration/test_workflow_app_version_migrations_cross_database.py`

该目录不在默认 pytest 递归范围。CI 需要显式安装相应驱动并提供专用空库：

```powershell
python -m pip install pymysql "psycopg[binary]"
$env:AMVISION_CROSS_DB_MIGRATION_ALLOW_DESTRUCTIVE = "1"
$env:AMVISION_TEST_MYSQL_DATABASE_URL = "mysql+pymysql://user:password@mysql:3306/amvision_migration_test_mysql"
$env:AMVISION_TEST_POSTGRESQL_DATABASE_URL = "postgresql+psycopg://user:password@postgres:5432/amvision_migration_test_postgresql"
python -m pytest -q tests/integration/test_workflow_app_version_migrations_cross_database.py
```

安全边界：

- 只有显式设置 `AMVISION_CROSS_DB_MIGRATION_ALLOW_DESTRUCTIVE=1` 才运行；
- 数据库名称必须以 `amvision_migration_test_` 开头；
- 数据库开始时必须为空；
- 测试会执行 downgrade，并在完成后回退到 `base`；
- 不得填写开发库、现场库或共享数据库 URL。

CI 可使用服务容器或已有的临时数据库服务。仓库默认依赖不包含 MySQL/
PostgreSQL 驱动，本地开发、SQLite 门禁和发行包不因该可选门禁强制依赖
Docker 或外部数据库。

真实数据库门禁验证以下行为：

- 迁移链保持单一 head；
- f7/f8/f9/fa 的真实 upgrade/downgrade 往返；
- Runtime revision 外键和 f8 命名唯一约束可由 Inspector 正确反射；
- 历史 Workflow Run 的 worker epoch 保持 `NULL`；
- 同一 Application 的多个 `NULL` dedup key 可共存，非空 key 仍唯一；
- fa lifecycle 表的复合主键和索引完整。
