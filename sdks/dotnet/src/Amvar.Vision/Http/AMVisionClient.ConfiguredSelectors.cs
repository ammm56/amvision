using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision.Configuration;

namespace Amvar.Vision
{
    /// <summary>
    /// 明确区分配置 name 与后端资源 id 的高层调用入口。
    /// </summary>
    public sealed partial class AMVisionClient
    {
        public Task<WorkflowAppResultResponse> InvokeConfiguredWorkflowRuntimeByNameAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            return InvokeConfiguredWorkflowRuntimeAsync(runtimeName, cancellationToken);
        }

        public Task<WorkflowAppResultResponse> InvokeConfiguredWorkflowRuntimeByIdAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var runtime = RequireConfigurationCatalog().GetRuntimeById(workflowRuntimeId);
            return InvokeConfiguredWorkflowRuntimeAsync(runtime.Runtime.Name, cancellationToken);
        }

        public Task<WorkflowAppResultResponse> InvokeConfiguredWorkflowRuntimeWithImageFileByNameAsync(
            string runtimeName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return InvokeConfiguredWorkflowRuntimeWithImageFileAsync(
                runtimeName, imagePath, mediaType, cancellationToken);
        }

        public Task<WorkflowAppResultResponse> InvokeConfiguredWorkflowRuntimeWithImageFileByIdAsync(
            string workflowRuntimeId,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            var runtime = RequireConfigurationCatalog().GetRuntimeById(workflowRuntimeId);
            return InvokeConfiguredWorkflowRuntimeWithImageFileAsync(
                runtime.Runtime.Name, imagePath, mediaType, cancellationToken);
        }

        public Task<ModelDeploymentInferenceResponse> InvokeConfiguredModelDeploymentByNameAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            return InvokeConfiguredModelDeploymentAsync(modelDeploymentName, cancellationToken);
        }

        public Task<ModelDeploymentInferenceResponse> InvokeConfiguredModelDeploymentByIdAsync(
            string deploymentInstanceId,
            CancellationToken cancellationToken = default)
        {
            var deployment = RequireConfigurationCatalog().GetModelDeploymentById(
                deploymentInstanceId, ModelDeploymentRuntimeModes.Sync);
            return InvokeConfiguredModelDeploymentAsync(
                deployment.ModelDeployment.Name, cancellationToken);
        }

        public Task<ModelDeploymentInferenceResponse> InvokeConfiguredModelDeploymentWithImageFileByNameAsync(
            string modelDeploymentName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return InvokeConfiguredModelDeploymentWithImageFileAsync(
                modelDeploymentName, imagePath, mediaType, cancellationToken);
        }

        public Task<ModelDeploymentInferenceResponse> InvokeConfiguredModelDeploymentWithImageFileByIdAsync(
            string deploymentInstanceId,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            var deployment = RequireConfigurationCatalog().GetModelDeploymentById(
                deploymentInstanceId, ModelDeploymentRuntimeModes.Sync);
            return InvokeConfiguredModelDeploymentWithImageFileAsync(
                deployment.ModelDeployment.Name, imagePath, mediaType, cancellationToken);
        }

        public Task<ModelInferenceTaskSubmissionResponse> RunConfiguredModelDeploymentByNameAsync(
            string modelDeploymentName,
            CancellationToken cancellationToken = default)
        {
            return RunConfiguredModelDeploymentAsync(modelDeploymentName, cancellationToken);
        }

        public Task<ModelInferenceTaskSubmissionResponse> RunConfiguredModelDeploymentByIdAsync(
            string deploymentInstanceId,
            CancellationToken cancellationToken = default)
        {
            var deployment = RequireConfigurationCatalog().GetModelDeploymentById(
                deploymentInstanceId, ModelDeploymentRuntimeModes.Async);
            return RunConfiguredModelDeploymentAsync(
                deployment.ModelDeployment.Name, cancellationToken);
        }

        public Task<ModelInferenceTaskSubmissionResponse> RunConfiguredModelDeploymentWithImageFileByNameAsync(
            string modelDeploymentName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return RunConfiguredModelDeploymentWithImageFileAsync(
                modelDeploymentName, imagePath, mediaType, cancellationToken);
        }

        public Task<ModelInferenceTaskSubmissionResponse> RunConfiguredModelDeploymentWithImageFileByIdAsync(
            string deploymentInstanceId,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            var deployment = RequireConfigurationCatalog().GetModelDeploymentById(
                deploymentInstanceId, ModelDeploymentRuntimeModes.Async);
            return RunConfiguredModelDeploymentWithImageFileAsync(
                deployment.ModelDeployment.Name, imagePath, mediaType, cancellationToken);
        }

        public TriggerResult InvokeConfiguredZeroMqImageByName(
            string triggerSourceName,
            CancellationToken cancellationToken = default)
        {
            return InvokeConfiguredZeroMqImage(triggerSourceName, cancellationToken);
        }

        public TriggerResult InvokeConfiguredZeroMqImageById(
            string triggerSourceId,
            CancellationToken cancellationToken = default)
        {
            var trigger = RequireConfigurationCatalog().GetTriggerSourceById(triggerSourceId);
            return InvokeConfiguredZeroMqImage(trigger.TriggerSource.Name, cancellationToken);
        }

        public TriggerResult InvokeConfiguredZeroMqImageFileByName(
            string triggerSourceName,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return InvokeConfiguredZeroMqImageFile(
                triggerSourceName, imagePath, mediaType, cancellationToken);
        }

        public TriggerResult InvokeConfiguredZeroMqImageFileById(
            string triggerSourceId,
            string imagePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            var trigger = RequireConfigurationCatalog().GetTriggerSourceById(triggerSourceId);
            return InvokeConfiguredZeroMqImageFile(
                trigger.TriggerSource.Name, imagePath, mediaType, cancellationToken);
        }
    }
}
