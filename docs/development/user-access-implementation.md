# 用户权限详细实施步骤

状态：阶段 1～6 已实现并通过开发测试；阶段 7 的追加验收按 30 分钟长稳、SQLite、CPU/NVIDIA 发行、正式 .NET SDK 与模型全链路执行。目标见[通用权限设计](user-access.md)，界面见[页面规格](../design/frontend/user-permissions.md)。初次开发记录见第 10 节，追加结果及未完成边界见[专项验收记录](user-access-acceptance.md)。

## 1. 数据和页面契约

新增 allowed_pages，贯通 ORM、Pydantic、应用请求、AuthenticatedPrincipal、登录/refresh/me/bootstrap 与 TS 类型。PATCH 用 model_fields_set 区分省略、null、[]，显式传递是否更新，不改变其他字段原语义。

Alembic 从实际 head 接续，旧用户赋 null；不能静默 downgrade 丢失已配置页面限制。使用通用 JSON/ORM；本次只验证 SQLite 新建和升级，不执行 MySQL/PostgreSQL 迁移验收。TS 类型按仓库当前维护方式更新，不假设已有 OpenAPI 生成命令。

| 页面 ID | 页面 | 最低操作能力 |
| --- | --- | --- |
| projects | 项目 | workflows:read 与 models:read |
| tasks | 任务 | tasks:read |
| datasets | 数据集 | datasets:read |
| models / deployments / inference | 模型、部署、推理 | models:read，操作另查原权限 |
| workflow-graph | 图编辑 | 读取 read，新建/保存 write |
| workflow-apps | 应用管理 | workflows:read |
| workflow-monitor | Runtime 监视 | workflows:read |
| workflow-app-mode | 应用模式 | workflows:read；检测需 invoke 或原 write |
| integrations / custom-nodes | 集成、节点 | workflows:read |
| settings-preferences | 偏好 | 已登录 |
| settings-startup | 启动页面 | 已登录，候选另查页面/读取/项目权限 |
| settings-services | 运行状态 | 现有 diagnostics 的 auth:read |
| settings-system | 系统环境 | diagnostics 为 auth:read，config/database 为 system:read |
| settings-session | 当前会话 | 当前身份，不包括账号审计 |
| settings-accounts | 用户管理 | auth:read，修改另查 auth:write |

同行的多个 ID 分别存储、勾选。设置父入口由有权子页派生，category/section 变化同样检查，不能只守卫 /settings 一次。登录、退出、无权/不存在页面不要求业务页面许可。类型化目录与前端标签分开维护，用测试校验所有路由和真实 scope，不新增目录服务。

无角色或权限预设。新增通用 workflows:invoke 与 projects:files:read；前者与 workflows:read 配合，后者独立控制授权项目公开文件读取；原 write 与 * 保持原语义。无页面但有 API 能力的账号合法，不能强制补页面。项目“指定/全部”显式选择，指定但为空禁止提交。

创建/编辑共用表单，auth:write 保持可信全局账号管理能力。沿用当前账号删除保护，并在数据库事务中保护最后有效管理员，不能只按用户名或单进程锁判断。权限编辑只提交权限和项目，不重置密码/状态/Token；并发覆盖用原子版本比较和更新，冲突保留表单并提示重新载入。

## 2. 既有模块落点

| 模块 | 工作 |
| --- | --- |
| LocalAuthService / ORM / auth schemas | 页面字段、合法性、权限保存和账号保护 |
| auth dependencies | 复用原匹配，补通用 Runtime 执行授权 |
| navigation / guards / SettingsDiagnosticsPage | 页面策略、设置子页过滤、按需读取 |
| SettingsAccountsPanel | 创建与编辑共用勾选表单、项目选择和摘要 |
| SettingsStartupPagePanel / startup-route / preferences store | 原选择/保存、目标过滤、账号隔离和回退 |
| 原 AppModePage / InputPanel | 查看与运行分离、管理跳转按权限显示 |
| 原 Runtime REST / 结果与文件接口 | 最小授权调整，原执行和显示合同复用 |
| session.store / 匿名 bootstrap | 其他用户存在时禁止默认自动登录 |

