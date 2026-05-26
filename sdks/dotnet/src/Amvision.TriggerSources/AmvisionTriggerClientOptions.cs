using System;

namespace Amvision.TriggerSources;

/// <summary>
/// <see cref="AmvisionTriggerClient" /> 使用的连接和默认调用参数。
/// </summary>
public sealed class AmvisionTriggerClientOptions
{
    /// <summary>
    /// ZeroMQ endpoint，例如 tcp://127.0.0.1:5555。
    /// </summary>
    public string Endpoint { get; set; } = string.Empty;

    /// <summary>
    /// 目标 WorkflowTriggerSource id。
    /// </summary>
    public string TriggerSourceId { get; set; } = string.Empty;

    /// <summary>
    /// 图片 bytes 默认绑定到的 FlowApplication input binding。
    /// </summary>
    public string DefaultInputBinding { get; set; } = "request_image";

    /// <summary>
    /// 发送和接收超时时间。
    /// </summary>
    public TimeSpan Timeout { get; set; } = TimeSpan.FromSeconds(5);

    /// <summary>
    /// 校验客户端参数是否满足当前初始化场景。
    /// </summary>
    /// <param name="requireEndpoint">是否要求 Endpoint 必填。</param>
    internal void Validate(bool requireEndpoint)
    {
        if (requireEndpoint && string.IsNullOrWhiteSpace(Endpoint))
        {
            throw new ArgumentException("Endpoint cannot be empty.", nameof(Endpoint));
        }

        if (string.IsNullOrWhiteSpace(TriggerSourceId))
        {
            throw new ArgumentException("TriggerSourceId cannot be empty.", nameof(TriggerSourceId));
        }

        if (string.IsNullOrWhiteSpace(DefaultInputBinding))
        {
            throw new ArgumentException("DefaultInputBinding cannot be empty.", nameof(DefaultInputBinding));
        }

        if (Timeout <= TimeSpan.Zero)
        {
            throw new ArgumentException("Timeout must be greater than zero.", nameof(Timeout));
        }
    }
}