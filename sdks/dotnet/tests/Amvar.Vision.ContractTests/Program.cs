using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision;
using Amvar.Vision.SharedMemory;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision.ContractTests
{
    internal static class Program
    {
        private static int Main(string[] args)
        {
            var probeResult = WorkflowTriggerContractProbe.TryRun(args);
            if (probeResult.HasValue)
            {
                return probeResult.Value;
            }

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
            WorkflowTriggerMailboxV1Fixture.Verify();
            LocalMessageChannelV1Fixture.Verify();
            VerifyZeroMqTriggerResultFrames();
            VerifyLocalBufferMappingCache();
            VerifyWorkflowTriggerHealthResponse();
            VerifyAutomaticConfigurationRequiresAsyncFactory();
            await VerifyCreateSelectorAsync().ConfigureAwait(false);
            await VerifySelectVersionRequestAsync().ConfigureAwait(false);
            await VerifyVersionArchiveRestoreAsync().ConfigureAwait(false);
            await VerifyRevisionPaginationAsync().ConfigureAwait(false);
            await VerifyRuntimeAndRevisionResponsesAsync().ConfigureAwait(false);
            await VerifyRunResponseAsync().ConfigureAwait(false);
            await VerifyConflictDetailsAsync().ConfigureAwait(false);
        }

        private static void VerifyWorkflowTriggerHealthResponse()
        {
            const string payload = @"{
                ""trigger_source_id"":""source-health"",
                ""enabled"":true,
                ""desired_state"":""running"",
                ""observed_state"":""running"",
                ""health_summary"":{
                    ""adapter_configured"":true,
                    ""adapter_running"":true,
                    ""request_count"":17,
                    ""request_count_rollover_count"":1,
                    ""success_count"":9,
                    ""success_count_rollover_count"":2,
                    ""error_count"":8,
                    ""error_count_rollover_count"":3,
                    ""timeout_count"":5,
                    ""timeout_count_rollover_count"":4,
                    ""busy_count"":6,
                    ""capacity_reject_count"":7,
                    ""request_timeout_count"":8,
                    ""response_ack_timeout_count"":9,
                    ""cancel_count"":10,
                    ""supervisor"":{}
                }
            }";
            var response = JsonConvert.DeserializeObject<WorkflowTriggerSourceHealthResponse>(payload);
            Assert(response != null, "health response must deserialize");
            var health = response!.HealthSummary;
            Assert(health.RequestCountRolloverCount == 1, "request rollover count mismatch");
            Assert(health.SuccessCountRolloverCount == 2, "success rollover count mismatch");
            Assert(health.ErrorCountRolloverCount == 3, "error rollover count mismatch");
            Assert(health.TimeoutCountRolloverCount == 4, "timeout rollover count mismatch");
            Assert(health.BusyCount == 6, "busy count mismatch");
            Assert(health.CapacityRejectCount == 7, "capacity count mismatch");
            Assert(health.RequestTimeoutCount == 8, "request timeout count mismatch");
            Assert(health.ResponseAckTimeoutCount == 9, "ACK timeout count mismatch");
            Assert(health.CancelCount == 10, "cancel count mismatch");
        }

        private static void VerifyAutomaticConfigurationRequiresAsyncFactory()
        {
            var root = Path.Combine(
                Path.GetTempPath(),
                "amvision-sdk-bootstrap-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                File.WriteAllText(
                    Path.Combine(root, "sdk-bootstrap.json"),
                    @"{
                        ""format_id"":""amvision.sdk-bootstrap.v1"",
                        ""backend"":{
                            ""base_api_url"":""http://127.0.0.1:5600"",
                            ""configuration_path"":""/api/v1/projects/project-1/sdk-config-packages/current"",
                            ""access_token"":""token"",
                            ""http_timeout_seconds"":10
                        },
                        ""configuration_sync"":{
                            ""enabled"":true,
                            ""use_last_known_good"":true
                        }
                    }",
                    Encoding.UTF8);
                try
                {
                    AMVisionClient.CreateFromConfigDirectory(root);
                }
                catch (InvalidOperationException error)
                {
                    Assert(
                        error.Message.Contains("CreateFromConfigDirectoryAsync"),
                        "automatic configuration sync must require the async factory");
                    return;
                }

                throw new InvalidOperationException(
                    "Automatic configuration sync was silently ignored by the synchronous factory.");
            }
            finally
            {
                Directory.Delete(root, true);
            }
        }

        private static void VerifyZeroMqTriggerResultFrames()
        {
            const string manifest = @"{
                ""format_id"":""amvision.workflow-trigger-result.v1"",
                ""trigger_source_id"":""trigger-source-1"",
                ""event_id"":""event-1"",
                ""state"":""succeeded"",
                ""response_payload"":{
                    ""results"":{""ok"":true},
                    ""attachments"":[
                        {""attachment_id"":""a-1"",""binding_id"":""image-a"",""item_index"":0,""payload_id"":""p-1""},
                        {""attachment_id"":""a-2"",""binding_id"":""image-b"",""item_index"":0,""payload_id"":""p-1""}
                    ],
                    ""payloads"":[{
                        ""payload_id"":""p-1"",
                        ""delivery_kind"":""zeromq-frame"",
                        ""frame_index"":1,
                        ""media_type"":""image/png"",
                        ""content_length"":12,
                        ""checksum_algorithm"":""crc32"",
                        ""checksum"":""1223ff19"",
                        ""shape"":[]
                    }]
                }
            }";
            var content = Encoding.ASCII.GetBytes("result-image");
            var result = AMVisionTriggerClient.ParseReply(new[]
            {
                Encoding.UTF8.GetBytes(manifest),
                content
            });

            AssertEqual(2, result.ImageAttachments.Count, "ZeroMQ logical attachment count");
            AssertEqual("image-a", result.ImageAttachments[0].BindingId, "first binding id");
            AssertEqual("image/png", result.ImageAttachments[0].MediaType, "image media type");
            Assert(
                ReferenceEquals(result.ImageAttachments[0].Content, result.ImageAttachments[1].Content),
                "duplicate logical attachments must share one physical byte[]");
            AssertEqual("result-image", Encoding.ASCII.GetString(result.ImageAttachments[0].Content), "image bytes");

            var failed = AMVisionTriggerClient.ParseReply(new[]
            {
                Encoding.UTF8.GetBytes(@"{
                    ""format_id"":""amvision.workflow-trigger-result.v1"",
                    ""trigger_source_id"":""trigger-source-1"",
                    ""event_id"":""event-error"",
                    ""state"":""failed"",
                    ""error_message"":""bad envelope"",
                    ""metadata"":{""error_code"":""invalid_request"",""error_details"":{}}
                }")
            });
            AssertEqual("failed", failed.State, "unified failed result state");
            AssertEqual("invalid_request", failed.Metadata["error_code"].Value<string>(), "unified failed result code");
        }

        private static void VerifyLocalBufferMappingCache()
        {
            var root = Path.Combine(
                Path.GetTempPath(),
                "amvision-local-buffer-cache-" + Guid.NewGuid().ToString("N"));
            var localBufferRoot = Path.Combine(root, "local-buffer");
            Directory.CreateDirectory(localBufferRoot);
            var arenaPath = Path.Combine(localBufferRoot, "images.mmap");
            var allocatorPath = Path.Combine(localBufferRoot, "state.mmap");
            var guardPath = Path.Combine(localBufferRoot, "access.guard");
            const long arenaSize = 4 * 1024 * 1024;
            using (var file = new FileStream(arenaPath, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.ReadWrite | FileShare.Delete))
            {
                file.SetLength(arenaSize);
            }
            var brokerEpoch = CreateArenaMetadata(allocatorPath, arenaSize);
            using (var guard = new FileStream(guardPath, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.ReadWrite | FileShare.Delete))
            {
                guard.SetLength(25);
            }
            var options = new SharedMemoryTriggerClientOptions
            {
                BuffersRoot = root,
                TriggerSourceId = "trigger-source-1",
                RouteGeneration = 1
            };

            try
            {
                using (var cache = new LocalBufferMappingCache(options))
                {
                    var allocation = CreateAllocation(brokerEpoch, "buffer-0", 0, 0, 512 * 1024);
                    var mismatchedLayout = CreateAllocation(
                        brokerEpoch,
                        "buffer-layout-mismatch",
                        0,
                        0,
                        512 * 1024);
                    mismatchedLayout.LayoutFingerprint = new string('f', 64);
                    try
                    {
                        cache.Acquire(mismatchedLayout).Dispose();
                        throw new InvalidOperationException(
                            "LocalBuffer mapping accepted a mismatched layout fingerprint.");
                    }
                    catch (SharedMemoryTriggerException error)
                    {
                        AssertEqual("protocol_error", error.ErrorCode, "layout mismatch error code");
                    }

                    using (var first = cache.Acquire(allocation))
                    using (var second = cache.Acquire(allocation))
                    {
                        Assert(
                            ReferenceEquals(first.View, second.View),
                            "same physical allocation must reuse one mmap view");
                    }

                    using (var slotZero = cache.Acquire(
                        CreateAllocation(brokerEpoch, "buffer-0", 0, 0, 512 * 1024)))
                    using (var slotOne = cache.Acquire(
                        CreateAllocation(brokerEpoch, "buffer-1", 1, 1024 * 1024, 512 * 1024)))
                    using (var slotZeroAgain = cache.Acquire(
                        CreateAllocation(brokerEpoch, "buffer-0", 0, 0, 512 * 1024)))
                    {
                        Assert(
                            ReferenceEquals(slotZero.View, slotZeroAgain.View),
                            "all dynamic extents must reuse the single fixed arena view");
                        Assert(
                            ReferenceEquals(slotZero.View, slotOne.View),
                            "different extents must not create per-image mmap views");
                        slotOne.View.Write(slotOne.Offset, (byte)23);
                        AssertEqual((byte)23, slotOne.View.ReadByte(slotOne.Offset), "extent offset access");
                    }
                }

                var deferredCache = new LocalBufferMappingCache(options);
                var active = deferredCache.Acquire(
                    CreateAllocation(brokerEpoch, "buffer-1", 1, 1024 * 1024, 512 * 1024));
                deferredCache.Dispose();
                active.View.Write(active.Offset, (byte)31);
                AssertEqual((byte)31, active.View.ReadByte(active.Offset), "active mapping survives cache dispose request");
                active.Dispose();
                try
                {
                    deferredCache.Acquire(
                        CreateAllocation(brokerEpoch, "buffer-1", 1, 1024 * 1024, 512 * 1024));
                    throw new InvalidOperationException("disposed mapping cache must reject acquire");
                }
                catch (ObjectDisposedException)
                {
                }
            }
            finally
            {
                Directory.Delete(root, recursive: true);
            }
        }

        private static WorkflowTriggerAllocation CreateAllocation(
            string brokerEpoch,
            string bufferId,
            int descriptorIndex,
            long offset,
            long size)
        {
            return new WorkflowTriggerAllocation
            {
                FormatId = "amvision.workflow-trigger-allocation.v1",
                ArenaId = "local-buffer-main",
                LeaseId = "lease-1",
                BufferId = bufferId,
                DescriptorIndex = descriptorIndex,
                DescriptorGeneration = 1,
                BrokerEpoch = brokerEpoch,
                LayoutFingerprint = new string('0', 64),
                Offset = offset,
                ContentLength = size,
                AllocationCapacityBytes = 1024 * 1024
            };
        }

        private static string CreateArenaMetadata(string path, long arenaSize)
        {
            var epoch = new byte[16];
            for (var index = 0; index < epoch.Length; index++)
            {
                epoch[index] = checked((byte)(index + 1));
            }

            using (var file = new FileStream(path, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.ReadWrite | FileShare.Delete))
            using (var writer = new BinaryWriter(file, Encoding.UTF8, leaveOpen: false))
            {
                file.SetLength(256 + 4 * 256);
                writer.Write(Encoding.ASCII.GetBytes("AMVLBA01"));
                writer.Write(1U);
                writer.Write(256U);
                writer.Write(256U);
                writer.Write(4U);
                writer.Write(4U);
                writer.Write(6U);
                writer.Write(checked((ulong)arenaSize));
                writer.Write(1024UL * 1024UL);
                writer.Write(4UL * 1024UL * 1024UL);
                writer.Write(0UL);
                writer.Write(epoch);
                writer.Write(new byte[32]);
                writer.Write(1UL);
                WriteArenaDescriptor(writer, 0, 0, 512 * 1024);
                WriteArenaDescriptor(writer, 1, 1024 * 1024, 512 * 1024);
            }

            var builder = new StringBuilder(32);
            foreach (var item in epoch)
            {
                builder.Append(item.ToString("x2"));
            }
            return builder.ToString();
        }

        private static void WriteArenaDescriptor(
            BinaryWriter writer,
            int descriptorIndex,
            long offset,
            long contentLength)
        {
            writer.BaseStream.Position = 256 + descriptorIndex * 256;
            writer.Write(1U);
            writer.Write(0U);
            writer.Write(1UL);
            writer.Write(new byte[16]);
            writer.Write(new byte[16]);
            writer.Write(checked((ulong)offset));
            writer.Write(1024UL * 1024UL);
            writer.Write(checked((ulong)contentLength));
            writer.Write(ulong.MaxValue >> 1);
            writer.Write(0UL);
            writer.Write(20U);
            writer.Write(0U);
            writer.Write(1UL);
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