不创建专用应用页、角色服务、App Mode 执行器/显示协议/资源授权表；不重写全部对话框、Preview controller 或高性能通信。

## 3. 读取与执行

读取沿用 workflows:read 和 Project 边界，页面隐藏不限制已授予的 API 读取。启动目标验证复用原列表与 snapshot，不逐次推理加载图或 Catalog。

invoke、invoke/upload、runs、runs/upload 授权为原 write 或 read+invoke。invoke 仅接受已发布 Runtime 公开输入，拒绝 template/节点配置覆盖，不自动 start 或选版。无权和非法输入在持久化上传、建任务和执行前拒绝。保留 JSON/multipart、同步/异步、回执、记录策略和错误合同，选项按原公开 Runtime 合同校验，不另造页面专用响应。

草稿预览、保存、发布、删除、Runtime 生命周期、Trigger 配置继续要求管理权限。新增执行能力不改变服务、节点或任务内部工作方式。

项目文件列表、metadata、content 接口统一接受 projects:files:read，或原 workflows:read 与 models:read 组合。继续使用 projects/files.py 的 Project 可见性、object_key/storage_uri 冲突检查、公开命名空间与 ObjectStore 解析。范围是 projects/{project}/inputs、results、datasets/*/versions、datasets/*/exports，不能扩到全磁盘或运行时临时目录。FileResponse、媒体类型和下载行为保持原样，不新增文件路由、资源 Token、拷贝或编码。该权限明确包括上述全部公开文件，不承诺仅某个 Runtime 的结果可读；不授予写入/删除。缺权限时图片区域和文件选择器提示缺少查看项目文件权限，JSON/内联图及其他已授权操作仍可使用。

## 4. 启动和默认登录

用户在原启动页选择项目/应用/Runtime。落点顺序：安全且有权的显式 redirect → 本账号有效启动选择 → 有权的启动设置页 → 第一个有权页面 → 无可用页面。拒绝外部 URL、协议相对 URL、登录循环，不自动选择唯一应用。

localStorage JSON 按 principal_id 隔离，旧全局偏好仅在目标有权时迁移。恢复默认指有权落点，不固定 /projects；目标删除/失权提示重新选，短暂故障保留选择。保存个人偏好不需要 workflows:write，不改服务端 Runtime。

匿名 bootstrap 增加默认自动登录许可布尔值：有 amvar 外用户记录时关闭，禁用其他账号不重新开启，其他账号全删除后按原配置决定。初始化、默认快捷入口、缓存默认 Token 共用判断，查询失败不猜测允许；不公开用户列表。正常手动 Session/refresh 不变。

amvar 默认全权限永久 Token 的值、权限、有效期、初始化保持原样；第三方/.NET SDK 原调用不变。创建用户不强制注销管理员，不撤销或轮换 Token。

## 5. 性能和长期稳定性

请求入口复用已有 principal/资源，不重复查询。节点、推理、LocalBuffer、共享内存、Trigger、训练遥测不新增权限查询、序列化或锁；原管理员和 SDK 不经过页面策略，不改协议、队列、超时、模型生命周期和记录策略。

不新增固定权限轮询、逐帧审计或显示文件复制。保留现有 WS 背压与鉴权；重连检查新权限，本阶段不承诺全部旧只读连接即时撤权。登录、导航、前台恢复、权限保存和鉴权失败触发身份刷新，合并同时发生的请求。

确认失权后禁止新操作；临时网络/刷新失败不清空结果，不取消任务。显示 WS 不作为检测执行的新增前提。注销、断线、权限变更不停止已接受任务、部署、Runtime、Trigger、worker 或其他集成调用。

## 6. 实施顺序

每阶段按实现、代码核对、专项测试完成后继续。阶段 1～6 的实现已经落地，下面的验收项同时作为后续回归清单；未运行项目不得据此认定通过。

