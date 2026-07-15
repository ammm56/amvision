using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.ModelDeployment
{
/// <summary>
/// 模型 DeploymentInstance runtime 停止操作。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 停止已存在的模型 DeploymentInstance runtime。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 状态响应。</returns>
    public async Task<ModelDeploymentRuntimeStatusResponse> StopModelDeploymentRuntimeAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        var deploymentInstanceId = RequireDeploymentInstanceId(configuredModelDeployment);
        var response = await client.StopModelDeploymentRuntimeResponseAsync(
            modelDeployment.TaskType,
            deploymentInstanceId,
            modelDeployment.RuntimeMode,
            cancellationToken).ConfigureAwait(false);
        return response;
    }
}
}
