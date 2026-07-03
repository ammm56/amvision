using System;
using System.Text.Json.Serialization;

namespace Amvision.Workflows.Net461Console.Model;

/// <summary>
/// 已存在 TriggerSource 的控制和协议调用配置，对应 trigger_sources[] 节点。
/// </summary>
internal sealed class TriggerSourceConfig
{
    /// <summary>
    /// 本程序内部使用的 TriggerSource 字典 key。
    /// </summary>
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>
    /// 后端持久化的 WorkflowTriggerSource id。
    /// </summary>
    [JsonPropertyName("trigger_source_id")]
    public string TriggerSourceId { get; set; } = string.Empty;

    /// <summary>
    /// ZeroMQ transport 和调用配置。
    /// </summary>
    [JsonPropertyName("zero_mq")]
    public TriggerSourceZeroMqConfig ZeroMq { get; set; } = new TriggerSourceZeroMqConfig();

    /// <summary>
    /// 校验 TriggerSource 配置是否能控制和调用一个已存在的后端 TriggerSource。
    /// </summary>
    /// <param name="path">配置字段路径。</param>
    public void Validate(string path)
    {
        Name = ConfigValidation.RequireText(Name, $"{path}.name");
        TriggerSourceId = ConfigValidation.RequireText(TriggerSourceId, $"{path}.trigger_source_id");
        ZeroMq.Validate($"{path}.zero_mq");
    }
}