| 阶段 | 实现 | 验收 |
| --- | --- | --- |
| 1 | 页面目录、真实 scope、通用 invoke、原功能/性能基线 | 无预设/虚假权限，读取/执行/管理边界准确 |
| 2 | 页面模型贯通、迁移、PATCH、账号保护 | 旧 null 兼容、三态/并发/末位管理员正确 |
| 3 | 通用 Runtime 执行和必要读取权限 | 无 write 能检测；管理拒绝；原 SDK 不变；非法请求无执行副作用 |
| 4 | 账号表单、导航、路由、设置子页、按钮 | 创建/编辑准确，直达与导航一致，无权限闪现 |
| 5 | 原启动页和 App Mode | 自选启动目标、账号隔离、正确回退，原输入/显示可用 |
| 6 | 默认登录条件 | 有其他用户不自动登录，默认永久 Token 仍全权限可用 |
| 7 | 真实全链路、CPU/NVIDIA 发行、性能与长稳 | 本轮执行 30 分钟长稳，逐项记录功能及性能门禁，正式文档同步；24 小时为后续项目 |

新测试统一根目录 tests、test_ 前缀，例如 `tests/test_user_page_access.py`、`tests/test_workflow_invoke_access.py`、`tests/frontend/auth/test_user_permissions.ts`、`tests/frontend/auth/test_startup_access.ts`。已有测试就地补充。新浏览器用例配置隔离测试项目，不能切换真实管理员会话冒充验收账号。

## 7. 完整验证

1. 隔离两个项目和账号，由管理员手动配置。覆盖默认管理员、read+invoke 无 write、仅 read、无页面、无 scope、跨项目、禁用账号，以及 Session/refresh/长期 Token。
2. 用户进入原启动页、自选保存、重新登录/刷新、切换账号、恢复默认；验证目标删除/无权/停止/暂时失败。
3. 复制真实模型和 Workflow 到隔离环境，部署、发布、创建 Runtime/Trigger，验证文本、JSON、图片、文件、多文件、同步/异步和原显示，不修改原开发资源。
4. 直接调用保存、发布、删除、Runtime 启停/选版、Trigger、模型和账号管理 API；验证拒绝及数据库、文件、执行计数无对应变化，不只验证隐藏按钮。
5. 原管理员完成数据集导入/导出、训练、转换、部署、推理、Workflow/Runtime/Trigger、.NET SDK；测试只有 amvar、新用户、禁用/删除、默认 Token 缓存、初始化失败。
6. 同机器、模型、输入、并发、预热对比吞吐、p50/p95/p99、CPU、内存、句柄、共享内存、数据库等待，覆盖无页面、管理员、普通用户、多订阅负载；超出基线波动的可重复退化必须修正。
7. 复用 tests/integration 中适用的遥测/推理/Trigger 基准和 deployment_workflow_trigger_soak.py，先核对实际参数。本轮按确认范围执行 30 分钟真实模型长稳；至少 24 小时及权限编辑、慢客户端、断线和查询故障组合留作后续专项，不以半小时正常调用替代。
8. 开发通过后标准 assemble-release 生成 CPU/NVIDIA 发行并隔离验证，记录实际推理后端，未 GPU 执行不声称 GPU 验收。只清理本轮创建且无进程使用的资源，不停止手动开发服务。

功能、性能、长稳分别记录结果；未完成项明确待验收，不以旧测试或设计文档替代运行证据。

## 8. 每阶段的详细工作清单

### 8.1 阶段 1：固定清单和修改前基线

1. 记录实际 Git 状态、数据库迁移 head、当前 API 和前端构建配置；保留用户已有修改，不提交运行数据。
2. 枚举当前所有路由、别名、设置 category/section 与 require_scopes 调用，形成页面/操作对应测试数据；未登记受保护路由在检查中报错，不能靠遗漏获得页面访问。
3. 固定两个通用新增 scope、页面 ID、PATCH 三态、项目空列表含义、默认自动登录条件。精确匹配、* 和 prefix:* 算法复用，不复制一套规则。
4. 在隔离环境记录已有功能、请求次数、端到端延迟和共享内存基线。UI 未打开时不得新增后台任务作为后续对比基准。

完成条件：契约测试清单能区分页面、读、执行、管理和项目；每项权限对应实际入口，没有预设或新角色模型。

### 8.2 阶段 2：数据模型与会话贯通

