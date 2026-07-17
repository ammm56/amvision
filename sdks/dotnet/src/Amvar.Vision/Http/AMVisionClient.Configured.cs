using System;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision.Configuration;
using Amvar.Vision.ModelDeployment;
using Amvar.Vision.Runtime;
using Amvar.Vision.Tools;
using Amvar.Vision.TriggerSource.ZeroMQ;

namespace Amvar.Vision
{
    /// <summary>
    /// 基于 Config/config*.json 的高层 SDK 调用入口。
    /// </summary>
    public sealed partial class AMVisionClient
    {
        /// <summary>
        /// 从默认 Config 目录加载所有 config*.json，并创建可按 key 调用的 SDK client。
        /// </summary>
        /// <returns>已经加载配置的 SDK client。</returns>
        public static AMVisionClient CreateFromConfig()
        {
            var catalog = WorkflowConfigLoader.LoadDefault();
            var client = CreateFromCatalog(catalog);
            return client;
        }

        /// <summary>
        /// 从指定 Config 目录加载所有 config*.json，并创建可按 key 调用的 SDK client。
        /// </summary>
        /// <param name="configDirectory">Config 目录路径。</param>
        /// <returns>已经加载配置的 SDK client。</returns>
        public static AMVisionClient CreateFromConfigDirectory(string configDirectory)
        {
            var catalog = WorkflowConfigLoader.LoadDirectory(configDirectory);
            var client = CreateFromCatalog(catalog);
            return client;
        }

        /// <summary>
        /// 使用已加载的配置索引创建 SDK client。
        /// </summary>
        /// <param name="catalog">配置索引。</param>
        /// <returns>已经绑定配置索引的 SDK client。</returns>
        internal static AMVisionClient CreateFromCatalog(WorkflowConfigurationCatalog catalog)
        {
            if (catalog == null)
            {
                throw new ArgumentNullException(nameof(catalog));
            }

            var options = BuildOptions(catalog.DefaultBackend);
            var client = new AMVisionClient(options, catalog);
            return client;
        }

        /// <summary>
        /// 从 backend 配置构建 HTTP client 参数。
        /// </summary>
        /// <param name="backend">backend 配置。</param>
        /// <returns>HTTP 管理 API 参数。</returns>
        private static AMVisionClientOptions BuildOptions(BackendConfig backend)
        {
            if (backend == null)
            {
                throw new ArgumentNullException(nameof(backend));
            }

            var options = new AMVisionClientOptions
            {
                BaseApiUrl = backend.BaseApiUrl,
                AccessToken = backend.AccessToken,
                Timeout = TimeSpan.FromSeconds(backend.HttpTimeoutSeconds)
            };
            return options;
        }

        /// <summary>
        /// 获取当前 client 持有的配置索引。
        /// </summary>
        /// <returns>配置索引。</returns>
        internal WorkflowConfigurationCatalog RequireConfigurationCatalog()
        {
            if (configurationCatalog == null)
            {
                throw new InvalidOperationException(
                    "This AMVisionClient has not loaded Config/config*.json. Create the client with AMVisionClient.CreateFromConfig() or CreateFromConfigDirectory().");
            }

            return configurationCatalog;
        }

