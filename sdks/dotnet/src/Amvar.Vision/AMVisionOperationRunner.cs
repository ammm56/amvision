using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision.Configuration;
using Amvar.Vision.ModelDeployment;
using Amvar.Vision.Runtime;
using Amvar.Vision.TriggerSource;
using Amvar.Vision.TriggerSource.ZeroMQ;

namespace Amvar.Vision
{
    /// <summary>
    /// 按 Config/config*.json 的 key 调用视觉后端的高层 SDK 入口。
    /// </summary>
    /// <remarks>
    /// 该类面向第三方集成和现场长期运行场景，一次加载配置后复用 HTTP client、operation 对象和 ZeroMQ client。
    /// 需要直接访问底层 REST API 时，可以通过 <see cref="Client"/> 调用 AMVisionClient 上的完整接口。
    /// </remarks>
    public sealed partial class AMVisionOperationRunner : IDisposable
    {
        /// <summary>
        /// 底层 HTTP SDK client。
        /// </summary>
        private readonly AMVisionClient client;

        /// <summary>
        /// Config/config*.json 加载后的只读配置索引。
        /// </summary>
        private readonly WorkflowConfigurationCatalog catalog;

        /// <summary>
        /// Workflow runtime 操作集合。
        /// </summary>
        private readonly WorkflowRuntimeOperations workflowRuntimeOperations;

        /// <summary>
        /// 模型 deployment 操作集合。
        /// </summary>
        private readonly ModelDeploymentOperations modelDeploymentOperations;

        /// <summary>
        /// TriggerSource 管理操作集合。
        /// </summary>
        private readonly WorkflowTriggerSourceOperations triggerSourceOperations;

        /// <summary>
        /// ZeroMQ TriggerSource 协议调用操作集合。
        /// </summary>
        private readonly ZeroMqTriggerOperations zeroMqTriggerOperations;

        /// <summary>
        /// 当前 runner 是否负责释放底层 client。
        /// </summary>
        private readonly bool ownsClient;

        /// <summary>
        /// 已加载的 Workflow runtime 配置 key。
        /// </summary>
        private readonly IReadOnlyList<string> runtimeNames;

        /// <summary>
        /// 已加载的 TriggerSource 配置 key。
        /// </summary>
        private readonly IReadOnlyList<string> triggerSourceNames;

        /// <summary>
        /// 已加载的模型 deployment 配置 key。
        /// </summary>
        private readonly IReadOnlyList<string> modelDeploymentNames;

        /// <summary>
        /// 标记 runner 是否已经释放。
        /// </summary>
        private int disposed;

        /// <summary>
        /// 使用默认 Config 目录创建完整操作入口。
        /// </summary>
        /// <returns>可按配置 key 调用的 SDK 操作入口。</returns>
        public static AMVisionOperationRunner CreateDefault()
        {
            var client = AMVisionClient.CreateFromConfig();
            var runner = FromOwnedClient(client);
            return runner;
        }

        /// <summary>
        /// 使用指定 Config 目录创建完整操作入口。
        /// </summary>
        /// <param name="configDirectory">Config 目录路径。</param>
        /// <returns>可按配置 key 调用的 SDK 操作入口。</returns>
        public static AMVisionOperationRunner CreateFromConfigDirectory(string configDirectory)
        {
            var client = AMVisionClient.CreateFromConfigDirectory(configDirectory);
            var runner = FromOwnedClient(client);
            return runner;
        }

        /// <summary>
        /// 使用已经按 Config 创建的 AMVisionClient 创建操作入口。
        /// </summary>
        /// <param name="client">已通过 AMVisionClient.CreateFromConfig 或 CreateFromConfigDirectory 创建的 client。</param>
        /// <returns>可按配置 key 调用的 SDK 操作入口。</returns>
        public static AMVisionOperationRunner FromClient(AMVisionClient client)
        {
            if (client == null)
            {
                throw new ArgumentNullException(nameof(client));
            }

            var catalog = client.RequireConfigurationCatalog();
            var runner = new AMVisionOperationRunner(client, catalog, ownsClient: false);
            return runner;
        }

