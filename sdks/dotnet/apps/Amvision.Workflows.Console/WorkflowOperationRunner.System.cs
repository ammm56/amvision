using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console;

/// <summary>
/// WorkflowOperationRunner 中面向后端统一配置的调用入口。
/// </summary>
public sealed partial class WorkflowOperationRunner
{
    /// <summary>
    /// 读取 backend-service 已解析的统一配置快照。
    /// </summary>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>统一配置快照响应。</returns>
    public Task<SystemConfigResponse> GetSystemConfigAsync(
        CancellationToken cancellationToken = default)
    {
        return workflowClient.GetSystemConfigResponseAsync(cancellationToken);
    }
}
