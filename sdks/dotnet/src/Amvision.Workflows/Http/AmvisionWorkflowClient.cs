using System;
using System.Net.Http;
using System.Text.Json;

namespace Amvision.Workflows
{

    /// <summary>
    /// backend-service Workflow runtime 与 TriggerSource HTTP 管理 API 的 SDK client。
    /// </summary>
    public sealed partial class AmvisionWorkflowClient : IDisposable
    {
        private const string WorkflowApiPrefix = "api/v1/workflows";

        private static readonly JsonSerializerOptions JsonOptions = WorkflowJsonDefaults.SerializerOptions;

        private readonly AmvisionWorkflowClientOptions options;
        private readonly HttpClient httpClient;
        private readonly bool ownsHttpClient;
        private bool disposed;

        /// <summary>
        /// 使用 SDK 自建 HttpClient 初始化管理 API client。
        /// </summary>
        /// <param name="options">HTTP 管理 API 参数。</param>
        public AmvisionWorkflowClient(AmvisionWorkflowClientOptions options)
        {
            this.options = options ?? throw new ArgumentNullException(nameof(options));
            this.options.Validate();
            httpClient = new HttpClient
            {
                BaseAddress = new Uri(NormalizeBaseApiUrl(this.options.BaseApiUrl), UriKind.Absolute),
                Timeout = this.options.Timeout
            };
            ownsHttpClient = true;
        }

        /// <summary>
        /// 使用外部提供的 HttpClient 初始化管理 API client。
        /// </summary>
        /// <param name="options">HTTP 管理 API 参数。</param>
        /// <param name="httpClient">外部提供的 HttpClient。</param>
        public AmvisionWorkflowClient(AmvisionWorkflowClientOptions options, HttpClient httpClient)
        {
            this.options = options ?? throw new ArgumentNullException(nameof(options));
            this.options.Validate();
            this.httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
            if (this.httpClient.BaseAddress is null)
            {
                this.httpClient.BaseAddress = new Uri(NormalizeBaseApiUrl(this.options.BaseApiUrl), UriKind.Absolute);
            }

            ownsHttpClient = false;
        }

        /// <summary>
        /// 释放 SDK 内部持有的 HttpClient。
        /// </summary>
        public void Dispose()
        {
            if (disposed)
            {
                return;
            }

            if (ownsHttpClient)
            {
                httpClient.Dispose();
            }

            disposed = true;
        }
    }
}
