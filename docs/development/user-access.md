# 用户页面与操作权限设计

状态：开发实现完成，已进行自动化与真实模型验收。实施顺序及验收范围见[实现与验收](user-access-implementation.md)，界面见[页面设计](../design/frontend/user-permissions.md)。

## 1. 目标和使用方式

管理员创建或编辑账号时，分别勾选页面权限、操作权限及既有项目范围。用户登录后，在现有“设置 → 启动页面”中自行选择启动时显示的项目和 Workflow Runtime 应用模式。

不提供现场操作员、只读用户、管理员等权限预设，不保存角色，不创建专用应用选择页，不按应用数量自动跳转。应用模式是现有工作流的一种页面，不是另一套账号体系。

典型配置只是说明，不是系统预设：管理员勾选“启动页面”“Workflow 应用模式”，允许“查看工作流”“执行工作流”，需要显示或选择项目图片/文件时再勾选“查看项目文件”，选择可访问项目。用户可以设置自己的启动目标、提供输入、发起检测和查看结果，不能保存工作流、修改节点、发布、删除或管理 Runtime/Trigger。个人启动偏好不属于平台配置修改，无须管理工作流权限。

## 2. 已核对的代码基础

| 环节 | 当前实现 | 边界 |
| --- | --- | --- |
| 后端鉴权 | Session/Token 解析用户，scope 支持精确、*、prefix:* | 复用原鉴权与项目边界 |
| 导航和路由 | allowed_pages 与最低读取能力共同控制 | 导航、路由与页内入口共用页面策略 |
| 设置 | 按设置子页授权 | 个人启动页不要求账号读取权限 |
| 启动页面 | 过滤有权项目和 Runtime，本地偏好按账号保存 | 不修改服务端配置 |
| 应用模式 | 查看要求 read，运行另查执行能力 | 无管理权限时隐藏管理入口 |
| Runtime 调用 | 原 write 或 read+invoke | 同步、异步及 multipart 共用授权 |
| 账号界面 | 创建、编辑共用页面/操作勾选与项目选择 | 不提供角色预设 |

代码依据：[鉴权](../../backend/service/api/deps/auth.py)、[导航](../../frontend/web-ui/src/config/navigation.config.ts)、[Workflow 路由](../../frontend/web-ui/src/workflows/workflow-editor/routes.ts)、[设置路由](../../frontend/web-ui/src/modules/settings/routes.ts)、[启动设置](../../frontend/web-ui/src/modules/settings/components/SettingsStartupPagePanel.vue)、[启动解析](../../frontend/web-ui/src/app/startup/startup-route.ts)、[Runtime 调用](../../backend/service/api/rest/v1/routes/workflow_runtime/runs.py)。

## 3. 通用权限规则

| 维度 | 含义 | 检查位置 |
| --- | --- | --- |
| 页面 | 哪些导航、页面、设置子页可进入 | 前端导航、路由、页内入口 |
| 操作 | 哪些业务可查看、执行、管理 | 后端请求入口强制验证，前端同步控制按钮 |
| 项目 | 哪些项目资源可用 | 既有后端 Project 校验 |

页面隐藏不撤销 API 能力。授予查看工作流意味着允许其对应读取接口，不承诺图、节点参数等已授权读取内容保密。本阶段防止未授权修改和删除，不为隐藏页面另建数据隔离系统。已发布检测仍可产生结果文件和节点原有业务副作用，不表示系统完全不写入。

保留 scopes、project_ids，仅增加 `allowed_pages: list[str] | null`。旧用户 null 按原 scopes 推导；[] 无业务页面；非空只允许登记页面。PATCH 省略不修改、null 恢复兼容、[] 清空。项目空列表保持全部项目含义，界面必须明确选择“全部项目”才能提交。

新增通用 `workflows:invoke`，与 workflows:read 配合，允许向已发布、可调用的 Runtime 提交公开输入。原 workflows:write 与 * 保持原执行和管理能力。invoke 不允许任意草稿预览、节点配置覆盖、保存、发布、启停、选版或删除；草稿预览继续原管理授权。

其他模块按真实 read/write 显示“查看/管理”，不虚构独立保存/删除权限。无效 deployments/integrations scope 不作新选项，旧值保留但不自动映射更大权限。目录在现有代码模块中保持类型明确，不新增权限目录 HTTP 服务。

## 4. 复用现有业务与页面

继续使用原 Runtime 列表、preview-snapshot、App Mode 输入/显示、invoke/runs、结果流和文件接口。不新增 /workflows/operate、App Mode 专用 DTO/WS 协议、资源授权描述表或第二套 controller。

现有启动页只列出有权读取和进入的目标。无启动选择时优先进入有权的启动设置页，用户自行选择，不自动选唯一应用。目标不存在/失权时回退有权页面，不能固定回退无权 /projects；短暂故障保留选择。个人偏好继续 localStorage JSON，按账号隔离，不增加服务端默认 Runtime 字段。

应用模式隐藏无权管理跳转和修改入口，运行按执行权限控制，查看按读取权限控制。输入是本次检测数据，不写回节点参数。

源码已确认项目文件接口具备 Project 校验和公开命名空间限制。增加通用 `projects:files:read`（查看项目文件），文件列表、元数据、内容接口接受该 scope 或原 workflows:read 与 models:read 组合；复用原路径和存储检查，不扩大公开命名空间。该权限允许读取授权项目的公开输入、结果、数据集版本与导出文件，不是某一次检测的私有结果权限，不允许写入或删除。管理员明确勾选，图片显示缺少该权限时就地提示，不暗中增加 models:read，不增加新接口、复制文件或资源 Token。

## 5. 默认登录与核心稳定性

amvar 默认全权限永久 Token 的值、权限、有效期与初始化实现保持原样，第三方和 .NET SDK 继续使用。只有 amvar 时沿用原自动登录配置，存在其他用户时不自动登录 amvar；正常手动会话继续恢复，创建用户不强制退出当前管理员。

权限集中在页面和请求入口，复用已有 principal，不进入节点、逐帧推理、LocalBuffer、共享内存 Trigger/推理或训练遥测。注销、撤权、显示失败不停止已接受任务、Runtime、部署、Trigger 或 worker。原协议和管理调用不增加复制、权限锁、轮询或逐帧审计。

不新增固定权限轮询。HTTP 继续检查最新权限，页面在登录、导航、前台恢复、权限保存和明确鉴权失败时刷新身份。原长连接机制保持兼容；本阶段不承诺所有既有只读连接即时撤权，重连按最新权限检查，新管理/执行请求按最新权限验证。主动切断旧连接如有需要另行评估，不能侵入核心链路。

## 6. 验收边界

页面、操作、项目范围分别准确；用户自行保存启动应用；无 write 的账号可执行真实检测，管理修改和删除由后端拒绝。原管理员、默认 Token、第三方和 .NET SDK 全链路保持正常。进行同负载性能对比及至少 24 小时隔离长稳；可重复性能退化、误取消、重复执行或资源泄漏必须修正。

开发环境已完成账号、页面、请求边界和真实 OpenVINO CPU 模型检测验证，初次证据见[开发验收记录](user-access-implementation.md#10-开发验收记录2026-09-09)。40 次身份交替调用不作为修改前后基线；独立的性能对比、30 分钟长稳、CPU/NVIDIA 发行和 .NET SDK 结果见[专项验收记录](user-access-acceptance.md)。本次数据库范围为 SQLite，不要求 MySQL/PostgreSQL 迁移实测；24 小时验证保留为后续长周期项目。
