using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision.ContractTests
{
    internal static class Program
    {
        private static int Main()
        {
            try
            {
                RunAsync().GetAwaiter().GetResult();
                Console.WriteLine("Workflow App version JSON contracts passed.");
                return 0;
            }
            catch (Exception error)
            {
                Console.Error.WriteLine(error);
                return 1;
            }
        }

        private static async Task RunAsync()
        {
            await VerifyCreateSelectorAsync().ConfigureAwait(false);
            await VerifySelectVersionRequestAsync().ConfigureAwait(false);
            await VerifyVersionArchiveRestoreAsync().ConfigureAwait(false);
            await VerifyRevisionPaginationAsync().ConfigureAwait(false);
            await VerifyRuntimeAndRevisionResponsesAsync().ConfigureAwait(false);
            await VerifyRunResponseAsync().ConfigureAwait(false);
            await VerifyConflictDetailsAsync().ConfigureAwait(false);
        }

        private static async Task VerifyCreateSelectorAsync()
        {
            var invalidHandler = new StubHandler(HttpStatusCode.OK, "{}");
            using (var invalidClient = CreateClient(invalidHandler))
            {
                await AssertThrowsAsync<ArgumentException>(() => invalidClient.CreateWorkflowAppRuntimeAsync(
                    new WorkflowAppRuntimeCreateRequest())).ConfigureAwait(false);

                await AssertThrowsAsync<ArgumentException>(() => invalidClient.CreateWorkflowAppRuntimeAsync(
                    new WorkflowAppRuntimeCreateRequest
                    {
                        ApplicationId = "workflow-app-draft",
                        WorkflowAppVersionId = "workflow-app-version-2"
                    })).ConfigureAwait(false);
            }

            AssertEqual(0, invalidHandler.CallCount, "invalid selectors must fail before HTTP transport");

            var versionHandler = new StubHandler(HttpStatusCode.Created, "{}");
            using (var versionClient = CreateClient(versionHandler))
            {
                await versionClient.CreateWorkflowAppRuntimeAsync(
                    new WorkflowAppRuntimeCreateRequest
                    {
                        ProjectId = "project-1",
                        WorkflowAppVersionId = "workflow-app-version-2",
                        DisplayName = "production"
                    }).ConfigureAwait(false);
            }

            var versionJson = JObject.Parse(versionHandler.LastRequestBody ?? string.Empty);
            AssertEqual("workflow-app-version-2", (string?)versionJson["workflow_app_version_id"], "version selector");
            Assert(versionJson["application_id"] == null, "version selector must omit application_id");

            var legacyHandler = new StubHandler(HttpStatusCode.Created, "{}");
            using (var legacyClient = CreateClient(legacyHandler))
            {
                await legacyClient.CreateWorkflowAppRuntimeAsync(
                    new WorkflowAppRuntimeCreateRequest
                    {
                        ProjectId = "project-1",
                        ApplicationId = "workflow-app-draft",
                        DisplayName = "legacy"
                    }).ConfigureAwait(false);
            }

            var legacyJson = JObject.Parse(legacyHandler.LastRequestBody ?? string.Empty);
            AssertEqual("workflow-app-draft", (string?)legacyJson["application_id"], "legacy selector");
            Assert(legacyJson["workflow_app_version_id"] == null, "legacy selector must omit workflow_app_version_id");
        }

        private static async Task VerifySelectVersionRequestAsync()
        {
            var invalidHandler = new StubHandler(HttpStatusCode.OK, "{}");
            using (var invalidClient = CreateClient(invalidHandler))
            {
                await AssertThrowsAsync<ArgumentException>(() =>
                    invalidClient.SelectWorkflowAppRuntimeVersionAsync(
                        "runtime-1",
                        new WorkflowAppRuntimeSelectVersionRequest())).ConfigureAwait(false);
                await AssertThrowsAsync<ArgumentOutOfRangeException>(() =>
                    invalidClient.SelectWorkflowAppRuntimeVersionAsync(
                        "runtime-1",
                        new WorkflowAppRuntimeSelectVersionRequest
                        {
                            WorkflowAppVersionId = "workflow-app-version-3",
                            ExpectedGeneration = -1
                        })).ConfigureAwait(false);
            }

            AssertEqual(0, invalidHandler.CallCount, "invalid version selection must not use HTTP transport");

            var handler = new StubHandler(HttpStatusCode.OK, "{}");
            using (var client = CreateClient(handler))
            {
                await client.SelectWorkflowAppRuntimeVersionAsync(
                    "runtime-1",
                    new WorkflowAppRuntimeSelectVersionRequest
                    {
                        WorkflowAppVersionId = "workflow-app-version-3",
                        ExpectedGeneration = 7,
                        AllowBreakingContract = true,
                        BreakingChangeReason = "approved"
                    }).ConfigureAwait(false);
            }

            AssertEqual(
                "http://127.0.0.1:5600/api/v1/workflows/app-runtimes/runtime-1/select-version",
                handler.LastRequestPath,
                "select-version path");
            var json = JObject.Parse(handler.LastRequestBody ?? string.Empty);
            AssertEqual("workflow-app-version-3", (string?)json["workflow_app_version_id"], "selected version");
            AssertEqual(7, (int?)json["expected_generation"], "expected generation");
            AssertEqual(true, (bool?)json["allow_breaking_contract"], "breaking contract flag");
            AssertEqual("approved", (string?)json["breaking_change_reason"], "breaking reason");
        }

        private static async Task VerifyVersionArchiveRestoreAsync()
        {
            var invalidHandler = new StubHandler(HttpStatusCode.OK, "{}");
            using (var invalidClient = CreateClient(invalidHandler))
            {
                await AssertThrowsAsync<ArgumentException>(() =>
                    invalidClient.ArchiveWorkflowAppVersionAsync(
                        "project-1",
                        "app-1",
                        "version-2",
                        new WorkflowAppVersionStateTransitionRequest
                        {
                            ExpectedState = "archived"
                        })).ConfigureAwait(false);
                await AssertThrowsAsync<ArgumentException>(() =>
                    invalidClient.RestoreWorkflowAppVersionAsync(
                        "project-1",
                        "app-1",
                        "version-2",
                        new WorkflowAppVersionStateTransitionRequest
                        {
                            ExpectedState = "published"
                        })).ConfigureAwait(false);
            }

            AssertEqual(0, invalidHandler.CallCount, "invalid version state CAS must not use HTTP transport");

            const string archivedVersionJson = @"{
                ""format_id"":""amvision.workflow-app-version.v1"",
                ""workflow_app_version_id"":""version-2"",
                ""project_id"":""project-1"",
                ""application_id"":""app-1"",
                ""version_number"":2,
                ""display_version"":""v2"",
                ""state"":""archived""
            }";
            var archiveHandler = new StubHandler(HttpStatusCode.OK, archivedVersionJson);
            WorkflowAppVersionResponse archivedVersion;
            using (var archiveClient = CreateClient(archiveHandler))
            {
                archivedVersion = await archiveClient.ArchiveWorkflowAppVersionResponseAsync(
                    "project one",
                    "app/one",
                    "version 2",
                    new WorkflowAppVersionStateTransitionRequest
                    {
                        ExpectedState = "published"
                    }).ConfigureAwait(false);
            }

            AssertEqual("POST", archiveHandler.LastRequestMethod, "archive HTTP method");
            AssertEqual(
                "http://127.0.0.1:5600/api/v1/workflows/projects/project%20one/applications/app%2Fone/versions/version%202/archive",
                archiveHandler.LastRequestPath,
                "archive path");
            AssertEqual(
                "published",
                (string?)JObject.Parse(archiveHandler.LastRequestBody ?? string.Empty)["expected_state"],
                "archive expected state");
            AssertEqual("version-2", archivedVersion.WorkflowAppVersionId, "archive response version");
            AssertEqual(2, archivedVersion.VersionNumber, "archive response number");
            AssertEqual("archived", archivedVersion.State, "archive response state");

            const string restoredVersionJson = @"{
                ""format_id"":""amvision.workflow-app-version.v1"",
                ""workflow_app_version_id"":""version-2"",
                ""project_id"":""project-1"",
                ""application_id"":""app-1"",
                ""version_number"":2,
                ""display_version"":""v2"",
                ""state"":""published""
            }";
            var restoreHandler = new StubHandler(HttpStatusCode.OK, restoredVersionJson);
            WorkflowAppVersionResponse restoredVersion;
            using (var restoreClient = CreateClient(restoreHandler))
            {
                restoredVersion = await restoreClient.RestoreWorkflowAppVersionResponseAsync(
                    "project-1",
                    "app-1",
                    "version-2",
                    new WorkflowAppVersionStateTransitionRequest
                    {
                        ExpectedState = "archived"
                    }).ConfigureAwait(false);
            }

            AssertEqual("POST", restoreHandler.LastRequestMethod, "restore HTTP method");
            AssertEqual(
                "http://127.0.0.1:5600/api/v1/workflows/projects/project-1/applications/app-1/versions/version-2/restore",
                restoreHandler.LastRequestPath,
                "restore path");
            AssertEqual(
                "archived",
                (string?)JObject.Parse(restoreHandler.LastRequestBody ?? string.Empty)["expected_state"],
                "restore expected state");
            AssertEqual("published", restoredVersion.State, "restore response state");
        }

        private static async Task VerifyRuntimeAndRevisionResponsesAsync()
        {
            const string runtimeJson = @"{
                ""format_id"":""amvision.workflow-app-runtime.v1"",
                ""workflow_runtime_id"":""runtime-1"",
                ""project_id"":""project-1"",
                ""application_id"":""app-1"",
                ""active_revision_id"":""revision-3"",
                ""desired_revision_id"":""revision-3"",
                ""revision_generation"":3,
                ""worker_instance_id"":""runtime-1-worker-epoch"",
                ""loaded_snapshot_fingerprint"":""sha256:runtime-fingerprint""
            }";
            var runtimeHandler = new StubHandler(HttpStatusCode.OK, runtimeJson);
            WorkflowAppRuntimeResponse runtime;
            using (var client = CreateClient(runtimeHandler))
            {
                runtime = await client.GetWorkflowAppRuntimeResponseAsync("runtime-1").ConfigureAwait(false);
            }

            AssertEqual("revision-3", runtime.ActiveRevisionId, "active revision");
            AssertEqual("revision-3", runtime.DesiredRevisionId, "desired revision");
            AssertEqual(3, runtime.RevisionGeneration, "runtime generation");
            AssertEqual("runtime-1-worker-epoch", runtime.WorkerInstanceId, "worker instance");
            AssertEqual("sha256:runtime-fingerprint", runtime.LoadedSnapshotFingerprint, "loaded fingerprint");

            const string revisionJson = @"{
                ""format_id"":""amvision.workflow-runtime-revision.v1"",
                ""workflow_runtime_revision_id"":""revision-3"",
                ""workflow_runtime_id"":""runtime-1"",
                ""generation"":3,
                ""workflow_app_version_id"":""workflow-app-version-3"",
                ""expected_snapshot_fingerprint"":""sha256:revision-fingerprint"",
                ""state"":""active""
            }";
            var revisionHandler = new StubHandler(HttpStatusCode.OK, revisionJson);
            WorkflowRuntimeRevisionResponse revision;
            using (var client = CreateClient(revisionHandler))
            {
                revision = await client.GetWorkflowRuntimeRevisionResponseAsync(
                    "runtime-1",
                    "revision-3").ConfigureAwait(false);
            }

            AssertEqual(3, revision.Generation, "revision generation");
            AssertEqual("workflow-app-version-3", revision.WorkflowAppVersionId, "revision version");
            AssertEqual("sha256:revision-fingerprint", revision.ExpectedSnapshotFingerprint, "revision fingerprint");
        }

        private static async Task VerifyRevisionPaginationAsync()
        {
            var handler = new StubHandler(HttpStatusCode.OK, "[]");
            using (var client = CreateClient(handler))
            {
                await client.ListWorkflowRuntimeRevisionResponsesAsync(
                    "runtime-1",
                    offset: 100,
                    limit: 50).ConfigureAwait(false);
            }

            AssertEqual(
                "http://127.0.0.1:5600/api/v1/workflows/app-runtimes/runtime-1/revisions?offset=100&limit=50",
                handler.LastRequestPath,
                "revision pagination path");
        }

        private static async Task VerifyRunResponseAsync()
        {
            const string runJson = @"{
                ""format_id"":""amvision.workflow-run.v1"",
                ""workflow_run_id"":""run-1"",
                ""workflow_runtime_id"":""runtime-1"",
                ""project_id"":""project-1"",
                ""application_id"":""app-1"",
                ""workflow_runtime_revision_id"":""revision-3"",
                ""workflow_app_version_id"":""workflow-app-version-3"",
                ""runtime_generation"":3,
                ""snapshot_fingerprint"":""sha256:run-fingerprint"",
                ""worker_instance_id"":""runtime-1-worker-epoch"",
                ""state"":""succeeded""
            }";
            var handler = new StubHandler(HttpStatusCode.OK, runJson);
            WorkflowRunResponse run;
            using (var client = CreateClient(handler))
            {
                run = await client.GetWorkflowRunResponseAsync("run-1").ConfigureAwait(false);
            }

            AssertEqual("revision-3", run.WorkflowRuntimeRevisionId, "run revision");
            AssertEqual("workflow-app-version-3", run.WorkflowAppVersionId, "run version");
            AssertEqual(3, run.RuntimeGeneration, "run generation");
            AssertEqual("sha256:run-fingerprint", run.SnapshotFingerprint, "run fingerprint");
            AssertEqual("runtime-1-worker-epoch", run.WorkerInstanceId, "run worker instance");
        }

        private static async Task VerifyConflictDetailsAsync()
        {
            const string conflictJson = @"{
                ""error"":{
                    ""code"":""RESOURCE_CONFLICT"",
                    ""message"":""runtime generation changed"",
                    ""details"":{
                        ""workflow_runtime_id"":""runtime-1"",
                        ""expected_generation"":2,
                        ""actual_generation"":3
                    }
                }
            }";
            var handler = new StubHandler(HttpStatusCode.Conflict, conflictJson);
            using (var client = CreateClient(handler))
            {
                try
                {
                    await client.GetWorkflowAppRuntimeResponseAsync("runtime-1").ConfigureAwait(false);
                    throw new InvalidOperationException("409 response must throw AMVisionApiException.");
                }
                catch (AMVisionApiException error)
                {
                    AssertEqual(HttpStatusCode.Conflict, error.StatusCode, "conflict status");
                    AssertEqual("RESOURCE_CONFLICT", error.ErrorCode, "conflict code");
                    AssertEqual(2, error.Details["expected_generation"].Value<int>(), "expected generation detail");
                    AssertEqual(3, error.Details["actual_generation"].Value<int>(), "actual generation detail");
                    AssertEqual("GET", error.HttpMethod, "conflict HTTP method");
                    AssertEqual(
                        "api/v1/workflows/app-runtimes/runtime-1",
                        error.RequestPath,
                        "conflict request path");
                    Assert(error.ResponseBody != null && error.ResponseBody.Contains("actual_generation"),
                        "conflict raw response must be retained");
                }
            }
        }

        private static AMVisionClient CreateClient(StubHandler handler)
        {
            var options = new AMVisionClientOptions
            {
                BaseApiUrl = "http://127.0.0.1:5600/",
                AccessToken = "contract-test-token"
            };
            return new AMVisionClient(options, new HttpClient(handler));
        }

        private static async Task AssertThrowsAsync<TException>(Func<Task> action)
            where TException : Exception
        {
            try
            {
                await action().ConfigureAwait(false);
            }
            catch (TException)
            {
                return;
            }

            throw new InvalidOperationException("Expected exception: " + typeof(TException).Name);
        }

        private static void Assert(bool condition, string message)
        {
            if (!condition)
            {
                throw new InvalidOperationException(message);
            }
        }

        private static void AssertEqual<T>(T expected, T actual, string field)
        {
            if (!EqualityComparer<T>.Default.Equals(expected, actual))
            {
                throw new InvalidOperationException(
                    field + " mismatch. Expected: " + expected + "; actual: " + actual + ".");
            }
        }

        private sealed class StubHandler : HttpMessageHandler
        {
            private readonly HttpStatusCode statusCode;
            private readonly string responseBody;

            internal StubHandler(HttpStatusCode statusCode, string responseBody)
            {
                this.statusCode = statusCode;
                this.responseBody = responseBody;
            }

            internal int CallCount { get; private set; }

            internal string? LastRequestPath { get; private set; }

            internal string? LastRequestMethod { get; private set; }

            internal string? LastRequestBody { get; private set; }

            protected override async Task<HttpResponseMessage> SendAsync(
                HttpRequestMessage request,
                CancellationToken cancellationToken)
            {
                CallCount++;
                LastRequestMethod = request.Method.Method;
                LastRequestPath = request.RequestUri?.AbsoluteUri;
                LastRequestBody = request.Content == null
                    ? null
                    : await request.Content.ReadAsStringAsync().ConfigureAwait(false);
                return new HttpResponseMessage(statusCode)
                {
                    Content = new StringContent(responseBody)
                };
            }
        }
    }
}
