using System;
using System.Text.Json.Serialization;

namespace Amvision.Workflows.Net461Console.Model;

/// <summary>
/// ZeroMQ TriggerSource 的 transport 和客户端调用配置。
/// </summary>
internal sealed class TriggerSourceZeroMqConfig
{
    /// <summary>
    /// 后端 ZeroMQ adapter 绑定的 endpoint，例如 tcp://127.0.0.1:5555。
    /// </summary>
    [JsonPropertyName("bind_endpoint")]
    public string BindEndpoint { get; set; } = "tcp://127.0.0.1:5555";

    /// <summary>
    /// 后端 LocalBufferBroker 使用的图片 buffer pool 名称。
    /// </summary>
    [JsonPropertyName("pool_name")]
    public string PoolName { get; set; } = "image-1080p";

    /// <summary>
    /// ZeroMQ 图片第二帧写入 workflow 的默认 input binding。
    /// </summary>
    [JsonPropertyName("default_input_binding")]
    public string DefaultInputBinding { get; set; } = "request_image_ref";

    /// <summary>
    /// ZeroMQ 请求等待 reply 的超时时间，单位为秒。
    /// </summary>
    [JsonPropertyName("timeout_seconds")]
    public int TimeoutSeconds { get; set; } = 5;

    /// <summary>
    /// 校验 ZeroMQ 配置是否可用于创建 TriggerSource 和 SDK client。
    /// </summary>
    /// <param name="path">配置字段路径。</param>
    public void Validate(string path)
    {
        ConfigValidation.RequireText(BindEndpoint, $"{path}.bind_endpoint");
        ConfigValidation.RequireText(PoolName, $"{path}.pool_name");
        ConfigValidation.RequireText(DefaultInputBinding, $"{path}.default_input_binding");
        if (TimeoutSeconds <= 0)
        {
            throw new InvalidOperationException($"{path}.timeout_seconds must be greater than zero.");
        }
    }
}
