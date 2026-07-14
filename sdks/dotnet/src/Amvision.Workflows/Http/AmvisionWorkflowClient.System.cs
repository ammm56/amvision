using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows
{

    public sealed partial class AmvisionWorkflowClient
    {
        private const string SystemApiPrefix = "api/v1/system";

        /// <summary>
        /// 读取 backend-service 已解析的统一配置快照。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> GetSystemConfigAsync(
            CancellationToken cancellationToken = default)
        {
            return SendAsync(HttpMethod.Get, $"{SystemApiPrefix}/config", content: null, cancellationToken);
        }

        /// <summary>
        /// 读取 backend-service 已解析的统一配置快照，并返回 typed response。
        /// </summary>
        public async Task<SystemConfigResponse> GetSystemConfigResponseAsync(
            CancellationToken cancellationToken = default)
        {
            return ReadJson<SystemConfigResponse>(
                await GetSystemConfigAsync(cancellationToken).ConfigureAwait(false));
        }
    }
}