        /// <summary>
        /// 使用 runner 自己创建的 AMVisionClient 创建操作入口。
        /// </summary>
        /// <param name="client">已经绑定配置索引的 client。</param>
        /// <returns>可按配置 key 调用的 SDK 操作入口。</returns>
        private static AMVisionOperationRunner FromOwnedClient(AMVisionClient client)
        {
            var catalog = client.RequireConfigurationCatalog();
            var runner = new AMVisionOperationRunner(client, catalog, ownsClient: true);
            return runner;
        }

        /// <summary>
        /// 初始化完整操作入口。
        /// </summary>
        /// <param name="client">底层 HTTP SDK client。</param>
        /// <param name="catalog">配置索引。</param>
        /// <param name="ownsClient">是否由当前 runner 释放 client。</param>
        private AMVisionOperationRunner(
            AMVisionClient client,
            WorkflowConfigurationCatalog catalog,
            bool ownsClient)
        {
            this.client = client ?? throw new ArgumentNullException(nameof(client));
            this.catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
            this.ownsClient = ownsClient;

            workflowRuntimeOperations = new WorkflowRuntimeOperations(this.client, this.catalog);
            modelDeploymentOperations = new ModelDeploymentOperations(this.client, this.catalog);
            triggerSourceOperations = new WorkflowTriggerSourceOperations(this.client, this.catalog);
            zeroMqTriggerOperations = new ZeroMqTriggerOperations(this.catalog);

            runtimeNames = SortKeys(this.catalog.Runtimes.Keys);
            triggerSourceNames = SortKeys(this.catalog.TriggerSources.Keys);
            modelDeploymentNames = SortKeys(this.catalog.ModelDeployments.Keys);
        }

        /// <summary>
        /// 底层 HTTP SDK client，保留完整后端 REST API 调用能力。
        /// </summary>
        public AMVisionClient Client
        {
            get
            {
                EnsureNotDisposed();
                return client;
            }
        }

        /// <summary>
        /// 已加载的 Workflow runtime 配置 key。
        /// </summary>
        public IReadOnlyList<string> RuntimeNames
        {
            get
            {
                EnsureNotDisposed();
                return runtimeNames;
            }
        }

        /// <summary>
        /// 已加载的 TriggerSource 配置 key。
        /// </summary>
        public IReadOnlyList<string> TriggerSourceNames
        {
            get
            {
                EnsureNotDisposed();
                return triggerSourceNames;
            }
        }

        /// <summary>
        /// 已加载的模型 deployment 配置 key。
        /// </summary>
        public IReadOnlyList<string> ModelDeploymentNames
        {
            get
            {
                EnsureNotDisposed();
                return modelDeploymentNames;
            }
        }

        /// <summary>
        /// 释放 ZeroMQ client 和当前 runner 持有的 HTTP client。
        /// </summary>
        public void Dispose()
        {
            if (Interlocked.Exchange(ref disposed, 1) != 0)
            {
                return;
            }

            zeroMqTriggerOperations.Dispose();

            if (ownsClient)
            {
                client.Dispose();
            }
        }

