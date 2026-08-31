using Amvar.Vision;
using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace Amvar.Vision.Configuration
{
/// <summary>
/// 已存在 TriggerSource 的控制和协议调用配置，对应 trigger_sources[] 节点。
/// </summary>
internal sealed class TriggerSourceConfig
{
    /// <summary>
    /// 本程序内部使用的 TriggerSource 字典 key。
    /// </summary>
    [JsonProperty("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>
    /// 后端持久化的 WorkflowTriggerSource id。
    /// </summary>
    [JsonProperty("trigger_source_id")]
    public string TriggerSourceId { get; set; } = string.Empty;

    /// <summary>
    /// 当前调用配置对应的 TriggerSource kind。
    /// </summary>
    [JsonProperty("trigger_kind")]
    public string TriggerKind { get; set; } = string.Empty;

    /// <summary>TriggerSource 固定的 application input binding mapping。</summary>
    [JsonProperty("input_binding_mapping")]
    public Dictionary<string, TriggerSourceInputBindingConfig> InputBindingMapping { get; set; } =
        new Dictionary<string, TriggerSourceInputBindingConfig>(StringComparer.Ordinal);

    /// <summary>
    /// ZeroMQ transport 和调用配置。
    /// </summary>
    [JsonProperty("zero_mq")]
    public TriggerSourceZeroMqConfig ZeroMq { get; set; } = null!;

    /// <summary>
    /// 同机共享内存全局 mailbox 调用配置。
    /// </summary>
    [JsonProperty("local_shared_memory")]
    public TriggerSourceLocalSharedMemoryConfig LocalSharedMemory { get; set; } = null!;

    /// <summary>
    /// 校验 TriggerSource 配置是否能控制和调用一个已存在的后端 TriggerSource。
    /// </summary>
    /// <param name="path">配置字段路径。</param>
    public void Validate(string path)
    {
        Name = ConfigValidation.RequireText(Name, $"{path}.name");
        TriggerSourceId = ConfigValidation.RequireText(TriggerSourceId, $"{path}.trigger_source_id");
        TriggerKind = ConfigValidation.RequireText(TriggerKind, $"{path}.trigger_kind");
        InputBindingMapping ??= new Dictionary<string, TriggerSourceInputBindingConfig>(StringComparer.Ordinal);
        foreach (var pair in InputBindingMapping)
        {
            var bindingId = ConfigValidation.RequireText(pair.Key, $"{path}.input_binding_mapping binding id");
            if (pair.Value == null)
            {
                throw new InvalidOperationException(
                    $"{path}.input_binding_mapping.{bindingId} cannot be null.");
            }
            pair.Value.Validate($"{path}.input_binding_mapping.{bindingId}");
        }
        if (string.Equals(TriggerKind, "zeromq-topic", StringComparison.Ordinal))
        {
            if (ZeroMq == null || LocalSharedMemory != null)
            {
                throw new InvalidOperationException($"{path} must contain only zero_mq for zeromq-topic.");
            }

            ZeroMq.Validate($"{path}.zero_mq");
            return;
        }

        if (string.Equals(TriggerKind, "local-shared-memory", StringComparison.Ordinal))
        {
            if (LocalSharedMemory == null || ZeroMq != null)
            {
                throw new InvalidOperationException(
                    $"{path} must contain only local_shared_memory for local-shared-memory.");
            }

            LocalSharedMemory.Validate($"{path}.local_shared_memory");
            return;
        }

        throw new InvalidOperationException($"{path}.trigger_kind is not supported by this SDK: {TriggerKind}.");
    }
}

/// <summary>SDK 构造 typed Trigger inputs 所需的单个 mapping 规则。</summary>
internal sealed class TriggerSourceInputBindingConfig
{
    [JsonProperty("source")]
    public string? Source { get; set; }

    [JsonProperty("value")]
    public object? Value { get; set; }

    [JsonProperty("required")]
    public bool Required { get; set; } = true;

    [JsonProperty("payload_type_id")]
    public string? PayloadTypeId { get; set; }

    [JsonProperty("metadata")]
    public Dictionary<string, object?> Metadata { get; set; } =
        new Dictionary<string, object?>();

    internal void Validate(string path)
    {
        Source = ConfigValidation.NormalizeOptional(Source);
        PayloadTypeId = ConfigValidation.NormalizeOptional(PayloadTypeId);
        Metadata ??= new Dictionary<string, object?>();
    }
}
}