按顺序修改 `backend/service/infrastructure/persistence/local_auth_orm.py`、账号应用请求/返回模型、Alembic revision、REST schemas/responses/users、`api/deps/auth.py`、system schemas/responses、TS 合同和 Session normalize 路径。

- 新数据库与旧数据库升级分别验证。旧账号 allowed_pages=null，静态 principal 的新增字段有兼容默认值；新建 UI 显式提交数组。
- 用户 DTO 使用明确类型，JSON 列交给 ORM 序列化，不用字符串拼接。数据库/系统不认识的页面 ID 在新请求中报错，旧未知 scopes 不暗中转换成授权。
- scopes/project_ids 的既有 PATCH 含义保持；allowed_pages 省略/null/[] 各用一次真实请求验证持久化结果。
- 新前端权限编辑提交打开时的版本标识。采用可选 If-Match，冲突 412，旧客户端不强制提交；服务端原子比较并更新，不能先读比较再无条件覆盖。
- 账号管理保护应在应用事务内执行，涉及权限、禁用和删除，现有默认 amvar/当前账号保护不移除。并发用例证明不能同时失去全部有效管理账号，不把保护锁放入推理/读取路径。

完成条件：登录、refresh、system/me、bootstrap、长期 Token 均携带一致页面信息；迁移可验证，账号修改不会改动默认 Token 或运行服务。

### 8.3 阶段 3：两个通用操作能力

先抽取复用的权限判定，再调整下表接口；不整体替换 workflows:write。同步响应模式校验当前在执行后的 formatter 中，须移到调用前，避免非法模式已经执行了工作流。

| 原接口 | 实施后的授权 | 保持的行为 |
| --- | --- | --- |
| POST /api/v1/workflows/app-runtimes/{id}/invoke | write 或 read+invoke，再查 Project | 原同步调用和 app-result/run/debug 合同 |
| POST 同路径 /invoke/upload | 同上，上传落盘前检查 | 原 multipart、限额和清理 |
| POST 同路径 /runs、/runs/upload | 同上 | 原异步任务/记录策略，不强制开启历史记录 |
| GET /api/v1/workflows/runs/{id} 及 events | 原 read 和资源归属 | 原读取合同 |
| Runtime start/stop/restart/select-version/delete、run cancel | 原 write | 不授予 invoke |
| App 保存/发布/删除、草稿 preview、Trigger 配置 | 原 write | 不授予 invoke |
| GET /api/v1/projects/{id}/files、/files/metadata、/files/content | files:read 或原 workflows:read+models:read | 原 Project/公开路径范围、FileResponse 与分页 |
| Runtime list、preview-snapshot、preview WS | 原 read+Project | 原快照与显示协议，不增加周期鉴权 |

表中 read/write/invoke 分别指 workflows:read/write/invoke，files:read 指 projects:files:read。管理分支原客户端选项保持兼容；新增 invoke 仅提交公开输入与原合法执行选项，不能传 template/配置覆盖。用户仍可读取其已获得 read 的调试合同，不以隐藏图编辑页承诺调试数据保密。

上传请求先鉴权和资源检查，再解析/验证契约、大小与数量，最后进入原服务。检查 JSON 顶层输入/包装输入的原互斥语义；无权、非法响应模式、非法输入不得创建业务任务或执行。解析所需临时文件按原生命周期清理，不为了检测增加持久记录。

图片接口的读取范围已由 `projects/files.py` 和 `object_store/object_key_layout.py` 定义，不需要另做结果归属数据库。用真实图片、Mask、overlay、file_id 和 storage_uri 验证原调用；跨项目、非公开目录、越界、冲突参数和链接逃逸继续拒绝。文件列表现有目录扫描不放入每帧显示流程，内容请求不先全盘列文件。

完成条件：无 workflows:write、无 models:read 的账号，明确授予 read+invoke+files:read 后能输入、运行、看图；移除 invoke 只禁止新检测，移除 files:read 只禁止对应文件访问，管理操作始终拒绝。

### 8.4 阶段 4：账号表单、导航和设置子页

