using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision
{

    public sealed partial class AMVisionClient
    {
        /// <summary>
        /// 按 Project id 列出 TriggerSource。
        /// </summary>
        public async Task<AMVisionApiResponse> ListTriggerSourcesAsync(
            string projectId,
            int offset = 0,
            int limit = 100,
            CancellationToken cancellationToken = default)
        {
            var path = WithQuery(
                $"{WorkflowApiPrefix}/trigger-sources",
                ("project_id", RequireId(projectId, nameof(projectId))),
                ("offset", offset),
                ("limit", limit));
            var apiResponse = await SendAsync(
                HttpMethod.Get,
                path,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 按 Project id 列出 TriggerSource，并返回 typed responses。
        /// </summary>
        public async Task<IReadOnlyList<WorkflowTriggerSourceResponse>> ListTriggerSourceResponsesAsync(
            string projectId,
            int offset = 0,
            int limit = 100,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await ListTriggerSourcesAsync(projectId, offset, limit, cancellationToken).ConfigureAwait(false);
            var typedResponses = ReadJsonList<WorkflowTriggerSourceResponse>(apiResponse);
            return typedResponses;
        }

        /// <summary>
        /// 读取一条 TriggerSource。
        /// </summary>
        public async Task<AMVisionApiResponse> GetTriggerSourceAsync(
            string triggerSourceId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/trigger-sources/{EncodePathSegment(RequireId(triggerSourceId, nameof(triggerSourceId)))}";
            var apiResponse = await SendAsync(
                HttpMethod.Get,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 读取一条 TriggerSource，并返回 typed response。
        /// </summary>
        public async Task<WorkflowTriggerSourceResponse> GetTriggerSourceResponseAsync(
            string triggerSourceId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetTriggerSourceAsync(triggerSourceId, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowTriggerSourceResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 创建一条 TriggerSource。
        /// </summary>
        public async Task<AMVisionApiResponse> CreateTriggerSourceAsync(
            WorkflowTriggerSourceCreateRequest request,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/trigger-sources";
            var requestBody = SerializeJson(request);
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                requestPath,
                requestBody,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 创建一条 TriggerSource，并返回 typed response。
        /// </summary>
        public async Task<WorkflowTriggerSourceResponse> CreateTriggerSourceResponseAsync(
            WorkflowTriggerSourceCreateRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await CreateTriggerSourceAsync(request, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowTriggerSourceResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 启用一条 TriggerSource。
        /// </summary>
        public async Task<AMVisionApiResponse> EnableTriggerSourceAsync(
            string triggerSourceId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/trigger-sources/{EncodePathSegment(RequireId(triggerSourceId, nameof(triggerSourceId)))}/enable";
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 启用一条 TriggerSource，并返回 typed response。
        /// </summary>
        public async Task<WorkflowTriggerSourceResponse> EnableTriggerSourceResponseAsync(
            string triggerSourceId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await EnableTriggerSourceAsync(triggerSourceId, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowTriggerSourceResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 停用一条 TriggerSource。
        /// </summary>
        public async Task<AMVisionApiResponse> DisableTriggerSourceAsync(
            string triggerSourceId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/trigger-sources/{EncodePathSegment(RequireId(triggerSourceId, nameof(triggerSourceId)))}/disable";
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 停用一条 TriggerSource，并返回 typed response。
        /// </summary>
        public async Task<WorkflowTriggerSourceResponse> DisableTriggerSourceResponseAsync(
            string triggerSourceId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await DisableTriggerSourceAsync(triggerSourceId, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowTriggerSourceResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 删除一条 TriggerSource。
        /// </summary>
        public async Task<AMVisionApiResponse> DeleteTriggerSourceAsync(
            string triggerSourceId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/trigger-sources/{EncodePathSegment(RequireId(triggerSourceId, nameof(triggerSourceId)))}";
            var apiResponse = await SendAsync(
                HttpMethod.Delete,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 查询一条 TriggerSource 的当前 health。
        /// </summary>
        public async Task<AMVisionApiResponse> GetTriggerSourceHealthAsync(
            string triggerSourceId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/trigger-sources/{EncodePathSegment(RequireId(triggerSourceId, nameof(triggerSourceId)))}/health";
            var apiResponse = await SendAsync(
                HttpMethod.Get,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 查询一条 TriggerSource 的当前 health，并返回 typed response。
        /// </summary>
        public async Task<WorkflowTriggerSourceHealthResponse> GetTriggerSourceHealthResponseAsync(
            string triggerSourceId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetTriggerSourceHealthAsync(triggerSourceId, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowTriggerSourceHealthResponse>(apiResponse);
            return typedResponse;
        }
    }
}
