using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision.Configuration;

namespace Amvar.Vision
{
    /// <summary>
    /// 通过 deployment_instance_id 精确调用模型 deployment 的入口。
    /// </summary>
    public sealed partial class AMVisionOperationRunner
    {
        private string GetModelDeploymentNameById(string deploymentInstanceId, string runtimeMode)
        {
            return catalog.GetModelDeploymentById(deploymentInstanceId, runtimeMode)
                .ModelDeployment.Name;
        }

        public Task<ModelDeploymentRuntimeStatusResponse> GetModelDeploymentRuntimeStatusByIdAsync(
            string deploymentInstanceId, string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            return GetModelDeploymentRuntimeStatusAsync(
                GetModelDeploymentNameById(deploymentInstanceId, runtimeMode), cancellationToken);
        }

        public Task<ModelDeploymentRuntimeHealthResponse> GetModelDeploymentRuntimeHealthByIdAsync(
            string deploymentInstanceId, string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            return GetModelDeploymentRuntimeHealthAsync(
                GetModelDeploymentNameById(deploymentInstanceId, runtimeMode), cancellationToken);
        }

        public Task<ModelDeploymentRuntimeStatusResponse> StartModelDeploymentRuntimeByIdAsync(
            string deploymentInstanceId, string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            return StartModelDeploymentRuntimeAsync(
                GetModelDeploymentNameById(deploymentInstanceId, runtimeMode), cancellationToken);
        }

        public Task<ModelDeploymentRuntimeStatusResponse> StopModelDeploymentRuntimeByIdAsync(
            string deploymentInstanceId, string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            return StopModelDeploymentRuntimeAsync(
                GetModelDeploymentNameById(deploymentInstanceId, runtimeMode), cancellationToken);
        }

        public Task<ModelDeploymentRuntimeHealthResponse> ResetModelDeploymentRuntimeByIdAsync(
            string deploymentInstanceId, string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            return ResetModelDeploymentRuntimeAsync(
                GetModelDeploymentNameById(deploymentInstanceId, runtimeMode), cancellationToken);
        }

        public Task<ModelDeploymentRuntimeHealthResponse> WarmupModelDeploymentRuntimeByIdAsync(
            string deploymentInstanceId, string runtimeMode,
            CancellationToken cancellationToken = default)
        {
            return WarmupModelDeploymentRuntimeAsync(
                GetModelDeploymentNameById(deploymentInstanceId, runtimeMode), cancellationToken);
        }

        public Task<ModelDeploymentInferenceResponse> InvokeConfiguredModelDeploymentByIdAsync(
            string deploymentInstanceId, CancellationToken cancellationToken = default)
        {
            return InvokeConfiguredModelDeploymentAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Sync),
                cancellationToken);
        }

        public Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithImageBase64ByIdAsync(
            string deploymentInstanceId, string imageBase64,
            CancellationToken cancellationToken = default)
        {
            return InvokeModelDeploymentWithImageBase64Async(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Sync),
                imageBase64, cancellationToken);
        }

        public Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithImageBytesByIdAsync(
            string deploymentInstanceId, byte[] imageBytes, string? fileName = null,
            string? mediaType = null, CancellationToken cancellationToken = default)
        {
            return InvokeModelDeploymentWithImageBytesAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Sync),
                imageBytes, fileName, mediaType, cancellationToken);
        }

        public Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithImageFromFileByIdAsync(
            string deploymentInstanceId, string imagePath, string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return InvokeModelDeploymentWithImageFromFileAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Sync),
                imagePath, mediaType, cancellationToken);
        }

        public Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithInputFileIdByIdAsync(
            string deploymentInstanceId, string inputFileId,
            CancellationToken cancellationToken = default)
        {
            return InvokeModelDeploymentWithInputFileIdAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Sync),
                inputFileId, cancellationToken);
        }

        public Task<ModelDeploymentInferenceResponse> InvokeModelDeploymentWithInputUriByIdAsync(
            string deploymentInstanceId, string inputUri,
            CancellationToken cancellationToken = default)
        {
            return InvokeModelDeploymentWithInputUriAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Sync),
                inputUri, cancellationToken);
        }

        public Task<ModelInferenceTaskSubmissionResponse> RunConfiguredModelDeploymentByIdAsync(
            string deploymentInstanceId, CancellationToken cancellationToken = default)
        {
            return RunConfiguredModelDeploymentAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Async),
                cancellationToken);
        }

        public Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithImageBase64ByIdAsync(
            string deploymentInstanceId, string imageBase64,
            CancellationToken cancellationToken = default)
        {
            return RunModelDeploymentWithImageBase64Async(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Async),
                imageBase64, cancellationToken);
        }

        public Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithImageBytesByIdAsync(
            string deploymentInstanceId, byte[] imageBytes, string? fileName = null,
            string? mediaType = null, CancellationToken cancellationToken = default)
        {
            return RunModelDeploymentWithImageBytesAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Async),
                imageBytes, fileName, mediaType, cancellationToken);
        }

        public Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithImageFromFileByIdAsync(
            string deploymentInstanceId, string imagePath, string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return RunModelDeploymentWithImageFromFileAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Async),
                imagePath, mediaType, cancellationToken);
        }

        public Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithInputFileIdByIdAsync(
            string deploymentInstanceId, string inputFileId,
            CancellationToken cancellationToken = default)
        {
            return RunModelDeploymentWithInputFileIdAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Async),
                inputFileId, cancellationToken);
        }

        public Task<ModelInferenceTaskSubmissionResponse> RunModelDeploymentWithInputUriByIdAsync(
            string deploymentInstanceId, string inputUri,
            CancellationToken cancellationToken = default)
        {
            return RunModelDeploymentWithInputUriAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Async),
                inputUri, cancellationToken);
        }

        public Task<ModelInferenceTaskDetailResponse> GetModelInferenceTaskByIdAsync(
            string deploymentInstanceId, string inferenceTaskId, bool includeEvents = false,
            CancellationToken cancellationToken = default)
        {
            return GetModelInferenceTaskAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Async),
                inferenceTaskId, includeEvents, cancellationToken);
        }

        public Task<ModelInferenceTaskResultResponse> GetModelInferenceTaskResultByIdAsync(
            string deploymentInstanceId, string inferenceTaskId,
            CancellationToken cancellationToken = default)
        {
            return GetModelInferenceTaskResultAsync(
                GetModelDeploymentNameById(deploymentInstanceId, ModelDeploymentRuntimeModes.Async),
                inferenceTaskId, cancellationToken);
        }
    }
}
