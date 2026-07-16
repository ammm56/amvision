using Amvar.Vision;
using System;
using Amvar.Vision.Configuration;

namespace Amvar.Vision.Runtime
{
/// <summary>
/// 构建普通 JSON runtime invoke 请求。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 构建不包含外部图片输入的 invoke 请求，适用于图内部读图、相机节点或纯事件触发流程。
    /// </summary>
    /// <param name="configuredRuntime">runtime 配置。</param>
    /// <param name="scenario">写入 execution_metadata 的场景名。</param>
    /// <returns>JSON invoke 请求。</returns>
    private static WorkflowRuntimeInvokeRequest BuildJsonInvokeRequest(
        ConfiguredRuntime configuredRuntime,
        string scenario)
    {
        var request = new WorkflowRuntimeInvokeRequest
        {
            TimeoutSeconds = configuredRuntime.Invoke.TimeoutSeconds,
            UseDirectInputBindings = configuredRuntime.Invoke.UseDirectInputBindings
        };
        request.ExecutionMetadata["source"] = configuredRuntime.Invoke.Source;
        request.ExecutionMetadata["scenario"] = scenario;
        request.ExecutionMetadata["runtime_name"] = configuredRuntime.Runtime.Name;
        request.ExecutionMetadata["request_id"] = $"request-{Guid.NewGuid():N}";
        return request;
    }
}
}
