using Amvision.Workflows;
using System;
using Newtonsoft.Json;

namespace Amvision.Workflows.Configuration
{
/// <summary>
/// ZeroMQ TriggerSource 的 transport 和客户端调用配置。
/// </summary>
internal sealed class TriggerSourceZeroMqConfig
{
    /// <summary>
    /// 后端 ZeroMQ adapter 绑定的 endpoint，例如 tcp://127.0.0.1:5555。
    /// </summary>
    [JsonProperty("bind_endpoint")]
    public string BindEndpoint { get; set; } = "tcp://127.0.0.1:5555";

    /// <summary>
    /// ZeroMQ 图片第二帧写入 workflow 的默认 input binding；必须和前端已创建 TriggerSource 的 mapping 对齐。
    /// </summary>
    [JsonProperty("default_input_binding")]
    public string DefaultInputBinding { get; set; } = "request_image_ref";

    /// <summary>
    /// 单次 ZeroMQ 图片触发允许的最大图片 bytes，默认 256MB，覆盖 20MP/4K 级工业相机 raw BGR24 输入。
    /// </summary>
    [JsonProperty("max_image_bytes")]
    public int MaxImageBytes { get; set; } = 256 * 1024 * 1024;

    /// <summary>
    /// ZeroMQ 请求等待 reply 的超时时间，单位为秒。
    /// </summary>
    [JsonProperty("timeout_seconds")]
    public int TimeoutSeconds { get; set; } = 5;

    /// <summary>
    /// 校验 ZeroMQ 配置是否可用于 SDK client 调用。
    /// </summary>
    /// <param name="path">配置字段路径。</param>
    public void Validate(string path)
    {
        ConfigValidation.RequireText(BindEndpoint, $"{path}.bind_endpoint");
        ConfigValidation.RequireText(DefaultInputBinding, $"{path}.default_input_binding");
        if (TimeoutSeconds <= 0)
        {
            throw new InvalidOperationException($"{path}.timeout_seconds must be greater than zero.");
        }

        if (MaxImageBytes <= 0)
        {
            throw new InvalidOperationException($"{path}.max_image_bytes must be greater than zero.");
        }
    }
}
}
