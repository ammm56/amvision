using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision
{

    public sealed partial class AMVisionClient
    {
        /// <summary>
        /// 使用 expected_state CAS 归档一个 published Workflow App 版本。
        /// </summary>
        public async Task<AMVisionApiResponse> ArchiveWorkflowAppVersionAsync(
            string projectId,
            string applicationId,
            string workflowAppVersionId,
            WorkflowAppVersionStateTransitionRequest request,
            CancellationToken cancellationToken = default)
        {
            return await TransitionWorkflowAppVersionStateAsync(
                projectId,
                applicationId,
                workflowAppVersionId,
                "archive",
                "published",
                request,
                cancellationToken).ConfigureAwait(false);
        }

        /// <summary>
        /// 归档一个 Workflow App 版本，并返回 typed response。
        /// </summary>
        public async Task<WorkflowAppVersionResponse> ArchiveWorkflowAppVersionResponseAsync(
            string projectId,
            string applicationId,
            string workflowAppVersionId,
            WorkflowAppVersionStateTransitionRequest request,
            CancellationToken cancellationToken = default)
        {
            var response = await ArchiveWorkflowAppVersionAsync(
                projectId,
                applicationId,
                workflowAppVersionId,
                request,
                cancellationToken).ConfigureAwait(false);
            return ReadJson<WorkflowAppVersionResponse>(response);
        }

        /// <summary>
        /// 使用 expected_state CAS 恢复一个 archived Workflow App 版本。
        /// </summary>
        public async Task<AMVisionApiResponse> RestoreWorkflowAppVersionAsync(
            string projectId,
            string applicationId,
            string workflowAppVersionId,
            WorkflowAppVersionStateTransitionRequest request,
            CancellationToken cancellationToken = default)
        {
            return await TransitionWorkflowAppVersionStateAsync(
                projectId,
                applicationId,
                workflowAppVersionId,
                "restore",
                "archived",
                request,
                cancellationToken).ConfigureAwait(false);
        }

        /// <summary>
        /// 恢复一个 Workflow App 版本，并返回 typed response。
        /// </summary>
        public async Task<WorkflowAppVersionResponse> RestoreWorkflowAppVersionResponseAsync(
            string projectId,
            string applicationId,
            string workflowAppVersionId,
            WorkflowAppVersionStateTransitionRequest request,
            CancellationToken cancellationToken = default)
        {
            var response = await RestoreWorkflowAppVersionAsync(
                projectId,
                applicationId,
                workflowAppVersionId,
                request,
                cancellationToken).ConfigureAwait(false);
            return ReadJson<WorkflowAppVersionResponse>(response);
        }

        private async Task<AMVisionApiResponse> TransitionWorkflowAppVersionStateAsync(
            string projectId,
            string applicationId,
            string workflowAppVersionId,
            string transition,
            string expectedState,
            WorkflowAppVersionStateTransitionRequest request,
            CancellationToken cancellationToken)
        {
            if (request == null) throw new ArgumentNullException(nameof(request));
            request.Validate(expectedState);
            var requestPath = string.Format(
                "{0}/projects/{1}/applications/{2}/versions/{3}/{4}",
                WorkflowApiPrefix,
                EncodePathSegment(RequireId(projectId, nameof(projectId))),
                EncodePathSegment(RequireId(applicationId, nameof(applicationId))),
                EncodePathSegment(RequireId(workflowAppVersionId, nameof(workflowAppVersionId))),
                transition);
            return await SendAsync(
                HttpMethod.Post,
                requestPath,
                SerializeJson(request),
                cancellationToken).ConfigureAwait(false);
        }
    }
}
