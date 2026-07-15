using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Amvision.Workflows;
using Amvision.Workflows.Configuration;

namespace Amvision.Workflows.Runtime
{
/// <summary>
/// WorkflowRun 事件读取操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 读取指定 WorkflowRun 的事件，并使用 runtime 配置控制返回条数。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="workflowRunId">WorkflowRun id。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 事件列表。</returns>
    public async Task<IReadOnlyList<WorkflowRunEventResponse>> GetWorkflowRunEventsAsync(
        string runtimeName,
        string workflowRunId,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        return await client.GetWorkflowRunEventResponsesAsync(
            ConfigValidation.RequireText(workflowRunId, nameof(workflowRunId)),
            limit: configuredRuntime.Invoke.EventLimit,
            cancellationToken: cancellationToken).ConfigureAwait(false);
    }
}
}
