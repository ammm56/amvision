using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision
{

    public sealed partial class AMVisionClient
    {
        private const string SystemApiPrefix = "api/v1/system";

        /// <summary>
        /// 读取 backend-service 已解析的统一配置快照。
        /// </summary>
        public Task<AMVisionApiResponse> GetSystemConfigAsync(
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{SystemApiPrefix}/config";
            var responseTask = SendAsync(HttpMethod.Get, requestPath, content: null, cancellationToken);
            return responseTask;
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
