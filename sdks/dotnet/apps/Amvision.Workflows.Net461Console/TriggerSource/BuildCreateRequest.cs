using Amvision.Workflows.Net461Console.Model;

namespace Amvision.Workflows.Net461Console.TriggerSource;

/// <summary>
/// TriggerSource 创建请求组装逻辑。
/// </summary>
internal sealed partial class WorkflowTriggerSourceOperations
{
    /// <summary>
    /// 将 config_*.json 中的 TriggerSource 配置转换为 SDK typed create request。
    /// </summary>
    /// <param name="configuredTriggerSource">已展开的 TriggerSource 配置。</param>
    /// <returns>TriggerSource 创建请求。</returns>
    private static WorkflowTriggerSourceCreateRequest BuildCreateRequest(ConfiguredTriggerSource configuredTriggerSource)
    {
        var runtimeId = ConfigValidation.NormalizeOptional(configuredTriggerSource.Runtime.WorkflowRuntimeId);
        if (runtimeId is null)
        {
            throw new System.InvalidOperationException(
                $"Runtime {configuredTriggerSource.Runtime.Name} does not have workflow_runtime_id.");
        }

        var triggerSource = configuredTriggerSource.TriggerSource;
        var request = new WorkflowTriggerSourceCreateRequest
        {
            TriggerSourceId = triggerSource.TriggerSourceId,
            ProjectId = configuredTriggerSource.Backend.ProjectId,
            DisplayName = triggerSource.DisplayName,
            TriggerKind = triggerSource.TriggerKind,
            WorkflowRuntimeId = runtimeId,
            SubmitMode = triggerSource.SubmitMode,
            Enabled = triggerSource.Enabled,
            AckPolicy = triggerSource.AckPolicy,
            ResultMode = triggerSource.ResultMode,
            ReplyTimeoutSeconds = triggerSource.ReplyTimeoutSeconds,
            DebounceWindowMs = triggerSource.DebounceWindowMs,
            IdempotencyKeyPath = triggerSource.IdempotencyKeyPath,
            ResultMapping = new WorkflowTriggerResultMapping
            {
                ResultBinding = triggerSource.ResultBinding,
                ResultMode = triggerSource.ResultMode,
                ReplyTimeoutSeconds = triggerSource.ReplyTimeoutSeconds
            }
        };

        request.TransportConfig["bind_endpoint"] = triggerSource.ZeroMq.BindEndpoint;
        request.TransportConfig["pool_name"] = triggerSource.ZeroMq.PoolName;
        foreach (var pair in triggerSource.MatchRule)
        {
            request.MatchRule[pair.Key] = pair.Value;
        }

        foreach (var pair in triggerSource.InputBindingMapping)
        {
            var item = pair.Value;
            var mappingItem = new WorkflowTriggerInputBindingMappingItem
            {
                Source = item.Source,
                Value = item.Value,
                Required = item.Required,
                PayloadTypeId = item.PayloadTypeId
            };
            foreach (var metadata in item.Metadata)
            {
                mappingItem.Metadata[metadata.Key] = metadata.Value;
            }

            request.InputBindingMapping[pair.Key] = mappingItem;
        }

        foreach (var pair in triggerSource.DefaultExecutionMetadata)
        {
            request.DefaultExecutionMetadata[pair.Key] = pair.Value;
        }

        foreach (var pair in triggerSource.Metadata)
        {
            request.Metadata[pair.Key] = pair.Value;
        }

        request.ResultMapping.Metadata["trigger_source_name"] = triggerSource.Name;
        request.Metadata["trigger_source_name"] = triggerSource.Name;
        request.Metadata["runtime_name"] = configuredTriggerSource.Runtime.Name;
        return request;
    }
}
