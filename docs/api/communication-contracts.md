# 通信和事件规则

## 文档目的

本文档用于说明平台公开通信边界与内部通信边界，明确 REST API、WebSocket 和 ZeroMQ 各自适合做什么、不适合做什么。

本文档关注“如何划分通信职责”和“哪些数据可以通过哪条边界流动”，不展开具体资源字段或消息 schema 的逐项清单。

## 适用范围

- 浏览器前端与后端服务的通信边界
- 上位机、MES、采集系统和其他外部系统的接入方式
- REST API、WebSocket 和 ZeroMQ 的职责拆分
- 任务状态、日志、事件、结果引用和回调消息的接口边界
- 版本化、兼容性、鉴权和错误语义

## 总体原则

- 浏览器前端与外部系统原则上共用同一套公开通信规则
- REST API 和 WebSocket 构成对外公开边界，ZeroMQ 仅作为同机本地部署中的内部 IPC 补充
- backend-service 是公开状态与资源视图的唯一权威入口
- 任何对外可见状态都应可被 REST 查询或通过 WebSocket 订阅获得
- ZeroMQ 传输的消息不能替代公开接口的版本规则与审计要求

## 三类通信边界的职责拆分

### REST API

REST API 用来做请求响应、资源查询和管理动作。

#### 适合做的事

- 项目、数据集、模型、部署、流程模板、插件和集成端点的资源管理
- 创建训练、验证、转换、部署、推理和流程执行任务
- 查询任务详情、分页列表、最新状态和结果引用
- 执行取消、重试、启停、回滚、发布等管理动作
- 提交配置变更、插件启停、集成端点管理和权限相关操作

#### 不适合做的事

- 高频日志流
- 持续进度推送
- 长连接订阅
- 同机本地内部进程的低开销消息分发

### WebSocket

WebSocket 用来推送状态、订阅事件和做长连接实时反馈。

#### 适合做的事

- 任务状态变化通知
- 训练、推理、转换和流程执行的进度推送
- 日志片段、告警事件和健康状态通知
- 部署实例、集成端点和插件状态变化推送
- 前端工作台需要的实时看板和长时订阅会话

#### 不适合做的事

- 替代资源型 REST 查询
- 承担权威写入接口
- 作为内部 worker 调度主通道
- 代替外部系统需要的稳定请求响应协议

### ZeroMQ

ZeroMQ 用来做同机本地部署场景下的内部进程间消息通信。

#### 适合做的事

- backend-service 与本地 worker 之间的低开销消息交换
- 本地插件进程、桥接进程或边车进程之间的事件转发
- 不适合通过公开网络接口暴露的本地内部信号
- 对延迟敏感但无需直接对外公开的内部通信路径

#### 不适合做的事

- 浏览器前端直接通信
- 跨公网或跨组织边界的对外公开接口
- 资源查询和管理动作的主接口
- 替代 REST API 与 WebSocket 的版本化规则

## 通信职责矩阵

- REST API：资源读写、管理动作、同步请求响应
- WebSocket：状态订阅、日志流、实时事件推送
- ZeroMQ：同机本地内部进程通信与消息转发

## 事件格式

### 事件对象的最小结构

- event id
- event type
- event version
- occurred at
- source
- aggregate id
- task id or deployment id
- payload reference or payload summary

### 事件分类

- task events：任务接收、排队、运行、完成、失败、取消、超时
- deployment events：部署创建、启动、切换、回滚、下线
- plugin events：插件安装、启用、禁用、升级、回调触发
- integration events：外部触发接收、回调发送、结果上报、联动通知
- audit events：重要管理动作和异常行为记录

## REST 规则

- 所有公开资源与动作必须显式版本化
- 创建类接口应返回可跟踪的资源 id 或 task id
- 长任务接口优先返回 accepted 或 queued 语义，而不是同步阻塞到底
- 错误响应需要区分校验错误、权限错误、状态冲突、依赖缺失和系统异常
- 幂等性要求应明确标注在创建、回调和重试相关接口上

## WebSocket 规则

- 订阅主题必须与任务、部署、插件、项目或全局事件范围明确对应
- 推送消息必须携带事件类型、版本和发生时间
- WebSocket 推送只提供状态流视图，不替代 REST 的权威查询接口
- 断线重连需要有从最近状态快照恢复的策略，而不是假设消息永久可靠

## ZeroMQ 规则

- 仅用于同机本地部署中的内部信道
- 消息主题、端点和访问权限必须由 backend-service 或 runtime manifest 管理
- ZeroMQ 消息若影响公开状态，必须回写 backend-service 后再对外发布
- 任何 ZeroMQ 交互都不得绕开审计、超时和管理规则

## 鉴权与权限边界

- REST API 和 WebSocket 共享统一身份与权限模型
- 外部系统接入应有独立的 endpoint identity 或 access scope
- ZeroMQ 不作为对外暴露的安全边界，应依赖本地进程级部署隔离和最小访问面
- 插件触发与回调应声明可访问的事件范围、资源范围和外部端点范围

## 兼容性和版本管理

- 公开 API、事件类型和消息载荷一旦外发，即视为版本规则
- 新字段优先采用向后兼容方式追加
- 行为变更或字段语义变化必须通过版本升级显式表达
- ZeroMQ 内部消息即使不对外公开，也应通过 manifest 或内部 schema 维持稳定边界

## 推荐后续文档

- [docs/architecture/backend-service.md](../architecture/backend-service.md)
- [docs/architecture/system-overview.md](../architecture/system-overview.md)
- [docs/deployment/bundled-python-deployment.md](../deployment/bundled-python-deployment.md)