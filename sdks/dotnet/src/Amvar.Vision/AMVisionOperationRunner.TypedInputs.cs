using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision
{
    public sealed partial class AMVisionOperationRunner
    {
        /// <summary>按 runtime 配置中的固定 App Contract 创建 HTTP Runtime 请求 Builder。</summary>
        public WorkflowRequestBuilder CreateWorkflowRequestBuilder(string runtimeName)
        {
            EnsureNotDisposed();
            var configured = catalog.GetRuntime(runtimeName);
            var contract = configured.Runtime.PublicContract
                ?? throw new InvalidOperationException(
                    "Runtime config does not contain a fixed public_contract.");
            return new WorkflowRequestBuilder(contract);
        }

        /// <summary>按 TriggerSource 固定 mapping 创建 JSON/文本 Trigger inputs Builder。</summary>
        public WorkflowTriggerInputsBuilder CreateWorkflowTriggerInputsBuilder(
            string triggerSourceName)
        {
            EnsureNotDisposed();
            var configured = catalog.GetTriggerSource(triggerSourceName);
            var contract = configured.Runtime.PublicContract
                ?? throw new InvalidOperationException(
                    "Runtime config does not contain a fixed public_contract.");
            var sourcePaths = configured.TriggerSource.InputBindingMapping
                .Where(pair => !string.IsNullOrWhiteSpace(pair.Value.Source))
                .ToDictionary(
                    pair => pair.Key,
                    pair => pair.Value.Source!,
                    StringComparer.Ordinal);
            return new WorkflowTriggerInputsBuilder(contract, sourcePaths);
        }

        /// <summary>按 runtime key 使用显式 JSON 请求同步调用并返回 AppResult。</summary>
        public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultAsync(
            string runtimeName,
            WorkflowRuntimeInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var runtimeId = catalog.GetRuntime(runtimeName).Runtime.WorkflowRuntimeId;
            return client.InvokeWorkflowAppRuntimeAppResultResponseAsync(
                runtimeId,
                request ?? throw new ArgumentNullException(nameof(request)),
                cancellationToken);
        }

        /// <summary>按 runtime key 使用显式 multipart 请求同步调用并返回 AppResult。</summary>
        public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultAsync(
            string runtimeName,
            WorkflowRuntimeMultipartInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            var runtimeId = catalog.GetRuntime(runtimeName).Runtime.WorkflowRuntimeId;
            return client.InvokeWorkflowAppRuntimeUploadAppResultResponseAsync(
                runtimeId,
                request ?? throw new ArgumentNullException(nameof(request)),
                cancellationToken);
        }
    }
}
