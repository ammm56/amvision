using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows
{

    public sealed partial class AmvisionWorkflowClient
    {
        private const string ModelApiPrefix = "api/v1/models";

        /// <summary>
        /// 启动模型部署 runtime。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> StartModelDeploymentRuntimeAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var responseTask = SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Post,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "start",
                cancellationToken);

            return responseTask;
        }

        /// <summary>
        /// 启动模型部署 runtime，并返回 typed response。
        /// </summary>
        public async Task<ModelDeploymentRuntimeStatusResponse> StartModelDeploymentRuntimeResponseAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await StartModelDeploymentRuntimeAsync(
                taskType,
                deploymentInstanceId,
                runtimeMode,
                cancellationToken).ConfigureAwait(false);

            var typedResponse = ReadJson<ModelDeploymentRuntimeStatusResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 停止模型部署 runtime。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> StopModelDeploymentRuntimeAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var responseTask = SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Post,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "stop",
                cancellationToken);

            return responseTask;
        }

        /// <summary>
        /// 停止模型部署 runtime，并返回 typed response。
        /// </summary>
        public async Task<ModelDeploymentRuntimeStatusResponse> StopModelDeploymentRuntimeResponseAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await StopModelDeploymentRuntimeAsync(
                taskType,
                deploymentInstanceId,
                runtimeMode,
                cancellationToken).ConfigureAwait(false);

            var typedResponse = ReadJson<ModelDeploymentRuntimeStatusResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 重置模型部署 runtime。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> ResetModelDeploymentRuntimeAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var responseTask = SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Post,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "reset",
                cancellationToken);

            return responseTask;
        }

        /// <summary>
        /// 重置模型部署 runtime，并返回 typed response。
        /// </summary>
        public async Task<ModelDeploymentRuntimeStatusResponse> ResetModelDeploymentRuntimeResponseAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await ResetModelDeploymentRuntimeAsync(
                taskType,
                deploymentInstanceId,
                runtimeMode,
                cancellationToken).ConfigureAwait(false);

            var typedResponse = ReadJson<ModelDeploymentRuntimeStatusResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 预热模型部署 runtime。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> WarmupModelDeploymentRuntimeAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var responseTask = SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Post,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "warmup",
                cancellationToken);

            return responseTask;
        }

        /// <summary>
        /// 预热模型部署 runtime，并返回 typed response。
        /// </summary>
        public async Task<ModelDeploymentRuntimeWarmupResponse> WarmupModelDeploymentRuntimeResponseAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await WarmupModelDeploymentRuntimeAsync(
                taskType,
                deploymentInstanceId,
                runtimeMode,
                cancellationToken).ConfigureAwait(false);

            var typedResponse = ReadJson<ModelDeploymentRuntimeWarmupResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 读取模型部署 runtime 状态。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> GetModelDeploymentRuntimeStatusAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var responseTask = SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Get,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "status",
                cancellationToken);

            return responseTask;
        }

        /// <summary>
        /// 读取模型部署 runtime 状态，并返回 typed response。
        /// </summary>
        public async Task<ModelDeploymentRuntimeStatusResponse> GetModelDeploymentRuntimeStatusResponseAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetModelDeploymentRuntimeStatusAsync(
                taskType,
                deploymentInstanceId,
                runtimeMode,
                cancellationToken).ConfigureAwait(false);

            var typedResponse = ReadJson<ModelDeploymentRuntimeStatusResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 读取模型部署 runtime health。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> GetModelDeploymentRuntimeHealthAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var responseTask = SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Get,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "health",
                cancellationToken);

            return responseTask;
        }

        /// <summary>
        /// 读取模型部署 runtime health，并返回 typed response。
        /// </summary>
        public async Task<ModelDeploymentRuntimeHealthResponse> GetModelDeploymentRuntimeHealthResponseAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetModelDeploymentRuntimeHealthAsync(
                taskType,
                deploymentInstanceId,
                runtimeMode,
                cancellationToken).ConfigureAwait(false);

            var typedResponse = ReadJson<ModelDeploymentRuntimeHealthResponse>(apiResponse);
            return typedResponse;
        }

        private async Task<AmvisionWorkflowApiResponse> SendModelDeploymentRuntimeCommandAsync(
            HttpMethod method,
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            string action,
            CancellationToken cancellationToken)
        {
            var requestPath = BuildModelDeploymentRuntimePath(taskType, deploymentInstanceId, runtimeMode, action);
            var apiResponse = await SendAsync(method, requestPath, content: null, cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        private static string BuildModelDeploymentRuntimePath(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            string action)
        {
            return $"{ModelApiPrefix}/{ModelTaskTypes.Normalize(taskType)}/deployment-instances/{EncodePathSegment(RequireId(deploymentInstanceId, nameof(deploymentInstanceId)))}/{ModelDeploymentRuntimeModes.Normalize(runtimeMode)}/{action}";
        }
    }
}
