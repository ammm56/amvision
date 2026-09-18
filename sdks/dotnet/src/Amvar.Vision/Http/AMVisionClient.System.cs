using System.Net.Http;
using System.Net;
using Newtonsoft.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision
{

    public sealed partial class AMVisionClient
    {
        private const string SystemApiPrefix = "api/v1/system";

        /// <summary>同步查询一次当前服务状态，不轮询、不等待启动完成或空闲实例。</summary>
        public ServiceStatusResponse GetServiceStatus(bool details = false,
            CancellationToken cancellationToken = default)
        {
            return GetServiceStatusAsync(cancellationToken, details).GetAwaiter().GetResult();
        }

        /// <summary>异步查询一次当前服务状态；HTTP 503 的有效状态响应正常返回。</summary>
        public async Task<ServiceStatusResponse> GetServiceStatusAsync(
            CancellationToken cancellationToken = default, bool details = false)
        {
            var response = await SendAsync(HttpMethod.Get,
                SystemApiPrefix + "/status" + (details ? "?details=true" : ""),
                content: null, cancellationToken).ConfigureAwait(false);
            if (response.StatusCode != HttpStatusCode.OK && response.StatusCode != HttpStatusCode.ServiceUnavailable)
                response.EnsureSuccessStatusCode();
            var result = JsonConvert.DeserializeObject<ServiceStatusResponse>(response.Content, JsonSettings)
                ?? throw new JsonException("Service status response is null.");
            if ((response.StatusCode == HttpStatusCode.OK) != result.Ready
                || (result.State == "ready") != result.Ready
                || string.IsNullOrWhiteSpace(result.InstanceId)
                || (result.State != "ready" && result.State != "starting" && result.State != "degraded"
                    && result.State != "unavailable" && result.State != "stopping"))
                throw new JsonException("Service status response is inconsistent.");
            return result;
        }

        /// <summary>
        /// 读取 backend-service 已解析的统一配置快照。
        /// </summary>
        public async Task<AMVisionApiResponse> GetSystemConfigAsync(
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{SystemApiPrefix}/config";
            var apiResponse = await SendAsync(
                HttpMethod.Get,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 读取 backend-service 已解析的统一配置快照，并返回 typed response。
        /// </summary>
        public async Task<SystemConfigResponse> GetSystemConfigResponseAsync(
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetSystemConfigAsync(cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<SystemConfigResponse>(apiResponse);
            return typedResponse;
        }
    }
}
