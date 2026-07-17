using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision
{

    public sealed partial class AMVisionClient
    {
        private const string ModelApiPrefix = "api/v1/models";

        /// <summary>
        /// 启动模型部署 runtime。
        /// </summary>
        /// <remarks>
        /// 返回原始 HTTP API 响应。后端返回 4xx/5xx 时不会在此方法内抛出 API 异常，调用方可通过
        /// IsSuccessStatusCode、ErrorCode、ErrorMessage 和 ErrorDetails 判断失败原因。
        /// </remarks>
        public async Task<AMVisionApiResponse> StartModelDeploymentRuntimeAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Post,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "start",
                cancellationToken).ConfigureAwait(false);

            return apiResponse;
        }

        /// <summary>
        /// 启动模型部署 runtime，并按成功响应读取进程状态。
        /// </summary>
        /// <remarks>
        /// typed 方法会校验 HTTP 状态码；后端返回 4xx/5xx 时会抛出 AMVisionApiException。
        /// </remarks>
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
        /// <remarks>
        /// 返回原始 HTTP API 响应。后端返回 4xx/5xx 时不会在此方法内抛出 API 异常。
        /// </remarks>
        public async Task<AMVisionApiResponse> StopModelDeploymentRuntimeAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Post,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "stop",
                cancellationToken).ConfigureAwait(false);

            return apiResponse;
        }

        /// <summary>
        /// 停止模型部署 runtime，并按成功响应读取进程状态。
        /// </summary>
        /// <remarks>
        /// typed 方法会校验 HTTP 状态码；后端返回 4xx/5xx 时会抛出 AMVisionApiException。
        /// </remarks>
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
        /// <remarks>
        /// 返回原始 HTTP API 响应。后端返回 4xx/5xx 时不会在此方法内抛出 API 异常。
        /// </remarks>
        public async Task<AMVisionApiResponse> ResetModelDeploymentRuntimeAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Post,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "reset",
                cancellationToken).ConfigureAwait(false);

            return apiResponse;
        }

        /// <summary>
        /// 重置模型部署 runtime，并按成功响应读取 runtime health。
        /// </summary>
        /// <remarks>
        /// 后端 reset 接口返回 health，而不是 status。typed 方法会校验 HTTP 状态码；后端返回 4xx/5xx
        /// 时会抛出 AMVisionApiException。
        /// </remarks>
        public async Task<ModelDeploymentRuntimeHealthResponse> ResetModelDeploymentRuntimeResponseAsync(
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

            var typedResponse = ReadJson<ModelDeploymentRuntimeHealthResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 预热模型部署 runtime。
        /// </summary>
        /// <remarks>
        /// 返回原始 HTTP API 响应。后端返回 4xx/5xx 时不会在此方法内抛出 API 异常。
        /// </remarks>
        public async Task<AMVisionApiResponse> WarmupModelDeploymentRuntimeAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Post,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "warmup",
                cancellationToken).ConfigureAwait(false);

            return apiResponse;
        }

        /// <summary>
        /// 预热模型部署 runtime，并按成功响应读取 runtime health。
        /// </summary>
        /// <remarks>
        /// 后端 warmup 接口返回 health，而不是独立 warmup payload。typed 方法会校验 HTTP 状态码；
        /// 后端返回 4xx/5xx 时会抛出 AMVisionApiException。
        /// </remarks>
        public async Task<ModelDeploymentRuntimeHealthResponse> WarmupModelDeploymentRuntimeResponseAsync(
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

            var typedResponse = ReadJson<ModelDeploymentRuntimeHealthResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 读取模型部署 runtime 状态。
        /// </summary>
        public async Task<AMVisionApiResponse> GetModelDeploymentRuntimeStatusAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Get,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "status",
                cancellationToken).ConfigureAwait(false);

            return apiResponse;
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
        public async Task<AMVisionApiResponse> GetModelDeploymentRuntimeHealthAsync(
            string taskType,
            string deploymentInstanceId,
            string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await SendModelDeploymentRuntimeCommandAsync(
                HttpMethod.Get,
                taskType,
                deploymentInstanceId,
                runtimeMode,
                "health",
                cancellationToken).ConfigureAwait(false);

            return apiResponse;
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

        private async Task<AMVisionApiResponse> SendModelDeploymentRuntimeCommandAsync(
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
