using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.ModelDeployment
{
/// <summary>
/// 模型 DeploymentInstance runtime 重置操作。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 重置已存在的模型 DeploymentInstance runtime。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 状态响应。</returns>
    public Task<ModelDeploymentRuntimeStatusResponse> ResetModelDeploymentRuntimeAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        return client.ResetModelDeploymentRuntimeResponseAsync(
            modelDeployment.TaskType,
            RequireDeploymentInstanceId(configuredModelDeployment),
            modelDeployment.RuntimeMode,
            cancellationToken);
    }
}
}
