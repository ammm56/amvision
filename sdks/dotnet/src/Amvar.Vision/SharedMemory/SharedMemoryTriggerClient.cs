using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using Amvar.Vision.Tools;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision.SharedMemory
{
    /// <summary>
    /// 同机高性能 Workflow Trigger client；图片写 LocalBuffer，参数和结果走全局 mailbox。
    /// </summary>
    public sealed class SharedMemoryTriggerClient : IDisposable
    {
        private readonly object syncRoot = new object();
        private readonly SharedMemoryTriggerClientOptions options;
        private readonly WorkflowTriggerMailboxClient mailbox;
        private readonly LocalBufferMappingCache mappingCache;
        private int activeInvocationCount;
        private int activeResultCount;
        private bool disposeRequested;
        private bool mailboxDisposed;

        /// <summary>打开 backend 已初始化的全局 Workflow Trigger mailbox。</summary>
        public SharedMemoryTriggerClient(SharedMemoryTriggerClientOptions options)
        {
            this.options = options ?? throw new ArgumentNullException(nameof(options));
            this.options.Validate();
            mappingCache = new LocalBufferMappingCache(this.options);
            mailbox = new WorkflowTriggerMailboxClient(this.options.BuffersRoot);
        }

        /// <summary>按调用方给定的 encoded 或 raw 表示直接写入 LocalBuffer。</summary>
        public SharedMemoryTriggerResult InvokeImageBytes(
            byte[] imageBytes,
            string mediaType,
            SharedMemoryTriggerRequest? request = null,
            IReadOnlyList<int>? shape = null,
            string? dtype = null,
            string? layout = null,
            string? pixelFormat = null)
        {
            if (imageBytes == null || imageBytes.Length == 0)
            {
                throw new ArgumentException("imageBytes cannot be empty.", nameof(imageBytes));
            }

            return InvokeImageBytesCore(
                imageBytes,
                mediaType,
                request,
                shape,
                dtype,
                layout,
                pixelFormat,
                CreateTimings(request));
        }

        private SharedMemoryTriggerResult InvokeImageBytesCore(
            byte[] imageBytes,
            string mediaType,
            SharedMemoryTriggerRequest? request,
            IReadOnlyList<int>? shape,
            string? dtype,
            string? layout,
            string? pixelFormat,
            SharedMemoryTriggerTimings? timings)
        {
            return Invoke(
                contentLength: imageBytes.LongLength,
                mediaType: RequireText(mediaType, nameof(mediaType)),
                request: request,
                shape: shape,
                dtype: dtype,
                layout: layout,
                pixelFormat: pixelFormat,
                write: writer => writer.Write(imageBytes),
                timings: timings);
        }

        /// <summary>直接写入连续 HWC BGR24；不执行图片编码或解码。</summary>
        public SharedMemoryTriggerResult InvokeBgr24(
            byte[] bgr24Bytes,
            int width,
            int height,
            SharedMemoryTriggerRequest? request = null)
        {
            ImageConversionTools.ValidateBgr24Bytes(bgr24Bytes, width, height, nameof(bgr24Bytes));
            return InvokeImageBytesCore(
                bgr24Bytes,
                "image/raw",
                request,
                new[] { height, width, 3 },
                "uint8",
                "HWC",
                "BGR24",
                CreateTimings(request));
        }

        /// <summary>
        /// 让采集或处理库直接填充本次 lease 的连续 HWC BGR24 Span；
        /// 不建立中间 BGR24 数组，也不执行图片编码或解码。
        /// </summary>
        public SharedMemoryTriggerResult InvokeBgr24(
            int width,
            int height,
            SharedMemoryTriggerBufferWriter fill,
            SharedMemoryTriggerRequest? request = null)
        {
            if (width <= 0 || height <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(width), "width and height must be positive.");
            }

            if (fill == null)
            {
                throw new ArgumentNullException(nameof(fill));
            }

            var contentLength = checked((long)width * height * 3);
            var timings = CreateTimings(request);
            return Invoke(
                contentLength,
                "image/raw",
                request,
                new[] { height, width, 3 },
                "uint8",
                "HWC",
                "BGR24",
                writer => writer.Write(fill),
                timings);
        }

        /// <summary>把带正/负 row stride 的 BGR24 规范化为连续 HWC 后写入。</summary>
        public SharedMemoryTriggerResult InvokeBgr24(
            byte[] source,
            int width,
            int height,
            int rowStride,
            SharedMemoryTriggerRequest? request = null)
        {
            var timings = CreateTimings(request);
            var conversionStartedAt = StartTiming(timings);
            var contiguous = NormalizeBgr24(source, width, height, rowStride);
            RecordConversionTiming(timings, conversionStartedAt);
            ImageConversionTools.ValidateBgr24Bytes(contiguous, width, height, nameof(source));
            return InvokeImageBytesCore(
                contiguous,
                "image/raw",
                request,
                new[] { height, width, 3 },
                "uint8",
                "HWC",
                "BGR24",
                timings);
        }

        /// <summary>把 Mono8 按正/负 stride 转为连续 BGR24 后写入。</summary>
        public SharedMemoryTriggerResult InvokeMono8(
            byte[] mono8Bytes,
            int width,
            int height,
            int rowStride,
            SharedMemoryTriggerRequest? request = null)
        {
            var timings = CreateTimings(request);
            var conversionStartedAt = StartTiming(timings);
            var bgr24 = ConvertMono8ToBgr24(mono8Bytes, width, height, rowStride);
            RecordConversionTiming(timings, conversionStartedAt);
            return InvokeImageBytesCore(
                bgr24,
                "image/raw",
                request,
                new[] { height, width, 3 },
                "uint8",
                "HWC",
                "BGR24",
                timings);
        }

        /// <summary>把 Bitmap 转为连续 BGR24 后写入。</summary>
        public SharedMemoryTriggerResult InvokeBitmap(Bitmap bitmap, SharedMemoryTriggerRequest? request = null)
        {
            if (bitmap == null)
            {
                throw new ArgumentNullException(nameof(bitmap));
            }

            var timings = CreateTimings(request);
            var conversionStartedAt = StartTiming(timings);
            var frame = ImageConversionTools.BitmapToBgr24(bitmap);
            RecordConversionTiming(timings, conversionStartedAt);
            return InvokeImageBytesCore(
                frame.Bytes,
                "image/raw",
                request,
                new[] { frame.Height, frame.Width, 3 },
                "uint8",
                "HWC",
                "BGR24",
                timings);
        }

        /// <summary>保留 JPEG/PNG/BMP 等 encoded bytes，从文件流直接写入。</summary>
        public SharedMemoryTriggerResult InvokeImageFromFile(
            string imagePath,
            string? mediaType = null,
            SharedMemoryTriggerRequest? request = null)
        {
            var fullPath = Path.GetFullPath(RequireText(imagePath, nameof(imagePath)));
            var fileInfo = new FileInfo(fullPath);
            if (!fileInfo.Exists || fileInfo.Length <= 0)
            {
                throw new FileNotFoundException("Image file does not exist or is empty.", fullPath);
            }

            var resolvedMediaType = string.IsNullOrWhiteSpace(mediaType)
                ? ImageConversionTools.GetMediaType(ImageConversionTools.InferFormatFromPath(fullPath))
                : mediaType!.Trim();
            var timings = CreateTimings(request);
            return Invoke(
                fileInfo.Length,
                resolvedMediaType,
                request,
                shape: null,
                dtype: null,
                layout: null,
                pixelFormat: null,
                write: writer =>
                {
                    using (var stream = new FileStream(fullPath, FileMode.Open, FileAccess.Read, FileShare.Read))
                    {
                        writer.Write(stream, fileInfo.Length);
                    }
                },
                timings: timings);
        }

        /// <summary>只还原 Base64/Data URL 为 encoded bytes，不在 SDK 解码图片矩阵。</summary>
        public SharedMemoryTriggerResult InvokeImageBase64(
            string imageBase64,
            string? mediaType = null,
            SharedMemoryTriggerRequest? request = null)
        {
            var timings = CreateTimings(request);
            var decodeStartedAt = StartTiming(timings);
            var encoded = DecodeBase64(imageBase64, out var dataUrlMediaType);
            if (timings != null)
            {
                timings.SdkBase64DecodeMs = ElapsedMilliseconds(decodeStartedAt);
            }

            return InvokeImageBytesCore(
                encoded,
                string.IsNullOrWhiteSpace(mediaType)
                    ? dataUrlMediaType ?? "application/octet-stream"
                    : mediaType!.Trim(),
                request,
                shape: null,
                dtype: null,
                layout: null,
                pixelFormat: null,
                timings: timings);
        }

        /// <summary>
        /// 直接发布不带图片的 event-only 请求；不执行 PREPARE 或 LocalBuffer allocation。
        /// </summary>
        public SharedMemoryTriggerResult InvokeEvent(
            SharedMemoryTriggerEventRequest request)
        {
            if (request == null)
            {
                throw new ArgumentNullException(nameof(request));
            }

            var timings = request.EnableTimings ? new SharedMemoryTriggerTimings() : null;
            if (timings != null)
            {
                timings.InvokeStartedAtTicks = Stopwatch.GetTimestamp();
            }
            BeginInvocation();
            try
            {
                var eventId = NormalizeOptional(request.EventId)
                    ?? "trigger-event-" + Guid.NewGuid().ToString("N");
                var traceId = NormalizeOptional(request.TraceId)
                    ?? "trace-" + Guid.NewGuid().ToString("N");
                var localDeadline = WorkflowTriggerMailboxClient.LocalDeadline(options.Timeout);
                var eventPayload = WorkflowJsonDefaults.SerializeToUtf8Bytes(
                    new WorkflowTriggerEventRequestPayload
                    {
                        TriggerSourceId = options.TriggerSourceId,
                        EventId = eventId,
                        Payload = new Dictionary<string, object?>(request.Payload),
                        Metadata = new Dictionary<string, object?>(request.Metadata),
                        TraceId = traceId,
                        IdempotencyKey = NormalizeOptional(request.IdempotencyKey)
                    });
                var claimStartedAt = StartTiming(timings);
                var identity = mailbox.ClaimEvent(
                    checked((uint)Math.Ceiling(options.Timeout.TotalMilliseconds)),
                    checked((ulong)options.RouteGeneration),
                    eventPayload,
                    Guid.NewGuid());
                if (timings != null)
                {
                    timings.SdkMailboxClaimMs = ElapsedMilliseconds(claimStartedAt);
                }
                try
                {
                    var responseWaitStartedAt = StartTiming(timings);
                    var response = WaitForResponse(identity, localDeadline);
                    if (timings != null)
                    {
                        timings.SdkResponseWaitMs = ElapsedMilliseconds(responseWaitStartedAt);
                    }
                    var resultBuildStartedAt = StartTiming(timings);
                    var responseAckDeadline =
                        WorkflowTriggerMailboxClient.LocalDeadlineFromBackendMonotonicNs(
                            response.ResponseAckDeadlineNs);
                    var result = BuildResult(response, responseAckDeadline, timings);
                    if (timings != null)
                    {
                        timings.SdkResultBuildMs = ElapsedMilliseconds(resultBuildStartedAt);
                        timings.InvokeReturnMs = ElapsedMilliseconds(timings.InvokeStartedAtTicks);
                    }
                    return result;
                }
                catch (Exception error)
                {
                    try
                    {
                        var cancelReason = error is SharedMemoryTriggerException triggerError
                            && string.Equals(triggerError.ErrorCode, "timeout", StringComparison.Ordinal)
                                ? WorkflowTriggerMailboxV1.CancelReasonRequestTimeout
                                : WorkflowTriggerMailboxV1.CancelReasonExplicit;
                        mailbox.Cancel(identity, cancelReason);
                    }
                    catch
                    {
                        // 原异常保持为调用方可见结果；取消只做 identity-fenced 补偿。
                    }
                    throw;
                }
            }
            finally
            {
                EndInvocation();
            }
        }

        /// <summary>停止接收新调用；已有零复制结果释放后再关闭 mailbox。</summary>
        public void Dispose()
        {
            lock (syncRoot)
            {
                if (disposeRequested)
                {
                    return;
                }

                disposeRequested = true;
                if (activeInvocationCount == 0 && activeResultCount == 0)
                {
                    DisposeResourcesLocked();
                }
            }
        }

        private SharedMemoryTriggerResult Invoke(
            long contentLength,
            string mediaType,
            SharedMemoryTriggerRequest? request,
            IReadOnlyList<int>? shape,
            string? dtype,
            string? layout,
            string? pixelFormat,
            Action<ExternalLocalBufferWriter> write,
            SharedMemoryTriggerTimings? timings)
        {
            BeginInvocation();
            try
            {
                return InvokeCore(
                    contentLength,
                    mediaType,
                    request,
                    shape,
                    dtype,
                    layout,
                    pixelFormat,
                    write,
                    timings);
            }
            finally
            {
                EndInvocation();
            }
        }

        private SharedMemoryTriggerResult InvokeCore(
            long contentLength,
            string mediaType,
            SharedMemoryTriggerRequest? request,
            IReadOnlyList<int>? shape,
            string? dtype,
            string? layout,
            string? pixelFormat,
            Action<ExternalLocalBufferWriter> write,
            SharedMemoryTriggerTimings? timings)
        {
            if (contentLength <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(contentLength), contentLength, "Image length must be positive.");
            }

            var call = request ?? new SharedMemoryTriggerRequest();
            var eventId = NormalizeOptional(call.EventId) ?? "trigger-event-" + Guid.NewGuid().ToString("N");
            var traceId = NormalizeOptional(call.TraceId) ?? "trace-" + Guid.NewGuid().ToString("N");
            var inputBinding = NormalizeOptional(call.InputBinding) ?? options.DefaultInputBinding;
            var localDeadline = WorkflowTriggerMailboxClient.LocalDeadline(options.Timeout);
            var mailboxClaimStartedAt = StartTiming(timings);
            var preparePayload = WorkflowJsonDefaults.SerializeToUtf8Bytes(new WorkflowTriggerPrepare
            {
                TriggerSourceId = options.TriggerSourceId,
                EventId = eventId,
                Image = new WorkflowTriggerInputImageSpec
                {
                    ContentLength = contentLength,
                    MediaType = mediaType,
                    EventPayloadKey = inputBinding,
                    Shape = shape ?? Array.Empty<int>(),
                    DType = NormalizeOptional(dtype),
                    Layout = NormalizeOptional(layout),
                    PixelFormat = NormalizeOptional(pixelFormat)
                }
            });
            var claimed = mailbox.Claim(
                checked((uint)Math.Ceiling(options.Timeout.TotalMilliseconds)),
                checked((ulong)options.RouteGeneration),
                preparePayload,
                Guid.NewGuid());
            if (timings != null)
            {
                timings.SdkMailboxClaimMs = ElapsedMilliseconds(mailboxClaimStartedAt);
            }
            var identity = claimed;
            try
            {
                var allocationWaitStartedAt = StartTiming(timings);
                var allocationRead = WaitForAllocationOrThrow(claimed, localDeadline);
                if (timings != null)
                {
                    timings.SdkAllocationWaitMs = ElapsedMilliseconds(allocationWaitStartedAt);
                }
                identity = allocationRead.Identity;
                var allocation = WorkflowJsonDefaults.Deserialize<WorkflowTriggerAllocation>(Encoding.UTF8.GetString(allocationRead.Payload));
                ValidateAllocation(allocation, contentLength);
                var writerOpenStartedAt = StartTiming(timings);
                var writer = new ExternalLocalBufferWriter(
                    allocation,
                    localDeadline,
                    timings != null,
                    mappingCache);
                try
                {
                    if (timings != null)
                    {
                        timings.SdkWriterOpenMs = ElapsedMilliseconds(writerOpenStartedAt);
                    }
                    write(writer);
                    if (timings != null)
                    {
                        timings.SdkWriteLocalBufferMs += writer.WriteElapsedMs;
                    }
                }
                finally
                {
                    var writerCloseStartedAt = StartTiming(timings);
                    writer.Dispose();
                    if (timings != null)
                    {
                        timings.SdkWriterCloseMs = ElapsedMilliseconds(writerCloseStartedAt);
                    }
                }
                var requestPayload = WorkflowJsonDefaults.SerializeToUtf8Bytes(new WorkflowTriggerRequestPayload
                {
                    TriggerSourceId = options.TriggerSourceId,
                    EventId = eventId,
                    Payload = new Dictionary<string, object?>(call.Payload),
                    Metadata = new Dictionary<string, object?>(call.Metadata),
                    TraceId = traceId,
                    IdempotencyKey = NormalizeOptional(call.IdempotencyKey)
                });
                // REQUEST 是 external write 的 publication barrier。必须先释放
                // writer guard，再允许服务端 commit；否则高频 poller 可能在 using
                // 离开前观察 REQUEST，形成正常写入与 commit 的竞态。
                var requestPublishStartedAt = StartTiming(timings);
                mailbox.PublishRequest(identity, requestPayload);
                if (timings != null)
                {
                    timings.SdkRequestPublishMs = ElapsedMilliseconds(requestPublishStartedAt);
                }

                var responseWaitStartedAt = StartTiming(timings);
                var response = WaitForResponse(identity, localDeadline);
                if (timings != null)
                {
                    timings.SdkResponseWaitMs = ElapsedMilliseconds(responseWaitStartedAt);
                }
                var resultBuildStartedAt = StartTiming(timings);
                var responseAckDeadline = WorkflowTriggerMailboxClient.LocalDeadlineFromBackendMonotonicNs(
                    response.ResponseAckDeadlineNs);
                var result = BuildResult(response, responseAckDeadline, timings);
                if (timings != null)
                {
                    timings.SdkResultBuildMs = ElapsedMilliseconds(resultBuildStartedAt);
                    timings.InvokeReturnMs = ElapsedMilliseconds(timings.InvokeStartedAtTicks);
                }

                return result;
            }
            catch (Exception error)
            {
                try
                {
                    var cancelReason = error is SharedMemoryTriggerException triggerError
                        && string.Equals(triggerError.ErrorCode, "timeout", StringComparison.Ordinal)
                            ? WorkflowTriggerMailboxV1.CancelReasonRequestTimeout
                            : WorkflowTriggerMailboxV1.CancelReasonExplicit;
                    mailbox.Cancel(identity, cancelReason);
                }
                catch
                {
                    // 原异常是调用方可见的权威失败；取消是 identity-fenced best effort。
                }

                throw;
            }
        }

        private WorkflowTriggerAllocationRead WaitForAllocationOrThrow(
            WorkflowTriggerDescriptorIdentity identity,
            long localDeadline)
        {
            var waitStartedAt = Stopwatch.GetTimestamp();
            while (Stopwatch.GetTimestamp() < localDeadline)
            {
                var allocation = mailbox.TryReadAllocation(identity);
                if (allocation != null)
                {
                    return allocation;
                }

                var earlyResponse = mailbox.TryReadResponse(identity);
                if (earlyResponse != null)
                {
                    ThrowResponseErrorAndAcknowledge(earlyResponse);
                }

                PausePoll(waitStartedAt);
            }

            throw new SharedMemoryTriggerException("timeout", "Timed out waiting for LocalBuffer allocation.");
        }

        private WorkflowTriggerMailboxResponse WaitForResponse(
            WorkflowTriggerDescriptorIdentity identity,
            long localDeadline)
        {
            var waitStartedAt = Stopwatch.GetTimestamp();
            while (Stopwatch.GetTimestamp() < localDeadline)
            {
                var response = mailbox.TryReadResponse(identity);
                if (response != null)
                {
                    return response;
                }

                PausePoll(waitStartedAt);
            }

            throw new SharedMemoryTriggerException("timeout", "Timed out waiting for Workflow Trigger response.");
        }

        private SharedMemoryTriggerResult BuildResult(
            WorkflowTriggerMailboxResponse response,
            long localDeadline,
            SharedMemoryTriggerTimings? timings)
        {
            if (response.ErrorCode != WorkflowTriggerMailboxV1.ErrorCodeNone)
            {
                ThrowResponseErrorAndAcknowledge(response);
            }

            TriggerResult triggerResult;
            try
            {
                triggerResult = WorkflowJsonDefaults.Deserialize<TriggerResult>(
                    DecodeUtf8(response.Payload));
            }
            catch (Exception error)
            {
                mailbox.Cancel(response.Identity, WorkflowTriggerMailboxV1.CancelReasonExplicit);
                throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger response is not valid result JSON.", error);
            }

            if (!string.Equals(triggerResult.FormatId, AMVisionTriggerClient.TriggerResultFormatId, StringComparison.Ordinal))
            {
                mailbox.Cancel(response.Identity, WorkflowTriggerMailboxV1.CancelReasonExplicit);
                throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger result format_id is not supported.");
            }

            var logical = ParseList<PublicLogicalAttachment>(triggerResult.ResponsePayload, "attachments");
            var physical = ParseList<PublicPhysicalPayload>(triggerResult.ResponsePayload, "payloads");
            var localPayloads = physical.Where(item => string.Equals(item.DeliveryKind, "local-buffer", StringComparison.Ordinal)).ToArray();
            if (localPayloads.Length != response.OutputLeaseCount)
            {
                mailbox.Cancel(response.Identity, WorkflowTriggerMailboxV1.CancelReasonExplicit);
                throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger output lease count does not match the manifest.");
            }

            if (localPayloads.Length == 0)
            {
                var acknowledgeStartedAt = StartTiming(timings);
                mailbox.Acknowledge(response.Identity);
                if (timings != null)
                {
                    timings.DisposeAckMs = ElapsedMilliseconds(acknowledgeStartedAt);
                }

                return new SharedMemoryTriggerResult(
                    triggerResult,
                    Array.Empty<PhysicalPayloadReader>(),
                    Array.Empty<PublicLogicalAttachment>(),
                    () => { },
                    timings);
            }

            var readers = new List<PhysicalPayloadReader>();
            try
            {
                foreach (var payload in localPayloads)
                {
                    readers.Add(OpenPhysicalReader(payload, localDeadline, timings));
                }

                if (!mailbox.IsResponseCurrent(response.Identity))
                {
                    throw new SharedMemoryTriggerException("identity_mismatch", "Workflow Trigger response expired while acquiring output readers.");
                }

                lock (syncRoot)
                {
                    if (disposeRequested || mailboxDisposed)
                    {
                        throw new ObjectDisposedException(nameof(SharedMemoryTriggerClient));
                    }

                    activeResultCount += 1;
                }

                return new SharedMemoryTriggerResult(
                    triggerResult,
                    readers,
                    logical,
                    () => ReleaseResultAndAcknowledge(response.Identity),
                    timings);
            }
            catch
            {
                foreach (var reader in readers)
                {
                    reader.Dispose();
                }

                mailbox.Cancel(response.Identity, WorkflowTriggerMailboxV1.CancelReasonExplicit);
                throw;
            }
        }

        private PhysicalPayloadReader OpenPhysicalReader(
            PublicPhysicalPayload payload,
            long localDeadline,
            SharedMemoryTriggerTimings? timings)
        {
            if (payload.BufferRef == null
                || payload.ContentLength <= 0)
            {
                throw new SharedMemoryTriggerException("protocol_error", "LocalBuffer result locator is incomplete.");
            }

            var arenaId = payload.BufferRef.Value<string>("arena_id") ?? string.Empty;
            var brokerEpoch = payload.BufferRef.Value<string>("broker_epoch") ?? string.Empty;
            var descriptorIndex = payload.BufferRef.Value<int?>("descriptor_index") ?? -1;
            var descriptorGeneration = payload.BufferRef.Value<long?>("descriptor_generation") ?? -1;
            var offset = payload.BufferRef.Value<long?>("offset") ?? -1;
            var size = payload.BufferRef.Value<long?>("content_length") ?? -1;
            var capacity = payload.BufferRef.Value<long?>("allocation_capacity_bytes") ?? -1;
            if (string.IsNullOrWhiteSpace(arenaId)
                || string.IsNullOrWhiteSpace(brokerEpoch)
                || descriptorIndex < 0
                || descriptorGeneration <= 0
                || offset < 0
                || size != payload.ContentLength
                || capacity < size)
            {
                throw new SharedMemoryTriggerException("protocol_error", "LocalBuffer result range is invalid.");
            }

            var guard = ByteRangeGuard.AcquireReader(
                mappingCache.GuardPath,
                mappingCache.ReaderGuardOffset(descriptorIndex),
                mappingCache.ReaderGuardSlots,
                localDeadline);
            mappingCache.ValidateActiveBufferRef(
                arenaId,
                brokerEpoch,
                descriptorIndex,
                descriptorGeneration,
                offset,
                size,
                capacity);
            var reader = new PhysicalPayloadReader(
                payload.PayloadId,
                payload.MediaType,
                mappingCache.ArenaPath,
                offset,
                size,
                payload.Width,
                payload.Height,
                payload.Shape,
                payload.DType,
                payload.Layout,
                payload.PixelFormat,
                guard);
            try
            {
                if (!string.Equals(payload.ChecksumAlgorithm, "crc32", StringComparison.OrdinalIgnoreCase))
                {
                    throw new SharedMemoryTriggerException("protocol_error", "LocalBuffer result checksum algorithm is not supported.");
                }

                uint expected;
                if (!uint.TryParse(payload.Checksum, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out expected))
                {
                    throw new SharedMemoryTriggerException("protocol_error", "LocalBuffer result checksum is invalid.");
                }

                var checksum = new Crc32Ieee();
                var checksumStartedAt = StartTiming(timings);
                using (var read = reader.OpenRead())
                {
                    var buffer = new byte[1024 * 1024];
                    int count;
                    while ((count = read.Read(buffer, 0, buffer.Length)) > 0)
                    {
                        checksum.Append(buffer, 0, count);
                    }
                }

                if (timings != null)
                {
                    timings.SdkChecksumMs += ElapsedMilliseconds(checksumStartedAt);
                }

                if (checksum.Value != expected)
                {
                    throw new SharedMemoryTriggerException("checksum_mismatch", "LocalBuffer result checksum mismatch.");
                }

                return reader;
            }
            catch
            {
                reader.Dispose();
                throw;
            }
        }

        private void ThrowResponseErrorAndAcknowledge(WorkflowTriggerMailboxResponse response)
        {
            string message = "Workflow Trigger returned an error.";
            try
            {
                var root = JObject.Parse(DecodeUtf8(response.Payload));
                message = root.Value<string>("error_message") ?? message;
            }
            finally
            {
                mailbox.Acknowledge(response.Identity);
            }

            throw new SharedMemoryTriggerException(MapErrorCode(response.ErrorCode), message);
        }

        private static string DecodeUtf8(ArraySegment<byte> payload)
        {
            if (payload.Array == null)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Workflow Trigger response payload is missing.");
            }
            return Encoding.UTF8.GetString(payload.Array, payload.Offset, payload.Count);
        }

        private void ReleaseResultAndAcknowledge(WorkflowTriggerDescriptorIdentity identity)
        {
            Exception? acknowledgeError = null;
            try
            {
                mailbox.Acknowledge(identity);
            }
            catch (Exception error)
            {
                acknowledgeError = error;
            }
            finally
            {
                lock (syncRoot)
                {
                    activeResultCount -= 1;
                    if (disposeRequested
                        && activeInvocationCount == 0
                        && activeResultCount == 0)
                    {
                        DisposeResourcesLocked();
                    }
                }
            }

            if (acknowledgeError != null)
            {
                throw acknowledgeError;
            }
        }

        private void BeginInvocation()
        {
            lock (syncRoot)
            {
                if (disposeRequested || mailboxDisposed)
                {
                    throw new ObjectDisposedException(nameof(SharedMemoryTriggerClient));
                }

                activeInvocationCount += 1;
            }
        }

        private void EndInvocation()
        {
            lock (syncRoot)
            {
                activeInvocationCount -= 1;
                if (activeInvocationCount < 0)
                {
                    throw new InvalidOperationException("Shared-memory Trigger active invocation count is invalid.");
                }

                if (disposeRequested
                    && activeInvocationCount == 0
                    && activeResultCount == 0)
                {
                    DisposeResourcesLocked();
                }
            }
        }

        private void DisposeResourcesLocked()
        {
            if (mailboxDisposed)
            {
                return;
            }

            mailboxDisposed = true;
            mappingCache.Dispose();
            mailbox.Dispose();
        }

        private void PausePoll(long waitStartedAt)
        {
            _ = waitStartedAt;
            // 本机 mailbox 的 publication 延迟远小于一次 Workflow 执行，但
            // SDK 不能为等待状态持续占用一个逻辑核。多个 TriggerSource 并发时
            // 忙轮询会和 Runtime/Broker 争抢 CPU 并放大 P99。Windows 进程已
            // 持有 1 ms timer resolution lease，因此按显式 PollInterval 阻塞等待
            // 只引入亚毫秒级平均观察延迟，同时保持 CPU 和尾延迟可预测。
            var milliseconds = Math.Max(1, (int)Math.Ceiling(options.PollInterval.TotalMilliseconds));
            Thread.Sleep(milliseconds);
        }

        private static IReadOnlyList<T> ParseList<T>(IDictionary<string, JToken> payload, string key)
        {
            if (!payload.TryGetValue(key, out var token) || token.Type == JTokenType.Null)
            {
                return Array.Empty<T>();
            }

            return WorkflowJsonDefaults.ToObject<List<T>>(token);
        }

        private static void ValidateAllocation(WorkflowTriggerAllocation allocation, long expectedSize)
        {
            if (!string.Equals(allocation.FormatId, "amvision.workflow-trigger-allocation.v1", StringComparison.Ordinal)
                || allocation.ContentLength != expectedSize
                || allocation.Offset < 0
                || allocation.AllocationCapacityBytes < allocation.ContentLength
                || string.IsNullOrWhiteSpace(allocation.ArenaId)
                || string.IsNullOrWhiteSpace(allocation.BrokerEpoch)
                || allocation.LayoutFingerprint == null
                || allocation.LayoutFingerprint.Length != 64
                || allocation.DescriptorIndex < 0
                || allocation.DescriptorGeneration <= 0)
            {
                throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger allocation does not match the requested image.");
            }
        }

        private static string MapErrorCode(int errorCode)
        {
            return errorCode switch
            {
                WorkflowTriggerMailboxV1.ErrorCodeTriggerSourceBusy => "trigger_source_busy",
                WorkflowTriggerMailboxV1.ErrorCodeWorkflowRuntimeBusy => "workflow_runtime_busy",
                WorkflowTriggerMailboxV1.ErrorCodeWorkflowExecutorBusy => "workflow_executor_busy",
                WorkflowTriggerMailboxV1.ErrorCodeLocalBufferCapacityExhausted => "local_buffer_capacity_exhausted",
                WorkflowTriggerMailboxV1.ErrorCodeDeadlineExceeded => "deadline_exceeded",
                WorkflowTriggerMailboxV1.ErrorCodeCancelled => "cancelled",
                WorkflowTriggerMailboxV1.ErrorCodeChecksumMismatch => "checksum_mismatch",
                WorkflowTriggerMailboxV1.ErrorCodeIdentityMismatch => "identity_mismatch",
                _ => "workflow_trigger_error_" + errorCode.ToString(CultureInfo.InvariantCulture)
            };
        }

        private static byte[] NormalizeBgr24(byte[] source, int width, int height, int rowStride)
        {
            if (source == null)
            {
                throw new ArgumentNullException(nameof(source));
            }

            var rowBytes = checked(width * 3);
            return NormalizeRows(source, height, rowStride, rowBytes, channels: 3);
        }

        private static byte[] ConvertMono8ToBgr24(byte[] source, int width, int height, int rowStride)
        {
            if (source == null)
            {
                throw new ArgumentNullException(nameof(source));
            }

            if (width <= 0 || height <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(width), "width and height must be positive.");
            }

            var stride = rowStride == 0 ? width : Math.Abs(rowStride);
            if (stride < width || source.LongLength < checked((long)stride * height))
            {
                throw new ArgumentException("Mono8 source does not contain the declared rows.", nameof(source));
            }

            var output = new byte[checked(width * height * 3)];
            for (var row = 0; row < height; row++)
            {
                var sourceRow = rowStride < 0 ? height - 1 - row : row;
                var sourceOffset = sourceRow * stride;
                var targetOffset = row * width * 3;
                for (var column = 0; column < width; column++)
                {
                    var value = source[sourceOffset + column];
                    output[targetOffset++] = value;
                    output[targetOffset++] = value;
                    output[targetOffset++] = value;
                }
            }

            return output;
        }

        private static byte[] NormalizeRows(byte[] source, int height, int rowStride, int rowBytes, int channels)
        {
            if (height <= 0 || rowBytes <= 0 || channels <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(height));
            }

            var stride = rowStride == 0 ? rowBytes : Math.Abs(rowStride);
            if (stride < rowBytes || source.LongLength < checked((long)stride * height))
            {
                throw new ArgumentException("Image source does not contain the declared rows.", nameof(source));
            }

            if (stride == rowBytes && rowStride >= 0 && source.Length == checked(rowBytes * height))
            {
                return source;
            }

            var output = new byte[checked(rowBytes * height)];
            for (var row = 0; row < height; row++)
            {
                var sourceRow = rowStride < 0 ? height - 1 - row : row;
                Buffer.BlockCopy(source, sourceRow * stride, output, row * rowBytes, rowBytes);
            }

            return output;
        }

        private static byte[] DecodeBase64(string value, out string? mediaType)
        {
            var normalized = RequireText(value, nameof(value));
            mediaType = null;
            var comma = normalized.IndexOf(',');
            if (normalized.StartsWith("data:", StringComparison.OrdinalIgnoreCase) && comma > 5)
            {
                var header = normalized.Substring(5, comma - 5);
                var separator = header.IndexOf(';');
                mediaType = (separator >= 0 ? header.Substring(0, separator) : header).Trim();
                normalized = normalized.Substring(comma + 1).Trim();
            }

            return Convert.FromBase64String(normalized);
        }

        private static string RequireText(string value, string parameterName)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                throw new ArgumentException(parameterName + " cannot be empty.", parameterName);
            }

            return value.Trim();
        }

        private static string? NormalizeOptional(string? value)
        {
            return string.IsNullOrWhiteSpace(value) ? null : value!.Trim();
        }

        private static SharedMemoryTriggerTimings? CreateTimings(SharedMemoryTriggerRequest? request)
        {
            if (request?.EnableTimings != true)
            {
                return null;
            }

            return new SharedMemoryTriggerTimings
            {
                InvokeStartedAtTicks = Stopwatch.GetTimestamp()
            };
        }

        private static long StartTiming(SharedMemoryTriggerTimings? timings)
        {
            return timings == null ? 0L : Stopwatch.GetTimestamp();
        }

        private static void RecordConversionTiming(
            SharedMemoryTriggerTimings? timings,
            long startedAt)
        {
            if (timings != null)
            {
                timings.SdkConvertToBgr24Ms += ElapsedMilliseconds(startedAt);
            }
        }

        private static double ElapsedMilliseconds(long startedAt)
        {
            return (Stopwatch.GetTimestamp() - startedAt) * 1000.0 / Stopwatch.Frequency;
        }
    }
}
