using System;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// WorkflowAppRuntime 调用后的清理操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按配置清理 runtime；只对本进程创建的 runtime 或显式 stop_at_end 执行停止。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    public async Task CleanupRuntimeAsync(string runtimeName, CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var workflowRuntimeId = RequireRuntimeId(configuredRuntime);
        try
        {
            if (createdRuntimeNames.Contains(configuredRuntime.Runtime.Name) || configuredRuntime.Cleanup.StopAtEnd)
            {
                await StopRuntimeAsync(runtimeName, cancellationToken).ConfigureAwait(false);
            }

            if (createdRuntimeNames.Contains(configuredRuntime.Runtime.Name) && configuredRuntime.Cleanup.DeleteCreatedRuntime)
            {
                await DeleteRuntimeAsync(runtimeName, cancellationToken).ConfigureAwait(false);
            }
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"Runtime cleanup failed for {workflowRuntimeId}: {exception.Message}");
        }
    }
}
