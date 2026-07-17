using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision.Configuration;

namespace Amvar.Vision
{
    /// <summary>
    /// 明确区分配置 name 与后端资源 id 的 runner 调用入口。
    /// </summary>
    public sealed partial class AMVisionOperationRunner
    {
        public Task<WorkflowAppRuntimeResponse> GetRuntimeByNameAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            return GetRuntimeAsync(runtimeName, cancellationToken);
        }

        public Task<WorkflowAppRuntimeResponse> GetRuntimeByIdAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var runtime = catalog.GetRuntimeById(workflowRuntimeId);
            return GetRuntimeAsync(runtime.Runtime.Name, cancellationToken);
        }

        public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultByNameAsync(
            string runtimeName,
            CancellationToken cancellationToken = default)
        {
            return InvokeRuntimeAppResultAsync(runtimeName, cancellationToken);
        }

        public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultByIdAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var runtime = catalog.GetRuntimeById(workflowRuntimeId);
            return InvokeRuntimeAppResultAsync(runtime.Runtime.Name, cancellationToken);
        }

        public Task<WorkflowTriggerSourceResponse> GetTriggerSourceByNameAsync(
            string triggerSourceName,
            CancellationToken cancellationToken = default)
        {
            return GetTriggerSourceAsync(triggerSourceName, cancellationToken);
        }

        public Task<WorkflowTriggerSourceResponse> GetTriggerSourceByIdAsync(
            string triggerSourceId,
            CancellationToken cancellationToken = default)
        {
            var trigger = catalog.GetTriggerSourceById(triggerSourceId);
            return GetTriggerSourceAsync(trigger.TriggerSource.Name, cancellationToken);
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
            var trigger = catalog.GetTriggerSourceById(triggerSourceId);
            return InvokeConfiguredZeroMqImage(trigger.TriggerSource.Name, cancellationToken);
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
            var deployment = catalog.GetModelDeploymentById(
                deploymentInstanceId, ModelDeploymentRuntimeModes.Sync);
            return InvokeConfiguredModelDeploymentAsync(
                deployment.ModelDeployment.Name, cancellationToken);
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
            var deployment = catalog.GetModelDeploymentById(
                deploymentInstanceId, ModelDeploymentRuntimeModes.Async);
            return RunConfiguredModelDeploymentAsync(
                deployment.ModelDeployment.Name, cancellationToken);
        }
    }
}
