# 通信和事件规则

## 文档目的

本文档用于说明平台通信边界，明确 REST API、WebSocket、ZeroMQ 和本机高性能数据交换层各自适合做什么、不适合做什么。

本文档关注“如何划分通信职责”和“哪些数据可以通过哪条边界流动”，不展开具体资源字段或消息 schema 的逐项清单。

## 适用范围

- 浏览器前端与后端服务的通信边界
- 上位机、MES、采集系统和其他外部系统的接入方式
- REST API、WebSocket、ZeroMQ 和 LocalBufferBroker 的职责拆分
- 任务状态、日志、事件、结果引用和回调消息的接口边界
- 版本化、兼容性、鉴权和错误语义

## 总体原则

- 浏览器前端默认使用 REST API 和 WebSocket
- 外部系统可按部署场景使用 REST API、WebSocket、ZeroMQ、gRPC、MQTT、PLC、IO 或传感器触发入口
- ZeroMQ 可作为 workstation 或 standalone 场景下的高速外部触发和图像提交入口之一
- LocalBufferBroker 用于本机内部隔离进程之间的大图和帧数据交换，不作为外部公开接口
- backend-service 是公开状态与资源视图的统一入口
- 任何对外可见状态都应可被 REST 查询或通过 WebSocket 订阅获得
- ZeroMQ 传输的消息不能替代公开接口的版本规则与审计要求
- LocalBufferBroker 传递的是短期本机数据引用，不能替代 ObjectStore 的正式文件保存规则

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
- 承担正式写入接口
- 作为内部 worker 调度主通道
- 代替外部系统需要的稳定请求响应协议

### ZeroMQ

ZeroMQ 用来做 workstation 或 standalone 场景下的高速协议接入、触发和消息传递。

#### 适合做的事

- 上位机或本地设备代理向平台提交高速触发和图片输入
- ZeroMQTriggerSource 接收主题、请求或帧到达事件并创建 WorkflowRun
- 本地插件进程、桥接进程或边车进程之间的事件转发
- 对延迟敏感且部署边界受控的本地通信路径

#### 不适合做的事

- 浏览器前端直接通信
- 跨公网或跨组织边界的对外公开接口
- 资源查询和管理动作的主接口
- 替代 REST API 与 WebSocket 的版本化规则
- 作为本机内部大图数据面的唯一方案；大图和连续帧应优先进入 LocalBufferBroker

### LocalBufferBroker

LocalBufferBroker 用来做本机内部隔离进程之间的大图、帧和中间结果引用传递。

#### 适合做的事

- workflow preview 进程、workflow runtime worker 和发布推理 worker 之间传递图片引用
- 用 mmap 文件池承载单张图和普通中间结果
- 用 ring buffer channel 承载连续帧和高速输入源
- 通过租约、TTL、引用计数和清理机制管理短期数据

#### 不适合做的事

- 替代 HTTP、ZeroMQ、gRPC、MQTT、PLC 或传感器等外部触发入口
- 替代 ObjectStore 保存需要审计、下载、复现或长期保留的文件
- 跨主机传递数据引用
- 直接作为浏览器前端接口

## 通信职责矩阵

- REST API：资源读写、管理动作、通用同步请求响应
- WebSocket：状态订阅、日志流、实时事件推送
- ZeroMQ：本地或受控网络里的高速触发、图片提交和消息转发
- LocalBufferBroker：本机内部隔离进程之间的大图和帧数据引用

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
- WebSocket 推送只提供状态流视图，不替代 REST 的正式查询接口
- 断线重连需要有从最近状态快照恢复的策略，而不是假设消息永久可靠

## ZeroMQ 规则

- 用于受控部署场景下的高速触发、图片提交和消息传递
- 消息主题、端点和访问权限必须由 backend-service、集成端点或 runtime manifest 管理
- ZeroMQ 消息若影响公开状态，必须回写 backend-service 后再对外发布
- 任何 ZeroMQ 交互都不得绕开审计、超时和管理规则

## LocalBufferBroker 规则

- 只用于本机内部隔离进程之间的数据交换
- BufferRef 和 FrameRef 只在本机短期有效，不写成长期公开接口字段
- 需要保留的图片和结果必须保存到 ObjectStore，并形成正式文件引用
- mmap 文件池必须有固定容量、租约、TTL、心跳、背压和启动清理
- LocalBufferBroker 的详细规划见 [docs/architecture/local-buffer-broker.md](../architecture/local-buffer-broker.md)

## 鉴权与权限边界

- REST API 和 WebSocket 共享统一身份与权限模型
- 外部系统接入应有独立的 endpoint identity 或 access scope
- ZeroMQ 接入应声明 endpoint identity、主题范围和访问权限
- LocalBufferBroker 不作为对外暴露的安全边界，应依赖本机进程隔离、运行时 token 和最小访问面
- 插件触发与回调应声明可访问的事件范围、资源范围和外部端点范围

## 兼容性和版本管理

- 公开 API、事件类型和消息载荷一旦外发，即视为版本规则
- 新字段优先采用向后兼容方式追加
- 行为变更或字段语义变化必须通过版本升级显式表达
- ZeroMQ 消息和 LocalBufferBroker 引用即使不作为公开 REST 字段，也应通过 manifest 或内部 schema 维持稳定边界

## 推荐后续文档

- [docs/architecture/backend-service.md](../architecture/backend-service.md)
- [docs/architecture/system-overview.md](../architecture/system-overview.md)
- [docs/deployment/bundled-python-deployment.md](../deployment/bundled-python-deployment.md)