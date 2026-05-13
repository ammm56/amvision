# TriggerSource Error Reply v1

ZeroMQ adapter 在协议输入错误、运行时配置错误或内部异常时返回单帧 JSON error reply。

## JSON 形状

```json
{
  "format_id": "amvision.zeromq-trigger-error.v1",
  "trigger_source_id": "trigger-source-04",
  "state": "failed",
  "error_code": "invalid_request",
  "error_message": "ZeroMQ envelope 必须是 UTF-8 JSON",
  "details": {}
}
```

SDK 应把 error reply 转换为语言原生异常，同时保留 `error_code`、`error_message` 和 `details`。