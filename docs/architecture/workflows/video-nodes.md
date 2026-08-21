# 视频 Workflow 节点

## 当前能力

平台当前把视频作为显式 payload 和节点链处理：

- `core.io.video-load-local`
- `core.io.video-decode-frames`
- `core.io.frame-window-item-get`
- `core.io.frame-window-preview`
- `core.vision.tracks-filter`
- `core.vision.tracks-to-regions`
- `core.io.video-overlay-render`
- `core.io.video-save`
- `core.output.video-body`
- `custom.sam3.video-interactive-segment`
- `custom.sam3.video-semantic-segment`

Catalog 是节点 id、端口和参数的最终事实来源。

## 数据边界

```text
video-ref
  → frames / frame-window
  → model or vision processing
  → tracks / regions / overlays
  → video-ref or response body
```

- 视频文件以引用传递，不在节点间复制整段 Base64。
- 帧窗口是有限集合，必须有最大帧数、步长或时间范围。
- 长视频处理不能把所有解码帧长期常驻内存。
- 生成视频保存到明确的 `save_location`，支持 ObjectStore 相对位置或磁盘绝对路径。
- 编解码依赖由发行包的 FFmpeg/runtime 资产提供，缺失时启动或节点执行明确失败。

## Runtime 与稳定性

- Preview 只用于短窗口调试，不代表生产长时吞吐。
- 正式视频 Workflow 使用已发布 App Version 和长期 Runtime Worker。
- Stateful 模型 session 在 Runtime 生命周期内创建与回收，不能保存进图 JSON。
- stop、cancel、timeout、Worker crash 和版本切换必须关闭解码器、编码器、文件句柄和模型 session。
- 并行分支仍受图中的显式并发参数控制，不引入隐藏 batch、排队或自动重试。

## SAM3 视频

SAM3 当前统一使用 Catalog 中的图片与视频分割节点；早期 prototype、shared-prompt、stateful-mask 等名称不是公开参数。模型资产、prompt schema 与本地缓存规则见 [YOLOE/SAM3 节点资产](yoloe-sam3-assets.md)。

## 相关文档

- [Workflow Runtime](runtime.md)
- [模型 Session Runtime](model-session-runtime.md)
- [YOLOE/SAM3 运行](../../operations/yoloe-sam3-workflow.md)
- [发行运行时](../platform/runtime-packaging.md)