1. 在 `platform/auth` 的现有权限模块集中页面判断，导航、Router guard、页内按钮引用同一函数。页面与业务 scope 均通过才可进入，alias 与 redirect 校验最终目标。
2. `/settings` 从整页 auth:read 改为登录后按实际 category/section 检查。`SettingsDiagnosticsPage` 只请求当前有权区块，启动页不触发 diagnostics、用户或 Token 加载。
3. `SettingsAccountsPanel` 提取共用权限表单：页面/操作分组复选框、项目搜索选择。用户详情增加编辑入口；创建时无业务默认勾选，无预设。页面要求的最低 read 显式提示，不自动授予 write。
4. 在按钮与事件处理两处控制权限；隐藏按钮不能留下快捷键、提交事件或页内链接绕过。查看型账号进入已有图页时，即便允许临时查看，也不得提交保存、发布或编辑配置。
5. 权限编辑成功使用服务端返回值刷新摘要；当前用户失去当前页时先报告保存成功，再进入有权落点。取消不保存，异常保留表单，提交中防重复操作。

完成条件：设置查询参数手输、前进后退、旧书签与导航行为一致；无全菜单闪现；匿名、零页面、API-only、原 null 管理账号均有稳定落点。

### 8.5 阶段 5：用户自行配置启动与原 App Mode

`SettingsStartupPagePanel` 已有分页加载、请求 generation 和选中 Runtime 的 snapshot 校验，保留这些机制。没有必要为每个候选下载完整快照；选择/保存时验证目标 Project/App/Runtime 身份与 app_mode。

- 前端候选来源使用 bootstrap 已过滤的 visible_projects，避免为选择项目附加 models:read。没有 App Mode 页面权限时不显示该启动类型。
- 当前默认模式是 projects；新计划把“未选择目标/默认落点”与“显式选择项目首页”区分，增加偏好 v2 的 default 模式，并保留 v1 读取迁移。恢复默认删除当前账号偏好，路由再按权限求落点，不给无权用户注入 projects。
- localStorage key 按 principal_id 隔离；先清理上一账号内存状态再读当前账号偏好。v1 全局偏好只有经过当前账号授权验证才迁移，原值不当作所有账号默认目标。
- `startup-route.ts`、登录页和 router guards 中 /projects 硬编码回退统一调用落点解析；不反复重定向到 login，不自动选唯一 Runtime。读取失败保留选择，不把网络错误误判目标已删除。
- `WorkflowRuntimeAppModePage` 继续 useRuntimePreview。工具栏“运行时监视”“应用详情”各查页面与 read；InputPanel 增加明确 canInvoke 控制运行按钮及提交事件，原 observed_state/active 限制继续保留。
- 当前真实页面是无公开输入的运行区加四个图片显示区域；该布局不改。没有输入也能发起已授权检测；只读时运行入口不可用，结果、放大和有权设置入口保留。
- 文件权限不足在相关显示区域提示，不能把已成功检测误报为工作流执行失败；HTTP 结果与图片下载错误分别显示。图像读取不新增 WS 成功前置条件。

完成条件：用户自行保存并在重新登录后打开正确应用；账号切换、恢复默认、无权/停止/删除目标、快速切项目、迟到响应和网络故障不串目标、不误保存、不修改 Runtime。

### 8.6 阶段 6：默认自动登录条件

`system/bootstrap.py` 已支持匿名读取和 include_devices=false，直接补布尔字段 `default_auto_login_allowed`。后端通过 LocalAuthService/Repository 的 exists 查询判断其他本地账号，使用默认账号种子身份标记识别默认账号，不在请求中列出全部用户；不额外做硬件探测。

`session.store.initializeSession` 已先读匿名 bootstrap，再恢复 Session，最后选择缓存/default Token。保持手动 Session 恢复顺序，只让默认 Token 的自动使用受布尔值控制。defaultAutoLoginAvailable、默认快捷入口、缓存同一 Token 同样受控，不影响用户显式输入的其他凭据。

老后端缺少新许可字段时不猜测允许默认自动登录，显示正常登录入口；已有合法手动会话仍恢复。开发/发行配套升级后验证原只有 amvar 的便捷行为。查询结果不放入每次推理，不更改 Token、密码、scope、过期时间或 seeder。

