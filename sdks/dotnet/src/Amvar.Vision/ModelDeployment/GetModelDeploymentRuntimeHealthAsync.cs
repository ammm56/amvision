using System;
using Amvar.Vision;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision.ModelDeployment
{
/// <summary>
/// 模型 DeploymentInstance runtime health 读取操作。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 按 deployment key 读取已存在的模型 DeploymentInstance runtime health。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime health 响应。</returns>
    public async Task<ModelDeploymentRuntimeHealthResponse> GetModelDeploymentRuntimeHealthAsync(
        string modelDeploymentName,
        CancellationToken cancellationToken = default)
    {
        var configuredModelDeployment = GetConfiguredModelDeployment(modelDeploymentName);
        var modelDeployment = configuredModelDeployment.ModelDeployment;
        var deploymentInstanceId = RequireDeploymentInstanceId(configuredModelDeployment);
        var response = await client.GetModelDeploymentRuntimeHealthResponseAsync(
            modelDeployment.TaskType,
            deploymentInstanceId,
            modelDeployment.RuntimeMode,
            cancellationToken).ConfigureAwait(false);
        return response;
    }
}
}
