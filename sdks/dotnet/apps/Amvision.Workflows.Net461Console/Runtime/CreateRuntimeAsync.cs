using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// WorkflowAppRuntime 创建操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 使用 runtime key 对应配置创建 WorkflowAppRuntime，并把返回的 workflow_runtime_id 写回内存配置。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>后端返回的 runtime 响应。</returns>
    public async Task<WorkflowAppRuntimeResponse> CreateRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var request = new WorkflowAppRuntimeCreateRequest
        {
            ProjectId = configuredRuntime.Backend.ProjectId,
            ApplicationId = configuredRuntime.Runtime.ApplicationId!,
            ExecutionPolicyId = configuredRuntime.Runtime.ExecutionPolicyId,
            DisplayName = configuredRuntime.Runtime.DisplayName,
            RequestTimeoutSeconds = configuredRuntime.Runtime.RequestTimeoutSeconds,
            HeartbeatIntervalSeconds = configuredRuntime.Runtime.HeartbeatIntervalSeconds,
            HeartbeatTimeoutSeconds = configuredRuntime.Runtime.HeartbeatTimeoutSeconds
        };
        request.Metadata["source"] = configuredRuntime.Invoke.Source;
        request.Metadata["runtime_name"] = configuredRuntime.Runtime.Name;

        var runtime = await client.CreateWorkflowAppRuntimeResponseAsync(request, cancellationToken).ConfigureAwait(false);
        configuredRuntime.Runtime.WorkflowRuntimeId = runtime.WorkflowRuntimeId;
        createdRuntimeNames.Add(configuredRuntime.Runtime.Name);
        Console.WriteLine($"Created runtime: {configuredRuntime.Runtime.Name} | {runtime.WorkflowRuntimeId}");
        return runtime;
    }
}
