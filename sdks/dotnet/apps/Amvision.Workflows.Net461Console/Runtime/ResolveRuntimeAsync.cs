using System.Threading;
using System.Threading.Tasks;
using Amvision.Workflows.Net461Console.Model;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// WorkflowAppRuntime 解析操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// runtime 已配置 workflow_runtime_id 时读取现有 runtime，否则按 application_id 创建新 runtime。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>可用 runtime 响应。</returns>
    public Task<WorkflowAppRuntimeResponse> ResolveRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        return ConfigValidation.NormalizeOptional(configuredRuntime.Runtime.WorkflowRuntimeId) is not null
            ? GetRuntimeAsync(runtimeName, cancellationToken)
            : CreateRuntimeAsync(runtimeName, cancellationToken);
    }
}
