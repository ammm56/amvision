using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console.ModelDeployment
{
/// <summary>
/// 模型 DeploymentInstance runtime 状态读取操作。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 读取已存在的模型 DeploymentInstance runtime 状态。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 状态响应。</returns>
    public Task<ModelDeploymentRuntimeStatusResponse> GetModelDeploymentRuntimeStatusAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        return client.GetModelDeploymentRuntimeStatusResponseAsync(
            modelDeployment.TaskType,
            RequireDeploymentInstanceId(configuredModelDeployment),
            modelDeployment.RuntimeMode,
            cancellationToken);
    }
}
}