        /// <summary>
        /// 按 runtime key 使用配置默认输入同步调用 Workflow App Runtime。
        /// </summary>
        /// <param name="runtimeName">Config/config*.json 中 runtime.name 对应的 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Workflow AppResult 响应。</returns>
        public async Task<WorkflowAppResultResponse> InvokeConfiguredWorkflowRuntimeAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            var catalog = RequireConfigurationCatalog();
            var operations = new WorkflowRuntimeOperations(this, catalog);
            var response = await operations.InvokeRuntimeAppResultAsync(
                runtimeName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 runtime key 使用调用方传入的图片文件同步调用 Workflow App Runtime。
        /// </summary>
        /// <param name="runtimeName">Config/config*.json 中 runtime.name 对应的 key。</param>
        /// <param name="imagePath">图片文件路径。</param>
        /// <param name="mediaType">可选 media type；为空时按文件扩展名推断。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>Workflow AppResult 响应。</returns>
        public async Task<WorkflowAppResultResponse> InvokeConfiguredWorkflowRuntimeWithImageFileAsync(
            string runtimeName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            var catalog = RequireConfigurationCatalog();
            var operations = new WorkflowRuntimeOperations(this, catalog);
            var response = await operations.InvokeRuntimeAppResultWithImageFromFileAsync(
                runtimeName,
                imagePath,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 model deployment key 使用配置默认输入执行同步推理。
        /// </summary>
        /// <param name="modelDeploymentName">Config/config*.json 中 model_deployments[].name 对应的 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>模型同步推理响应。</returns>
        public async Task<ModelDeploymentInferenceResponse> InvokeConfiguredModelDeploymentAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            var catalog = RequireConfigurationCatalog();
            var operations = new ModelDeploymentOperations(this, catalog);
            var response = await operations.InvokeConfiguredModelDeploymentAsync(
                modelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 model deployment key 使用调用方传入的图片文件执行同步推理。
        /// </summary>
        /// <param name="modelDeploymentName">Config/config*.json 中 model_deployments[].name 对应的 key。</param>
        /// <param name="imagePath">图片文件路径。</param>
        /// <param name="mediaType">可选 media type；为空时按文件扩展名推断。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>模型同步推理响应。</returns>
        public async Task<ModelDeploymentInferenceResponse> InvokeConfiguredModelDeploymentWithImageFileAsync(
            string modelDeploymentName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            var catalog = RequireConfigurationCatalog();
            var operations = new ModelDeploymentOperations(this, catalog);
            var response = await operations.InvokeModelDeploymentWithImageFromFileAsync(
                modelDeploymentName,
                imagePath,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 model deployment key 使用配置默认输入创建异步推理任务。
        /// </summary>
        /// <param name="modelDeploymentName">Config/config*.json 中 model_deployments[].name 对应的 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>异步推理任务提交响应。</returns>
        public async Task<ModelInferenceTaskSubmissionResponse> RunConfiguredModelDeploymentAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            var catalog = RequireConfigurationCatalog();
            var operations = new ModelDeploymentOperations(this, catalog);
            var response = await operations.RunConfiguredModelDeploymentAsync(
                modelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 model deployment key 使用调用方传入的图片文件创建异步推理任务。
        /// </summary>
        /// <param name="modelDeploymentName">Config/config*.json 中 model_deployments[].name 对应的 key。</param>
        /// <param name="imagePath">图片文件路径。</param>
        /// <param name="mediaType">可选 media type；为空时按文件扩展名推断。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>异步推理任务提交响应。</returns>
        public async Task<ModelInferenceTaskSubmissionResponse> RunConfiguredModelDeploymentWithImageFileAsync(
            string modelDeploymentName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            var catalog = RequireConfigurationCatalog();
            var operations = new ModelDeploymentOperations(this, catalog);
            var response = await operations.RunModelDeploymentWithImageFromFileAsync(
                modelDeploymentName,
                imagePath,
                mediaType,
                cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 按 trigger key 使用配置默认图片执行 ZeroMQ image bytes 触发。
        /// </summary>
        /// <param name="triggerSourceName">Config/config*.json 中 trigger_sources[].name 对应的 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeConfiguredZeroMqImage(
            string triggerSourceName,
            CancellationToken cancellationToken = default)
        {
            var catalog = RequireConfigurationCatalog();
            using (var operations = new ZeroMqTriggerOperations(catalog))
            {
                var response = operations.InvokeConfiguredImage(
                    triggerSourceName,
                    cancellationToken);
                return response;
            }
        }

        /// <summary>
        /// 按 trigger key 使用调用方传入的图片文件执行 ZeroMQ image bytes 触发。
        /// </summary>
        /// <param name="triggerSourceName">Config/config*.json 中 trigger_sources[].name 对应的 key。</param>
        /// <param name="imagePath">图片文件路径。</param>
        /// <param name="mediaType">可选 media type；为空时按文件扩展名推断。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeConfiguredZeroMqImageFile(
            string triggerSourceName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            var catalog = RequireConfigurationCatalog();
            using (var operations = new ZeroMqTriggerOperations(catalog))
            {
                var response = operations.InvokeImageFromFile(
                    triggerSourceName,
                    imagePath,
                    mediaType,
                    cancellationToken);
                return response;
            }
        }

        /// <summary>
        /// 按 trigger key 使用配置默认图片执行 ZeroMQ BGR24 raw 触发。
        /// </summary>
        /// <param name="triggerSourceName">Config/config*.json 中 trigger_sources[].name 对应的 key。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeConfiguredZeroMqBgr24Image(
            string triggerSourceName,
            CancellationToken cancellationToken = default)
        {
            var catalog = RequireConfigurationCatalog();
            using (var operations = new ZeroMqTriggerOperations(catalog))
            {
                var response = operations.InvokeConfiguredBgr24Image(
                    triggerSourceName,
                    cancellationToken);
                return response;
            }
        }

        /// <summary>
        /// 按 trigger key 使用调用方传入的图片文件执行 ZeroMQ BGR24 raw 触发。
        /// </summary>
        /// <param name="triggerSourceName">Config/config*.json 中 trigger_sources[].name 对应的 key。</param>
        /// <param name="imagePath">图片文件路径。</param>
        /// <param name="cancellationToken">取消信号。</param>
        /// <returns>TriggerSource 调用结果。</returns>
        public TriggerResult InvokeConfiguredZeroMqBgr24ImageFile(
            string triggerSourceName,
            string imagePath,
            CancellationToken cancellationToken = default)
        {
            var catalog = RequireConfigurationCatalog();
            using (var operations = new ZeroMqTriggerOperations(catalog))
            {
                var response = operations.InvokeBgr24FromFile(
                    triggerSourceName,
                    imagePath,
                    cancellationToken);
                return response;
            }
        }
    }
}
