using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision.Configuration;
using Amvar.Vision.Runtime;

namespace Amvar.Vision
{
    /// <summary>
    /// 通过 workflow_runtime_id 精确调用 runtime 的入口。
    /// 不带 ById 后缀的原方法继续明确接收配置 name。
    /// </summary>
    public sealed partial class AMVisionOperationRunner
    {
        private string GetRuntimeNameById(string workflowRuntimeId)
        {
            return catalog.GetRuntimeById(workflowRuntimeId).Runtime.Name;
        }

        public Task<IReadOnlyList<WorkflowAppRuntimeResponse>> ListProjectRuntimesByIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return ListProjectRuntimesAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<WorkflowAppRuntimeResponse> GetRuntimeByIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return GetRuntimeAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<WorkflowAppRuntimeResponse> GetRuntimeHealthByIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return GetRuntimeHealthAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<WorkflowAppRuntimeResponse> StartRuntimeByIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return StartRuntimeAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<WorkflowAppRuntimeResponse> StopRuntimeByIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return StopRuntimeAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<WorkflowAppRuntimeResponse> RestartRuntimeByIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return RestartRuntimeAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<IReadOnlyList<WorkflowAppRuntimeInstanceResponse>> ListRuntimeInstancesByIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return ListRuntimeInstancesAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<IReadOnlyList<WorkflowAppRuntimeEventResponse>> GetRuntimeEventsByIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return GetRuntimeEventsAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<RuntimeFlowCheckResult> CheckRuntimeFlowByIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return CheckRuntimeFlowAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultByIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return InvokeRuntimeAppResultAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageBase64ByIdAsync(
            string workflowRuntimeId, string imageBase64, string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return InvokeRuntimeAppResultWithImageBase64Async(
                GetRuntimeNameById(workflowRuntimeId), imageBase64, mediaType, cancellationToken);
        }

        public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageBytesByIdAsync(
            string workflowRuntimeId, byte[] imageBytes,
            string mediaType = "image/octet-stream", CancellationToken cancellationToken = default)
        {
            return InvokeRuntimeAppResultWithImageBytesAsync(
                GetRuntimeNameById(workflowRuntimeId), imageBytes, mediaType, cancellationToken);
        }

        public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageFromFileByIdAsync(
            string workflowRuntimeId, string imagePath, string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return InvokeRuntimeAppResultWithImageFromFileAsync(
                GetRuntimeNameById(workflowRuntimeId), imagePath, mediaType, cancellationToken);
        }

        public Task<WorkflowRunResponse> RunRuntimeByIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return RunRuntimeAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<WorkflowRunResponse> RunRuntimeWithImageBase64ByIdAsync(
            string workflowRuntimeId, string imageBase64, string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return RunRuntimeWithImageBase64Async(
                GetRuntimeNameById(workflowRuntimeId), imageBase64, mediaType, cancellationToken);
        }

        public Task<WorkflowRunResponse> RunRuntimeWithImageBytesByIdAsync(
            string workflowRuntimeId, byte[] imageBytes,
            string mediaType = "image/octet-stream", CancellationToken cancellationToken = default)
        {
            return RunRuntimeWithImageBytesAsync(
                GetRuntimeNameById(workflowRuntimeId), imageBytes, mediaType, cancellationToken);
        }

        public Task<WorkflowRunResponse> RunRuntimeWithImageFromFileByIdAsync(
            string workflowRuntimeId, string imagePath, string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return RunRuntimeWithImageFromFileAsync(
                GetRuntimeNameById(workflowRuntimeId), imagePath, mediaType, cancellationToken);
        }

        public Task<IReadOnlyList<WorkflowRunEventResponse>> GetWorkflowRunEventsByRuntimeIdAsync(
            string workflowRuntimeId, string workflowRunId,
            CancellationToken cancellationToken = default)
        {
            return GetWorkflowRunEventsAsync(
                GetRuntimeNameById(workflowRuntimeId), workflowRunId, cancellationToken);
        }
    }
}