完成条件：有新账号不自动进入 amvar，禁用该账号不重新开启，删除所有其他账号后遵循原配置；默认永久 Token 的 REST/.NET SDK 调用前后保持一致。

### 8.7 阶段 7：真实验收、构建与交付

先准备明确的隔离数据根、端口、测试账号和 Workflow 副本，再执行第 7 节完整矩阵。记录实际配置、命令、模型和推理后端、开始/结束时间、功能/性能/长稳结果；不修改当前用户的真实流程或启动偏好。

源目录修正后按标准 assemble-release 生成 CPU/NVIDIA 包，不手工改 release/app。测试服务退出并确认子进程结束后清理准确的本次数据；不得删除用户数据或仍在使用的临时目录。

完成后更新 local-auth API、项目文件 API、Runtime 调用 API、前端权限与启动文档，明确新增字段、scope、旧客户端兼容和权限生效时机。实施计划仅在实际验收后标记完成。

## 9. 测试命令与判定记录

以下命令可在仓库根目录复查本次实现。新增测试已放入统一 tests 目录。

```powershell
conda activate amvision
python -m pytest tests/test_local_auth_api.py tests/test_project_access_boundaries.py tests/test_workflow_runtime_invoke_api.py tests/test_workflow_runtime_preview_api.py
python -m pytest tests/test_user_page_access.py tests/test_workflow_invoke_access.py tests/test_project_file_read_access.py tests/test_user_access_migration.py
node frontend/web-ui/node_modules/vitest/vitest.mjs run --config frontend/web-ui/vite.config.ts
npm --prefix frontend/web-ui run build
git diff --check
```

现有 Vitest 已包含 tests/frontend/**/test_*.ts，不必改其测试目录。新增 Playwright 用例放 tests/frontend/e2e 并使用独立命名项目；不能让带 @playwright/test 的用例被 Vitest 的宽匹配误收集，需显式排除 e2e 目录。保留已有 e2e 套件；浏览器验收不向当前真实 Runtime 点击运行。

新增行为测试至少覆盖：

| 分类 | 必测差异 |
| --- | --- |
| 账号数据 | 省略/null/[]、未知页面、未知旧 scope、Session/refresh/Token、并发编辑 |
| 页面 | 允许页面无最低 read、允许 API 无页面、设置子区块、别名/redirect、当前页撤权 |
| 调用 | read-only 拒绝、read+invoke 允许、* 兼容、公开输入/非法选项、JSON/multipart/sync/async |
| 文件 | 独立 files:read、原双 read 兼容、无 files:read、跨项目/非公开目录/越界、已删除文件 |
| 启动 | v1→v2、账号隔离、default 与 projects 区分、快速选择迟到响应、无权和临时故障 |
| 默认登录 | 只有 amvar、有其他账号、禁用/删除、缓存默认 Token、许可读取失败、手动会话恢复 |
| 稳定性 | 退出/撤权/断线不停止任务、无重复执行、无新增逐帧权限开销、长稳资源有界 |

每阶段记录“通过/失败/未执行”及证据。浏览器实测使用开发测试账号和 Workflow 副本，未修改原业务应用、模型或默认管理员 Token。

## 10. 开发验收记录（2026-09-09）

### 实现与迁移

- Alembic `f2b7d9a4c6e8` 接续 `e7a9b1c3d5f8`，增加 nullable JSON 页面字段。开发 SQLite 已执行 upgrade head。旧 null 保留兼容语义；任何显式配置（包括 []）存在时拒绝有损 downgrade。
- 账号创建、编辑、登录、刷新、当前身份及 bootstrap 贯通字段。编辑以可选 If-Match/updated_at 防覆盖，最后有效账号管理员由数据库事务保护；未引入逐帧权限锁。
- 当前账号与默认种子账号不能删除。最后有效管理员不能被禁用、删除或撤去有效管理能力。默认 amvar 永久 Token 的种子、权限、有效期没有改动。
- 页面目录共 18 项，操作表按真实 scope 显示，新增 workflows:invoke、projects:files:read。页面、执行、项目范围分别检查，不创建角色预设。
- 身份在导航、前台恢复和明确执行 403 后刷新；合并同时请求，忽略切换账号后的旧响应。瞬时断网保留身份与结果，不操纵后台服务。

