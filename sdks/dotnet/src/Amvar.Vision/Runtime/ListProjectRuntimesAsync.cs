using System;
using Amvar.Vision;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision.Runtime
{
/// <summary>
/// Project 下 WorkflowAppRuntime 列表读取操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 使用 runtime key 对应的 project_id 列出 Project 下 runtime。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 列表。</returns>
    public async Task<IReadOnlyList<WorkflowAppRuntimeResponse>> ListProjectRuntimesAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var runtimes = await client.ListWorkflowAppRuntimeResponsesAsync(
            configuredRuntime.Backend.ProjectId,
            limit: 20,
            cancellationToken: cancellationToken).ConfigureAwait(false);

        return runtimes;
    }
}
}
