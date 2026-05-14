# Workflow Authoring 后端开发单

## 文档目的

本文档用于收口 workflow 图编排前端所依赖的后端接口和数据补齐顺序。

本文档只关注 authoring 控制面，不展开前端实现、视觉设计或交互细节。

## 当前已具备的最小控制面

- template：validate、save、get、list、version browse、delete version；列表和版本摘要已带 created_at、updated_at、created_by、updated_by
- application：validate、save、get、list、delete；列表和详情已带 created_at、updated_at、created_by、updated_by，以及 template 一跳摘要
- node catalog：统一读取 core node、custom node、payload contract 和 node pack manifest，支持按 category、node_pack_id、payload_type_id、q 过滤，并返回 palette_groups
- preview run：create、get、list、delete；列表支持按 state、created_from、created_to 过滤
- execution policy：create、list、get
- app runtime：create、list、get、start、stop、restart、health、instances、sync invoke、async run create、get run、cancel run；响应已带 updated_by，以及 application/template 一跳摘要
- trigger source：create、list、get、enable、disable、delete、health；响应已带 updated_by，以及 runtime/application 一跳摘要

## 本轮已补齐的接口

- `GET /api/v1/workflows/node-catalog`
- `GET /api/v1/workflows/node-catalog?category=&node_pack_id=&payload_type_id=&q=`
- `GET /api/v1/workflows/projects/{project_id}/templates`
- `GET /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions`
- `DELETE /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions/{template_version}`
- `GET /api/v1/workflows/projects/{project_id}/applications`
- `DELETE /api/v1/workflows/projects/{project_id}/applications/{application_id}`
- `GET /api/v1/workflows/preview-runs?project_id=&state=&created_from=&created_to=`
- `DELETE /api/v1/workflows/preview-runs/{preview_run_id}`

## 当前已能支撑的前端第一阶段范围

- 从 node catalog 拉取节点目录、端口定义、payload contract、parameter_schema 和 palette_groups，并支持节点面板筛选与搜索
- 保存和读取图模板与流程应用
- 浏览同一模板的多版本
- 删除旧模板版本和无效流程应用
- 使用 preview run 做编辑态试跑、浏览最近试跑结果并清理临时记录
- 基于 app runtime 做已发布应用的启动、调用和运行结果回查

## 下一批执行项

### 1. 资源摘要字段补齐

- preview run 当前已有 retention_until；后续只保留运维清理和生命周期策略，不再扩公开字段面
- 如需继续扩资源摘要，应优先围绕运行结果或审计展示，不再新增通用排序或复杂搜索

### 2. preview run 生命周期规则补齐

- 已补 backend-maintenance cleanup-preview-runs，按 retention_until 清理过期记录和 snapshot 目录
- 如需继续补规则，只保留保留时长、定时执行方式和失败重试边界

### 3. node catalog 返回形状增强

- 评估是否需要把 capability_tags、runtime_requirements 和 parameter_schema 的常用摘要单独上提到列表层
- 评估是否需要补 palette group 排序权重、图标、推荐节点和最近使用节点入口

### 4. authoring 资源关联摘要补齐

- 当前阶段已完成 application -> template、runtime -> application/template、trigger source -> runtime/application 的一跳摘要
- 后续不继续向下递归透传更深层资源

### 5. 参数和 UI schema 边界补齐

- 明确 `parameter_schema` 中哪些字段由前端直接渲染
- 补充默认值、枚举标签、分组、隐藏字段、只读字段等 authoring UI 所需约束
- 明确节点结果面板和端口预览需要的元数据是否进入 node catalog

### 6. template/application 管理动作补齐

- 增加复制 template version 的控制面
- 增加复制 application 的控制面
- 评估是否需要增加“读取 template 最新版本”的便捷接口，而不是每次先 list versions 再 get

## 当前不进入的范围

- 浏览器前端画布实现
- application versioning 设计重构
- SDK 对 Save Template、Save Application、Create Runtime 的创建面封装
- 把 docs 中的示例 JSON 直接改造成长期 authoring 数据源