### 自动化

修改前 4 个既有后端套件共 31 项通过；最终 8 个既有及新增后端套件共 37 项通过。新增用例覆盖页面三态、默认登录条件、并发编辑与最后管理员、SQLite 迁移回退、项目文件及 JSON/multipart 同步/异步调用。前端完整套件 126 个文件、505 项通过，覆盖默认 Token 登录条件、权限组合、启动偏好隔离和失效回退、刷新故障及账号切换迟到响应。vue-tsc 与 Vite 完整构建、变更 Python 文件 Ruff 检查均通过。

### 真实数据与页面

- 通过用户管理页面创建“权限验收”开发账号，只授予应用模式、启动页面，以及 workflows:read、workflows:invoke、projects:files:read，限定 project-1；未签发额外长期 Token。
- 复制现有 3570 治具工作流到 `workflow-app-access-test-0909`，Runtime 为 `workflow-runtime-8829e24ac32e42ba8ae916177b1bf8dc`。仅副本适配已有透视校正图片，保留 24 个 ROI 的两路分类、汇总和标注。原节点配置、原应用和模型未修改。
- 复用真实 `yolo11-s-pcbtrayslotsmall3570-20260804085356` 模型、OpenVINO CPU 部署和现有治具照片。受限账号在启动页面自选该 Runtime，重新打开后进入应用模式，并通过页面运行得到 24 工位结果与标注图片（21 空、3 满，业务判定 NG，执行成功）。
- 上传实测发现副本直接向固定 ROI 网格传递 storage 引用时缺少图片尺寸；副本增加现有 Resize 节点，以原尺寸 2560×2358 输出执行期内存图片，再进行 ROI 分类和来源一致性检查。最终通过受限账号在亮/暗外观页面上传真实图片并得到完整结果，没有修改节点核心实现。
- 受限账号的 Runtime 停止/删除、App 保存/删除/发布和账号创建均返回 403。暂时撤去 invoke 后新检测返回 403，Runtime 仍运行；管理员调用产生的结果仍可供只读页面显示。
- 项目文件无 files:read 时 403，补回后实际下载 974446 字节；跨项目 403、非公开命名空间 400。该测试文件已清理，原照片保留。JSON 与内联图片不要求项目文件下载权限。
- 默认 amvar Token 的 me 与实际模型调用仍成功，scopes 为 *；有测试账号后匿名 bootstrap 的默认自动登录许可为 false，正常手动会话继续使用。
- 管理员页面实际编辑、保存、取消均已验证；清空页面后用户进入无权页面，仍可退出登录，未出现循环跳转。恢复两项页面授权后，用户重新在启动设置保存验收 Runtime。

### 性能观察与未执行项

在最终验收副本上，同一开发实现、同一真实模型与输入，交替执行管理员和受限用户各 20 次，共 40 次全部成功。管理员 p50 449.88 ms，受限账号 p50 453.38 ms。此前未加图片规范化节点的副本也完成 40 次成功调用；两轮流程不同，不据此比较性能变化。此结果仅用于发现身份路径明显异常，不是严格性能基准，也不证明修改前后无退化。节点、worker、IPC、共享内存与 Trigger 数据面未增加权限检查或协议变化。

以上为初次开发验收。当时未执行的修改前后性能、发行包及 .NET SDK 项目已进入[追加专项验收](user-access-acceptance.md)。本次长稳范围明确为 30 分钟；24 小时属于后续长周期验收，MySQL/PostgreSQL 不在本次范围。REST 实测不能替代 SDK 实测，半小时结果也不等于 24 小时结论。

### 验收资源

开发账号、验收应用副本与运行中的验收 Runtime 保留用于复查，不依赖 `.tmp` 中间文件。启动偏好按账号和浏览器站点保存，本轮使用 localhost:5601 隔离原 127.0.0.1:5601 会话。临时目录 `.tmp/user-access-*` 与副本调试时生成的 `data/files/memory` 图片清理命令被工具执行策略拒绝，尚未清理；这些文件不是交付资产，也不作为工作流运行输入。