        /// <summary>
        /// 读取后端系统配置。
        /// </summary>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>系统配置响应。</returns>
        public async Task<SystemConfigResponse> GetSystemConfigResponseAsync(CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await client.GetSystemConfigResponseAsync(cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 获取同一 project 下的 Runtime 列表。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Runtime 列表。</returns>
        public async Task<IReadOnlyList<WorkflowAppRuntimeResponse>> ListProjectRuntimesAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.ListProjectRuntimesAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 获取 Runtime 当前状态。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Runtime 状态。</returns>
        public async Task<WorkflowAppRuntimeResponse> GetRuntimeAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.GetRuntimeAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 获取 Runtime 健康状态。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Runtime 健康状态。</returns>
        public async Task<WorkflowAppRuntimeResponse> GetRuntimeHealthAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.GetRuntimeHealthAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 启动 Runtime。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Runtime 状态。</returns>
        public async Task<WorkflowAppRuntimeResponse> StartRuntimeAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.StartRuntimeAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 停止 Runtime。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Runtime 状态。</returns>
        public async Task<WorkflowAppRuntimeResponse> StopRuntimeAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.StopRuntimeAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 重启 Runtime。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Runtime 状态。</returns>
        public async Task<WorkflowAppRuntimeResponse> RestartRuntimeAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.RestartRuntimeAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 获取 Runtime worker instance 列表。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Runtime worker instance 列表。</returns>
        public async Task<IReadOnlyList<WorkflowAppRuntimeInstanceResponse>> ListRuntimeInstancesAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.ListRuntimeInstancesAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 获取 Runtime 事件。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Runtime 事件列表。</returns>
        public async Task<IReadOnlyList<WorkflowAppRuntimeEventResponse>> GetRuntimeEventsAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.GetRuntimeEventsAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 执行 Runtime 调用链检查。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>调用链检查结果。</returns>
        public async Task<RuntimeFlowCheckResult> CheckRuntimeFlowAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.CheckRuntimeFlowAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 使用配置默认输入同步调用 Workflow App Runtime。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Workflow AppResult 响应。</returns>
        public async Task<WorkflowAppResultResponse> InvokeRuntimeAppResultAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.InvokeRuntimeAppResultAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 使用 base64 图片同步调用 Workflow App Runtime。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="imageBase64">图片 base64 内容。</param>
        /// <param name="mediaType">图片 media type。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Workflow AppResult 响应。</returns>
        public async Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageBase64Async(
            string runtimeName,
            string imageBase64,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.InvokeRuntimeAppResultWithImageBase64Async(
                runtimeName,
                imageBase64,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 使用图片 bytes 同步调用 Workflow App Runtime。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="imageBytes">图片二进制内容。</param>
        /// <param name="mediaType">图片 media type。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Workflow AppResult 响应。</returns>
        public async Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageBytesAsync(
            string runtimeName,
            byte[] imageBytes,
            string mediaType = "image/octet-stream",
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.InvokeRuntimeAppResultWithImageBytesAsync(
                runtimeName,
                imageBytes,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 使用图片文件同步调用 Workflow App Runtime。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="imagePath">图片文件路径。</param>
        /// <param name="mediaType">图片 media type；为空时按扩展名推断。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Workflow AppResult 响应。</returns>
        public async Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageFromFileAsync(
            string runtimeName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.InvokeRuntimeAppResultWithImageFromFileAsync(
                runtimeName,
                imagePath,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 使用配置默认输入创建异步 WorkflowRun。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>WorkflowRun 响应。</returns>
        public async Task<WorkflowRunResponse> RunRuntimeAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.RunRuntimeAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 使用 base64 图片创建异步 WorkflowRun。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="imageBase64">图片 base64 内容。</param>
        /// <param name="mediaType">图片 media type。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>WorkflowRun 响应。</returns>
        public async Task<WorkflowRunResponse> RunRuntimeWithImageBase64Async(
            string runtimeName,
            string imageBase64,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.RunRuntimeWithImageBase64Async(
                runtimeName,
                imageBase64,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 使用图片 bytes 创建异步 WorkflowRun。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="imageBytes">图片二进制内容。</param>
        /// <param name="mediaType">图片 media type。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>WorkflowRun 响应。</returns>
        public async Task<WorkflowRunResponse> RunRuntimeWithImageBytesAsync(
            string runtimeName,
            byte[] imageBytes,
            string mediaType = "image/octet-stream",
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.RunRuntimeWithImageBytesAsync(
                runtimeName,
                imageBytes,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 使用图片文件创建异步 WorkflowRun。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="imagePath">图片文件路径。</param>
        /// <param name="mediaType">图片 media type；为空时按扩展名推断。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>WorkflowRun 响应。</returns>
        public async Task<WorkflowRunResponse> RunRuntimeWithImageFromFileAsync(
            string runtimeName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.RunRuntimeWithImageFromFileAsync(
                runtimeName,
                imagePath,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 workflow_run_id 获取 WorkflowRun。
        /// </summary>
        /// <param name="workflowRunId">WorkflowRun id。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>WorkflowRun 响应。</returns>
        public async Task<WorkflowRunResponse> GetWorkflowRunAsync(
            string workflowRunId,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.GetWorkflowRunAsync(
                workflowRunId,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 workflow_run_id 取消 WorkflowRun。
        /// </summary>
        /// <param name="workflowRunId">WorkflowRun id。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>WorkflowRun 响应。</returns>
        public async Task<WorkflowRunResponse> CancelWorkflowRunAsync(
            string workflowRunId,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.CancelWorkflowRunAsync(
                workflowRunId,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 workflow_run_id 获取 WorkflowRun 事件。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="workflowRunId">WorkflowRun id。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>WorkflowRun 事件列表。</returns>
        public async Task<IReadOnlyList<WorkflowRunEventResponse>> GetWorkflowRunEventsAsync(
            string runtimeName,
            string workflowRunId,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await workflowRuntimeOperations.GetWorkflowRunEventsAsync(
                runtimeName,
                workflowRunId,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 获取运行状态。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>模型 deployment 运行状态。</returns>
        public async Task<ModelDeploymentRuntimeStatusResponse> GetModelDeploymentRuntimeStatusAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.GetModelDeploymentRuntimeStatusAsync(
                modelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 获取健康状态。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>模型 deployment 健康状态。</returns>
        public async Task<ModelDeploymentRuntimeHealthResponse> GetModelDeploymentRuntimeHealthAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.GetModelDeploymentRuntimeHealthAsync(
                modelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 启动运行时。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>启动后的模型运行时状态；非 2xx 响应抛出 AMVisionApiException。</returns>
        public async Task<ModelDeploymentRuntimeStatusResponse> StartModelDeploymentRuntimeAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.StartModelDeploymentRuntimeAsync(
                modelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 停止运行时。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>停止后的模型运行时状态；非 2xx 响应抛出 AMVisionApiException。</returns>
        public async Task<ModelDeploymentRuntimeStatusResponse> StopModelDeploymentRuntimeAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.StopModelDeploymentRuntimeAsync(
                modelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 重置运行时。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>重置后的模型运行时健康状态；非 2xx 响应抛出 AMVisionApiException。</returns>
        public async Task<ModelDeploymentRuntimeHealthResponse> ResetModelDeploymentRuntimeAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.ResetModelDeploymentRuntimeAsync(
                modelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 执行预热。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>预热后的模型运行时健康状态；非 2xx 响应抛出 AMVisionApiException。</returns>
        public async Task<ModelDeploymentRuntimeHealthResponse> WarmupModelDeploymentRuntimeAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.WarmupModelDeploymentRuntimeAsync(
                modelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用配置默认输入同步推理。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>模型同步推理响应。</returns>
        public async Task<ModelDeploymentInferenceResponse> InvokeConfiguredModelDeploymentAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.InvokeConfiguredModelDeploymentAsync(
                modelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用 base64 图片同步推理。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="imageBase64">图片 base64 内容。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>模型同步推理响应。</returns>
        public async Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithImageBase64Async(
            string modelDeploymentName,
            string imageBase64,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.InvokeModelDeploymentWithImageBase64Async(
                modelDeploymentName,
                imageBase64,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用图片 bytes 同步推理。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="imageBytes">图片二进制内容。</param>
        /// <param name="fileName">可选文件名。</param>
        /// <param name="mediaType">图片 media type；为空时按文件名推断或使用默认值。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>模型同步推理响应。</returns>
        public async Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithImageBytesAsync(
            string modelDeploymentName,
            byte[] imageBytes,
            string? fileName = null,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.InvokeModelDeploymentWithImageBytesAsync(
                modelDeploymentName,
                imageBytes,
                fileName,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用图片文件同步推理。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="imagePath">图片文件路径。</param>
        /// <param name="mediaType">图片 media type；为空时按扩展名推断。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>模型同步推理响应。</returns>
        public async Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithImageFromFileAsync(
            string modelDeploymentName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.InvokeModelDeploymentWithImageFromFileAsync(
                modelDeploymentName,
                imagePath,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用后端 input_file_id 同步推理。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="inputFileId">后端文件 id。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>模型同步推理响应。</returns>
        public async Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithInputFileIdAsync(
            string modelDeploymentName,
            string inputFileId,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.InvokeModelDeploymentWithInputFileIdAsync(
                modelDeploymentName,
                inputFileId,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用后端 input_uri 同步推理。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="inputUri">后端可读取的 input_uri。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>模型同步推理响应。</returns>
        public async Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithInputUriAsync(
            string modelDeploymentName,
            string inputUri,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.InvokeModelDeploymentWithInputUriAsync(
                modelDeploymentName,
                inputUri,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用配置默认输入创建异步推理任务。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>异步推理任务提交响应。</returns>
        public async Task<ModelInferenceTaskSubmissionResponse> RunConfiguredModelDeploymentAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.RunConfiguredModelDeploymentAsync(
                modelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用 base64 图片创建异步推理任务。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="imageBase64">图片 base64 内容。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>异步推理任务提交响应。</returns>
        public async Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithImageBase64Async(
            string modelDeploymentName,
            string imageBase64,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.RunModelDeploymentWithImageBase64Async(
                modelDeploymentName,
                imageBase64,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用图片 bytes 创建异步推理任务。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="imageBytes">图片二进制内容。</param>
        /// <param name="fileName">可选文件名。</param>
        /// <param name="mediaType">图片 media type；为空时按文件名推断或使用默认值。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>异步推理任务提交响应。</returns>
        public async Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithImageBytesAsync(
            string modelDeploymentName,
            byte[] imageBytes,
            string? fileName = null,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.RunModelDeploymentWithImageBytesAsync(
                modelDeploymentName,
                imageBytes,
                fileName,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用图片文件创建异步推理任务。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="imagePath">图片文件路径。</param>
        /// <param name="mediaType">图片 media type；为空时按扩展名推断。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>异步推理任务提交响应。</returns>
        public async Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithImageFromFileAsync(
            string modelDeploymentName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.RunModelDeploymentWithImageFromFileAsync(
                modelDeploymentName,
                imagePath,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用后端 input_file_id 创建异步推理任务。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="inputFileId">后端文件 id。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>异步推理任务提交响应。</returns>
        public async Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithInputFileIdAsync(
            string modelDeploymentName,
            string inputFileId,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.RunModelDeploymentWithInputFileIdAsync(
                modelDeploymentName,
                inputFileId,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 使用后端 input_uri 创建异步推理任务。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="inputUri">后端可读取的 input_uri。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>异步推理任务提交响应。</returns>
        public async Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithInputUriAsync(
            string modelDeploymentName,
            string inputUri,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.RunModelDeploymentWithInputUriAsync(
                modelDeploymentName,
                inputUri,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 获取异步推理任务详情。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="inferenceTaskId">异步推理任务 id。</param>
        /// <param name="includeEvents">是否包含任务事件。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>异步推理任务详情。</returns>
        public async Task<ModelInferenceTaskDetailResponse> GetModelInferenceTaskAsync(
            string modelDeploymentName,
            string inferenceTaskId,
            bool includeEvents = false,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.GetModelInferenceTaskAsync(
                modelDeploymentName,
                inferenceTaskId,
                includeEvents,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按模型 deployment key 获取异步推理任务结果。
        /// </summary>
        /// <param name="modelDeploymentName">模型 deployment 配置 key。</param>
        /// <param name="inferenceTaskId">异步推理任务 id。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>异步推理任务结果。</returns>
        public async Task<ModelInferenceTaskResultResponse> GetModelInferenceTaskResultAsync(
            string modelDeploymentName,
            string inferenceTaskId,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await modelDeploymentOperations.GetModelInferenceTaskResultAsync(
                modelDeploymentName,
                inferenceTaskId,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 获取 TriggerSource 列表。
        /// </summary>
        /// <param name="runtimeName">runtime 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 列表。</returns>
        public async Task<IReadOnlyList<WorkflowTriggerSourceResponse>> ListTriggerSourcesAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await triggerSourceOperations.ListTriggerSourcesAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 获取 TriggerSource。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 响应。</returns>
        public async Task<WorkflowTriggerSourceResponse> GetTriggerSourceAsync(
            string triggerSourceName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await triggerSourceOperations.GetTriggerSourceAsync(
                triggerSourceName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 启用 TriggerSource。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 响应。</returns>
        public async Task<WorkflowTriggerSourceResponse> EnableTriggerSourceAsync(
            string triggerSourceName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await triggerSourceOperations.EnableTriggerSourceAsync(
                triggerSourceName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 停用 TriggerSource。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 响应。</returns>
        public async Task<WorkflowTriggerSourceResponse> DisableTriggerSourceAsync(
            string triggerSourceName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await triggerSourceOperations.DisableTriggerSourceAsync(
                triggerSourceName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 获取 TriggerSource 健康状态。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 健康状态。</returns>
        public async Task<WorkflowTriggerSourceHealthResponse> GetTriggerSourceHealthAsync(
            string triggerSourceName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = await triggerSourceOperations.GetTriggerSourceHealthAsync(
                triggerSourceName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 发送通用事件 payload。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="payload">事件 payload。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeZeroMqEvent(
            string triggerSourceName,
            IDictionary<string, object?>? payload = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = zeroMqTriggerOperations.InvokeEvent(
                triggerSourceName,
                payload,
                cancellationToken);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 使用配置默认图片执行 ZeroMQ image bytes 触发。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeConfiguredZeroMqImage(
            string triggerSourceName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = zeroMqTriggerOperations.InvokeConfiguredImage(
                triggerSourceName,
                cancellationToken);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 使用图片文件执行 ZeroMQ image bytes 触发。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="imagePath">图片文件路径。</param>
        /// <param name="mediaType">图片 media type；为空时按扩展名推断。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeZeroMqImageFromFile(
            string triggerSourceName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = zeroMqTriggerOperations.InvokeImageFromFile(
                triggerSourceName,
                imagePath,
                mediaType,
                cancellationToken);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 使用图片 bytes 执行 ZeroMQ image bytes 触发。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="imageBytes">图片二进制内容。</param>
        /// <param name="mediaType">图片 media type。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeZeroMqImageBytes(
            string triggerSourceName,
            byte[] imageBytes,
            string mediaType = "image/octet-stream",
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = zeroMqTriggerOperations.InvokeImageBytes(
                triggerSourceName,
                imageBytes,
                mediaType,
                cancellationToken);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 使用 base64 图片执行 ZeroMQ image bytes 触发。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="imageBase64">图片 base64 内容。</param>
        /// <param name="mediaType">图片 media type。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeZeroMqImageBase64(
            string triggerSourceName,
            string imageBase64,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = zeroMqTriggerOperations.InvokeImageBase64(
                triggerSourceName,
                imageBase64,
                mediaType,
                cancellationToken);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 使用 BGR24 raw 数据触发。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="bgr24Bytes">BGR24 数据。</param>
        /// <param name="width">图片宽度。</param>
        /// <param name="height">图片高度。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeZeroMqBgr24(
            string triggerSourceName,
            byte[] bgr24Bytes,
            int width,
            int height,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = zeroMqTriggerOperations.InvokeBgr24(
                triggerSourceName,
                bgr24Bytes,
                width,
                height,
                cancellationToken);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 使用 Bitmap 转 BGR24 raw 数据触发。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="bitmap">待发送的 Bitmap。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeZeroMqBgr24FromBitmap(
            string triggerSourceName,
            Bitmap bitmap,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = zeroMqTriggerOperations.InvokeBgr24FromBitmap(
                triggerSourceName,
                bitmap,
                cancellationToken);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 使用图片文件转 BGR24 raw 数据触发。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="imagePath">图片文件路径。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeZeroMqBgr24FromFile(
            string triggerSourceName,
            string imagePath,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = zeroMqTriggerOperations.InvokeBgr24FromFile(
                triggerSourceName,
                imagePath,
                cancellationToken);
            return response;
        }

        /// <summary>
        /// 按 TriggerSource key 使用配置默认图片转 BGR24 raw 数据触发。
        /// </summary>
        /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeConfiguredZeroMqBgr24Image(
            string triggerSourceName,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var response = zeroMqTriggerOperations.InvokeConfiguredBgr24Image(
                triggerSourceName,
                cancellationToken);
            return response;
        }

        /// <summary>
        /// 按字典 key 排序为只读列表，便于 Console 和第三方界面显示。
        /// </summary>
        /// <param name="keys">配置 key 集合。</param>
        /// <returns>排序后的只读 key 列表。</returns>
        private static IReadOnlyList<string> SortKeys(IEnumerable<string> keys)
        {
            var sortedKeys = keys
                .OrderBy(key => key, StringComparer.OrdinalIgnoreCase)
                .ToList()
                .AsReadOnly();
            return sortedKeys;
        }

        /// <summary>
        /// 确认当前 runner 仍可使用。
        /// </summary>
        private void EnsureNotDisposed()
        {
            if (Volatile.Read(ref disposed) != 0)
            {
                throw new ObjectDisposedException(nameof(AMVisionOperationRunner));
            }
        }
    }
}

