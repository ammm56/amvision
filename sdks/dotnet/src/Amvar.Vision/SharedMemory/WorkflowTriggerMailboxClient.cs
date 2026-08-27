using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.IO.MemoryMappedFiles;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace Amvar.Vision.SharedMemory
{
    internal sealed class WorkflowTriggerDescriptorIdentity
    {
        internal int DescriptorIndex { get; set; }
        internal ulong Generation { get; set; }
        internal ulong ServerEpoch { get; set; }
        internal Guid RequestId { get; set; }
        internal ulong OwnerToken { get; set; }
        internal ulong BackendDeadlineNs { get; set; }
    }

    internal sealed class WorkflowTriggerMailboxResponse
    {
        internal WorkflowTriggerDescriptorIdentity Identity { get; set; } = new WorkflowTriggerDescriptorIdentity();
        internal ArraySegment<byte> Payload { get; set; } = new ArraySegment<byte>(Array.Empty<byte>());
        internal int ErrorCode { get; set; }
        internal int OutputLeaseCount { get; set; }
        internal int HandoffState { get; set; }
        internal ulong ResponseAckDeadlineNs { get; set; }
    }

    internal sealed class WorkflowTriggerAllocationRead
    {
        internal WorkflowTriggerDescriptorIdentity Identity { get; set; } = new WorkflowTriggerDescriptorIdentity();
        internal byte[] Payload { get; set; } = Array.Empty<byte>();
    }

    internal sealed class WorkflowTriggerMailboxClient : IDisposable
    {
        private const string PrepareSchemaId = "amvision.workflow-trigger.prepare.v1";
        private const string AllocationSchemaId = "amvision.workflow-trigger.allocation.v1";
        private const string RequestSchemaId = "amvision.workflow-trigger.request.v1";
        private const string ResponseSchemaId = "amvision.workflow-trigger.response.v1";
        private static readonly byte[] Magic = { 0x41, 0x4d, 0x56, 0x4c, 0x4d, 0x53, 0x47, 0x00 };

        private readonly object accessSync = new object();
        private readonly string mailboxPath;
        private readonly string guardPath;
        private readonly FileStream mailboxFile;
        private readonly FileStream guardFile;
        private readonly MemoryMappedFile mailboxMap;
        private readonly MemoryMappedViewAccessor view;
        private readonly IDisposable timerResolutionLease;
        private bool disposed;

        internal WorkflowTriggerMailboxClient(string buffersRoot)
        {
            if (string.IsNullOrWhiteSpace(buffersRoot))
            {
                throw new ArgumentException("buffersRoot cannot be empty.", nameof(buffersRoot));
            }

            timerResolutionLease = WindowsLowLatencyTimer.Acquire();
            mailboxPath = Path.GetFullPath(Path.Combine(
                buffersRoot,
                WorkflowTriggerMailboxV1.RelativeMmapPath.Replace('/', Path.DirectorySeparatorChar)));
            guardPath = Path.GetFullPath(Path.Combine(
                buffersRoot,
                WorkflowTriggerMailboxV1.RelativeGuardPath.Replace('/', Path.DirectorySeparatorChar)));
            try
            {
                mailboxFile = new FileStream(
                    mailboxPath,
                    FileMode.Open,
                    FileAccess.ReadWrite,
                    FileShare.ReadWrite);
            }
            catch (Exception error)
            {
                timerResolutionLease.Dispose();
                throw new SharedMemoryTriggerException(
                    "server_unavailable",
                    "Workflow Trigger mailbox is not available.",
                    error);
            }

            if (mailboxFile.Length != WorkflowTriggerMailboxV1.MailboxFileSizeBytes)
            {
                mailboxFile.Dispose();
                timerResolutionLease.Dispose();
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Workflow Trigger mailbox size does not match the frozen profile.");
            }

            try
            {
                guardFile = new FileStream(
                    guardPath,
                    FileMode.Open,
                    FileAccess.ReadWrite,
                    FileShare.ReadWrite);
                if (guardFile.Length != WorkflowTriggerMailboxV1.DescriptorCount)
                {
                    throw new SharedMemoryTriggerException(
                        "protocol_error",
                        "Workflow Trigger guard size does not match the frozen profile.");
                }
                mailboxMap = MemoryMappedFile.CreateFromFile(
                    mailboxFile,
                    null,
                    0,
                    MemoryMappedFileAccess.ReadWrite,
                    HandleInheritability.None,
                    false);
                view = mailboxMap.CreateViewAccessor(
                    0,
                    WorkflowTriggerMailboxV1.MailboxFileSizeBytes,
                    MemoryMappedFileAccess.ReadWrite);
                ValidateHeader();
            }
            catch
            {
                guardFile?.Dispose();
                mailboxFile.Dispose();
                timerResolutionLease.Dispose();
                throw;
            }
        }

        internal ulong ServerEpoch
        {
            get
            {
                lock (accessSync)
                {
                    ThrowIfDisposed();
                    return ServerEpochUnsafe();
                }
            }
        }

        internal WorkflowTriggerDescriptorIdentity Claim(
            uint timeoutMs,
            ulong routeGeneration,
            byte[] preparePayload,
            Guid requestId)
        {
            if (timeoutMs == 0)
            {
                throw new ArgumentOutOfRangeException(nameof(timeoutMs));
            }

            var wireBytes = EncodeEnvelope(PrepareSchemaId, preparePayload, requestId);
            if (wireBytes.Length > WorkflowTriggerMailboxV1.MaxRequestBytes)
            {
                throw new SharedMemoryTriggerException(
                    "trigger_request_too_large",
                    "Workflow Trigger PREPARE envelope exceeds 64 KiB.");
            }

            var ownerToken = CreateNonZeroToken();
            for (var descriptorIndex = 0;
                descriptorIndex < WorkflowTriggerMailboxV1.DescriptorCount;
                descriptorIndex++)
            {
                lock (accessSync)
                {
                    ThrowIfDisposed();
                    VerifyOwnerReady();
                    if (ReadInt32(DescriptorOffset(descriptorIndex))
                        != WorkflowTriggerMailboxV1.MailboxStateFree)
                    {
                        continue;
                    }
                }

                using (var guard = ByteRangeGuard.TryAcquire(
                    guardPath,
                    descriptorIndex,
                    1))
                {
                    if (guard == null)
                    {
                        continue;
                    }

                    lock (accessSync)
                    {
                        ThrowIfDisposed();
                        VerifyOwnerReady();
                        var descriptorOffset = DescriptorOffset(descriptorIndex);
                        if (ReadInt32(descriptorOffset)
                            != WorkflowTriggerMailboxV1.MailboxStateFree)
                        {
                            continue;
                        }

                        var generation = unchecked(
                            ReadUInt64(
                                descriptorOffset
                                + WorkflowTriggerMailboxV1.DescriptorGenerationOffset)
                            + 1UL);
                        if (generation == 0)
                        {
                            generation = 1;
                        }

                        var header = new byte[WorkflowTriggerMailboxV1.DescriptorHeaderSize];
                        view.WriteArray(descriptorOffset, header, 0, header.Length);
                        WriteInt32(
                            descriptorOffset + WorkflowTriggerMailboxV1.DescriptorStateOffset,
                            WorkflowTriggerMailboxV1.MailboxStateWritingRequest);
                        WriteUInt64(
                            descriptorOffset + WorkflowTriggerMailboxV1.DescriptorGenerationOffset,
                            generation);
                        var serverEpoch = ServerEpochUnsafe();
                        WriteUInt64(
                            descriptorOffset + WorkflowTriggerMailboxV1.DescriptorOwnerEpochOffset,
                            serverEpoch);
                        WriteGuidNetworkOrder(
                            descriptorOffset + WorkflowTriggerMailboxV1.DescriptorRequestIdOffset,
                            requestId);
                        WriteUInt64(
                            descriptorOffset + WorkflowTriggerMailboxV1.DescriptorOwnerTokenOffset,
                            ownerToken);
                        WriteUInt64(
                            descriptorOffset + WorkflowTriggerMailboxV1.DescriptorDeadlineNsOffset,
                            ulong.MaxValue);
                        WriteInt32(
                            descriptorOffset + WorkflowTriggerMailboxV1.DescriptorRequestSizeOffset,
                            wireBytes.Length);
                        WriteUInt32(
                            descriptorOffset + WorkflowTriggerMailboxV1.DescriptorRequestChecksumOffset,
                            Crc32Ieee.Compute(wireBytes));
                        WriteInt32(
                            descriptorOffset + WorkflowTriggerMailboxV1.DescriptorFirstPageIndexOffset,
                            -1);
                        WriteInt32(
                            descriptorOffset + WorkflowTriggerMailboxV1.ExtensionPhaseOffset,
                            WorkflowTriggerMailboxV1.PhasePrepare);
                        WriteUInt32(
                            descriptorOffset
                            + WorkflowTriggerMailboxV1.ExtensionRequestedTimeoutMsOffset,
                            timeoutMs);
                        WriteUInt64(
                            descriptorOffset
                            + WorkflowTriggerMailboxV1.ExtensionRouteGenerationOffset,
                            routeGeneration);
                        WriteUInt64(
                            descriptorOffset + WorkflowTriggerMailboxV1.DescriptorUpdatedAtNsOffset,
                            MonotonicNanoseconds());
                        view.WriteArray(
                            InlineRequestOffset(descriptorIndex),
                            wireBytes,
                            0,
                            wireBytes.Length);
                        Thread.MemoryBarrier();
                        WriteInt32(
                            descriptorOffset + WorkflowTriggerMailboxV1.DescriptorStateOffset,
                            WorkflowTriggerMailboxV1.MailboxStateRequest);
                        return new WorkflowTriggerDescriptorIdentity
                        {
                            DescriptorIndex = descriptorIndex,
                            Generation = generation,
                            ServerEpoch = serverEpoch,
                            RequestId = requestId,
                            OwnerToken = ownerToken,
                            BackendDeadlineNs = 0
                        };
                    }
                }
            }

            throw new SharedMemoryTriggerException(
                "trigger_source_busy",
                "Workflow Trigger mailbox descriptors are full.");
        }

        internal WorkflowTriggerAllocationRead? TryReadAllocation(
            WorkflowTriggerDescriptorIdentity claimedIdentity)
        {
            lock (accessSync)
            {
                ThrowIfDisposed();
                VerifyOwnerReady();
                var state = ReadInt32(DescriptorOffset(claimedIdentity.DescriptorIndex));
                if (state != WorkflowTriggerMailboxV1.MailboxStateResponse)
                {
                    return null;
                }
            }

            using (var guard = ByteRangeGuard.TryAcquire(
                guardPath,
                claimedIdentity.DescriptorIndex,
                1))
            {
                if (guard == null)
                {
                    return null;
                }

                lock (accessSync)
                {
                    ThrowIfDisposed();
                    VerifyOwnerReady();
                    var current = RequireIdentity(claimedIdentity, true);
                    var descriptorOffset = DescriptorOffset(current.DescriptorIndex);
                    if (ReadInt32(descriptorOffset)
                        != WorkflowTriggerMailboxV1.MailboxStateResponse)
                    {
                        return null;
                    }

                    var phase = ReadInt32(
                        descriptorOffset + WorkflowTriggerMailboxV1.ExtensionPhaseOffset);
                    var transportError = ReadInt32(
                        descriptorOffset
                        + WorkflowTriggerMailboxV1.DescriptorTransportErrorCodeOffset);
                    if (phase != WorkflowTriggerMailboxV1.PhaseWriting
                        || transportError != WorkflowTriggerMailboxV1.MailboxErrorNone)
                    {
                        return null;
                    }

                    var wireBytes = ReadResponseWireBytes(current);
                    var payload = DecodeEnvelope(
                        AllocationSchemaId,
                        wireBytes,
                        current.RequestId);
                    if (ReadInt32(
                        descriptorOffset
                        + WorkflowTriggerMailboxV1.DescriptorResponsePageCountOffset) != 0)
                    {
                        throw new SharedMemoryTriggerException(
                            "protocol_error",
                            "Workflow Trigger allocation must remain inline.");
                    }

                    ReopenForWriting(descriptorOffset);
                    return new WorkflowTriggerAllocationRead
                    {
                        Identity = current,
                        Payload = payload
                    };
                }
            }
        }

        internal void PublishRequest(
            WorkflowTriggerDescriptorIdentity identity,
            byte[] payload)
        {
            var wireBytes = EncodeEnvelope(RequestSchemaId, payload, identity.RequestId);
            if (wireBytes.Length > WorkflowTriggerMailboxV1.MaxRequestBytes)
            {
                throw new SharedMemoryTriggerException(
                    "trigger_request_too_large",
                    "Workflow Trigger request envelope exceeds 64 KiB.");
            }

            using (var guard = ByteRangeGuard.Acquire(
                guardPath,
                identity.DescriptorIndex,
                1,
                LocalDeadline(TimeSpan.FromSeconds(5))))
            {
                lock (accessSync)
                {
                    ThrowIfDisposed();
                    VerifyOwnerReady();
                    RequireState(identity, WorkflowTriggerMailboxV1.MailboxStateWritingRequest);
                    var descriptorOffset = DescriptorOffset(identity.DescriptorIndex);
                    if (ReadInt32(
                        descriptorOffset + WorkflowTriggerMailboxV1.DescriptorFlagsOffset)
                        != 0)
                    {
                        throw new SharedMemoryTriggerException(
                            "cancelled",
                            "Workflow Trigger request was cancelled.");
                    }

                    WriteInt32(
                        descriptorOffset + WorkflowTriggerMailboxV1.DescriptorRequestSizeOffset,
                        wireBytes.Length);
                    WriteUInt32(
                        descriptorOffset
                        + WorkflowTriggerMailboxV1.DescriptorRequestChecksumOffset,
                        Crc32Ieee.Compute(wireBytes));
                    WriteInt32(
                        descriptorOffset + WorkflowTriggerMailboxV1.ExtensionPhaseOffset,
                        WorkflowTriggerMailboxV1.PhaseRequest);
                    view.WriteArray(
                        InlineRequestOffset(identity.DescriptorIndex),
                        wireBytes,
                        0,
                        wireBytes.Length);
                    Thread.MemoryBarrier();
                    WriteInt32(
                        descriptorOffset + WorkflowTriggerMailboxV1.DescriptorStateOffset,
                        WorkflowTriggerMailboxV1.MailboxStateRequest);
                }
            }
        }

        internal WorkflowTriggerMailboxResponse? TryReadResponse(
            WorkflowTriggerDescriptorIdentity identity)
        {
            lock (accessSync)
            {
                ThrowIfDisposed();
                VerifyOwnerReady();
                if (ReadInt32(DescriptorOffset(identity.DescriptorIndex))
                    != WorkflowTriggerMailboxV1.MailboxStateResponse)
                {
                    return null;
                }
            }

            using (var guard = ByteRangeGuard.TryAcquire(
                guardPath,
                identity.DescriptorIndex,
                1))
            {
                if (guard == null)
                {
                    return null;
                }

                lock (accessSync)
                {
                    ThrowIfDisposed();
                    VerifyOwnerReady();
                    var current = RequireIdentity(identity, true);
                    var descriptorOffset = DescriptorOffset(identity.DescriptorIndex);
                    if (ReadInt32(descriptorOffset)
                        != WorkflowTriggerMailboxV1.MailboxStateResponse)
                    {
                        return null;
                    }

                    var phase = ReadInt32(
                        descriptorOffset + WorkflowTriggerMailboxV1.ExtensionPhaseOffset);
                    var transportError = ReadInt32(
                        descriptorOffset
                        + WorkflowTriggerMailboxV1.DescriptorTransportErrorCodeOffset);
                    if (phase == WorkflowTriggerMailboxV1.PhaseWriting
                        && transportError == WorkflowTriggerMailboxV1.MailboxErrorNone)
                    {
                        return null;
                    }

                    int businessError;
                    ArraySegment<byte> payload;
                    if (transportError != WorkflowTriggerMailboxV1.MailboxErrorNone)
                    {
                        businessError = BusinessErrorFromTransport(transportError);
                        payload = new ArraySegment<byte>(Encoding.UTF8.GetBytes(
                            "{\"state\":\"failed\",\"error_code\":"
                            + businessError.ToString(System.Globalization.CultureInfo.InvariantCulture)
                            + "}"));
                    }
                    else
                    {
                        businessError = ReadInt32(
                            descriptorOffset + WorkflowTriggerMailboxV1.ExtensionErrorCodeOffset);
                        payload = DecodeEnvelopeSegment(
                            ResponseSchemaId,
                            ReadResponseWireBytes(current),
                            current.RequestId);
                    }

                    return new WorkflowTriggerMailboxResponse
                    {
                        Identity = current,
                        Payload = payload,
                        ErrorCode = businessError,
                        OutputLeaseCount = ReadInt32(
                            descriptorOffset
                            + WorkflowTriggerMailboxV1.ExtensionOutputLeaseCountOffset),
                        HandoffState = ReadInt32(
                            descriptorOffset
                            + WorkflowTriggerMailboxV1.ExtensionHandoffStateOffset),
                        ResponseAckDeadlineNs = ReadUInt64(
                            descriptorOffset
                            + WorkflowTriggerMailboxV1.DescriptorResponseAckDeadlineNsOffset)
                    };
                }
            }
        }

        internal void Acknowledge(WorkflowTriggerDescriptorIdentity identity)
        {
            var reclaimDeadline = LocalDeadline(TimeSpan.FromSeconds(5));
            using (var guard = ByteRangeGuard.Acquire(
                guardPath,
                identity.DescriptorIndex,
                1,
                reclaimDeadline))
            {
                lock (accessSync)
                {
                    ThrowIfDisposed();
                    VerifyOwnerReady();
                    RequireState(identity, WorkflowTriggerMailboxV1.MailboxStateResponse);
                    var flagsOffset = DescriptorOffset(identity.DescriptorIndex)
                        + WorkflowTriggerMailboxV1.DescriptorFlagsOffset;
                    WriteInt32(
                        flagsOffset,
                        ReadInt32(flagsOffset) | WorkflowTriggerMailboxV1.MailboxFlagAcked);
                }
            }

            WaitForReclaim(identity, reclaimDeadline);
        }

        internal void Cancel(
            WorkflowTriggerDescriptorIdentity identity,
            int reason = WorkflowTriggerMailboxV1.CancelReasonExplicit)
        {
            if (reason != WorkflowTriggerMailboxV1.CancelReasonRequestTimeout
                && reason != WorkflowTriggerMailboxV1.CancelReasonExplicit
                && reason != WorkflowTriggerMailboxV1.CancelReasonClientShutdown)
            {
                throw new ArgumentOutOfRangeException(nameof(reason));
            }

            using (var guard = ByteRangeGuard.Acquire(
                guardPath,
                identity.DescriptorIndex,
                1,
                LocalDeadline(TimeSpan.FromSeconds(2))))
            {
                lock (accessSync)
                {
                    ThrowIfDisposed();
                    VerifyOwnerReady();
                    var current = RequireIdentity(identity, true);
                    var descriptorOffset = DescriptorOffset(current.DescriptorIndex);
                    var state = ReadInt32(descriptorOffset);
                    if (state == WorkflowTriggerMailboxV1.MailboxStateFree)
                    {
                        return;
                    }

                    if (ReadInt32(
                        descriptorOffset
                        + WorkflowTriggerMailboxV1.ExtensionCancelReasonOffset)
                        == WorkflowTriggerMailboxV1.CancelReasonNone)
                    {
                        WriteInt32(
                            descriptorOffset
                            + WorkflowTriggerMailboxV1.ExtensionCancelReasonOffset,
                            reason);
                    }

                    var flagsOffset = descriptorOffset
                        + WorkflowTriggerMailboxV1.DescriptorFlagsOffset;
                    WriteInt32(
                        flagsOffset,
                        ReadInt32(flagsOffset)
                        | WorkflowTriggerMailboxV1.MailboxFlagCancelRequested);
                }
            }
        }

        internal bool IsResponseCurrent(WorkflowTriggerDescriptorIdentity identity)
        {
            using (var guard = ByteRangeGuard.TryAcquire(
                guardPath,
                identity.DescriptorIndex,
                1))
            {
                if (guard == null)
                {
                    return false;
                }

                lock (accessSync)
                {
                    try
                    {
                        VerifyOwnerReady();
                        RequireState(identity, WorkflowTriggerMailboxV1.MailboxStateResponse);
                        return true;
                    }
                    catch (SharedMemoryTriggerException)
                    {
                        return false;
                    }
                }
            }
        }

        public void Dispose()
        {
            lock (accessSync)
            {
                if (disposed)
                {
                    return;
                }

                disposed = true;
                view.Dispose();
                mailboxMap.Dispose();
                mailboxFile.Dispose();
                guardFile.Dispose();
                timerResolutionLease.Dispose();
            }
        }

        private void ReopenForWriting(long descriptorOffset)
        {
            WriteInt32(
                descriptorOffset + WorkflowTriggerMailboxV1.DescriptorFlagsOffset,
                0);
            WriteInt32(
                descriptorOffset + WorkflowTriggerMailboxV1.DescriptorRequestSizeOffset,
                0);
            WriteUInt32(
                descriptorOffset + WorkflowTriggerMailboxV1.DescriptorRequestChecksumOffset,
                0);
            WriteInt32(
                descriptorOffset + WorkflowTriggerMailboxV1.DescriptorResponseRawSizeOffset,
                0);
            WriteUInt32(
                descriptorOffset + WorkflowTriggerMailboxV1.DescriptorResponseChecksumOffset,
                0);
            WriteInt32(
                descriptorOffset + WorkflowTriggerMailboxV1.DescriptorFirstPageIndexOffset,
                -1);
            WriteInt32(
                descriptorOffset + WorkflowTriggerMailboxV1.DescriptorResponsePageCountOffset,
                0);
            WriteInt32(
                descriptorOffset
                + WorkflowTriggerMailboxV1.DescriptorTransportErrorCodeOffset,
                WorkflowTriggerMailboxV1.MailboxErrorNone);
            WriteInt32(
                descriptorOffset + WorkflowTriggerMailboxV1.DescriptorResponseStoredSizeOffset,
                0);
            WriteUInt64(
                descriptorOffset
                + WorkflowTriggerMailboxV1.DescriptorResponseAckDeadlineNsOffset,
                0);
            WriteInt32(
                descriptorOffset + WorkflowTriggerMailboxV1.ExtensionPhaseOffset,
                WorkflowTriggerMailboxV1.PhaseWriting);
            Thread.MemoryBarrier();
            WriteInt32(
                descriptorOffset + WorkflowTriggerMailboxV1.DescriptorStateOffset,
                WorkflowTriggerMailboxV1.MailboxStateWritingRequest);
        }

        private byte[] ReadResponseWireBytes(WorkflowTriggerDescriptorIdentity identity)
        {
            var descriptorOffset = DescriptorOffset(identity.DescriptorIndex);
            var rawSize = ReadBoundedSize(
                descriptorOffset
                + WorkflowTriggerMailboxV1.DescriptorResponseRawSizeOffset,
                WorkflowTriggerMailboxV1.MaxResponseBytes);
            var storedSize = ReadBoundedSize(
                descriptorOffset
                + WorkflowTriggerMailboxV1.DescriptorResponseStoredSizeOffset,
                WorkflowTriggerMailboxV1.MaxResponseBytes);
            var pageCount = ReadInt32(
                descriptorOffset
                + WorkflowTriggerMailboxV1.DescriptorResponsePageCountOffset);
            byte[] stored;
            if (pageCount == 0)
            {
                if (storedSize > WorkflowTriggerMailboxV1.InlineResponseCapacityBytes)
                {
                    throw new SharedMemoryTriggerException(
                        "protocol_error",
                        "Workflow Trigger inline response exceeds its capacity.");
                }

                stored = new byte[storedSize];
                view.ReadArray(
                    InlineResponseOffset(identity.DescriptorIndex),
                    stored,
                    0,
                    stored.Length);
            }
            else
            {
                stored = ReadPageChain(identity, storedSize, pageCount);
            }

            var flags = ReadInt32(
                descriptorOffset + WorkflowTriggerMailboxV1.DescriptorFlagsOffset);
            var payload = (flags & WorkflowTriggerMailboxV1.MailboxFlagResponseCompressed) != 0
                ? ZlibCodec.Decompress(stored, rawSize)
                : stored;
            if (payload.Length != rawSize
                || Crc32Ieee.Compute(payload)
                    != ReadUInt32(
                        descriptorOffset
                        + WorkflowTriggerMailboxV1.DescriptorResponseChecksumOffset))
            {
                throw new SharedMemoryTriggerException(
                    "checksum_mismatch",
                    "Workflow Trigger response length or checksum mismatch.");
            }

            return payload;
        }

        private byte[] ReadPageChain(
            WorkflowTriggerDescriptorIdentity identity,
            int storedSize,
            int pageCount)
        {
            if (pageCount <= 0
                || pageCount > WorkflowTriggerMailboxV1.MaxOverflowPagesPerResponse)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Workflow Trigger response page count is invalid.");
            }

            var result = new byte[storedSize];
            var written = 0;
            var descriptorOffset = DescriptorOffset(identity.DescriptorIndex);
            var pageIndex = ReadInt32(
                descriptorOffset
                + WorkflowTriggerMailboxV1.DescriptorFirstPageIndexOffset);
            var visited = new HashSet<int>();
            for (var ordinal = 0; ordinal < pageCount; ordinal++)
            {
                if (pageIndex < 0
                    || pageIndex >= WorkflowTriggerMailboxV1.OverflowPageCount
                    || !visited.Add(pageIndex))
                {
                    throw new SharedMemoryTriggerException(
                        "protocol_error",
                        "Workflow Trigger response page-chain is invalid.");
                }

                var pageOffset = PageOffset(pageIndex);
                if (ReadInt32(pageOffset + WorkflowTriggerMailboxV1.PageStateOffset)
                        != WorkflowTriggerMailboxV1.PageStatePublished
                    || ReadInt32(
                        pageOffset
                        + WorkflowTriggerMailboxV1.PageDescriptorIndexOffset)
                        != identity.DescriptorIndex
                    || ReadUInt64(
                        pageOffset
                        + WorkflowTriggerMailboxV1.PageDescriptorGenerationOffset)
                        != identity.Generation
                    || ReadInt32(pageOffset + WorkflowTriggerMailboxV1.PageOrdinalOffset)
                        != ordinal
                    || ReadUInt64(pageOffset + WorkflowTriggerMailboxV1.PageTokenOffset) == 0
                    || ReadUInt64(pageOffset + WorkflowTriggerMailboxV1.PageOwnerEpochOffset)
                        != identity.ServerEpoch)
                {
                    throw new SharedMemoryTriggerException(
                        "identity_mismatch",
                        "Workflow Trigger response page identity mismatch.");
                }

                var used = ReadBoundedSize(
                    pageOffset + WorkflowTriggerMailboxV1.PageUsedSizeOffset,
                    WorkflowTriggerMailboxV1.OverflowPageCapacityBytes);
                if (used <= 0 || written > result.Length - used)
                {
                    throw new SharedMemoryTriggerException(
                        "protocol_error",
                        "Workflow Trigger page-chain exceeds declared size.");
                }

                var chunk = new byte[used];
                view.ReadArray(
                    pageOffset + WorkflowTriggerMailboxV1.PageHeaderSize,
                    chunk,
                    0,
                    chunk.Length);
                if (Crc32Ieee.Compute(chunk)
                    != ReadUInt32(pageOffset + WorkflowTriggerMailboxV1.PageChecksumOffset))
                {
                    throw new SharedMemoryTriggerException(
                        "checksum_mismatch",
                        "Workflow Trigger response page checksum mismatch.");
                }

                Buffer.BlockCopy(chunk, 0, result, written, chunk.Length);
                written += chunk.Length;
                pageIndex = ReadInt32(
                    pageOffset + WorkflowTriggerMailboxV1.PageNextPageIndexOffset);
            }

            if (written != result.Length || pageIndex != -1)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Workflow Trigger response page total length mismatch.");
            }

            return result;
        }

        private void WaitForReclaim(
            WorkflowTriggerDescriptorIdentity identity,
            long localDeadlineTicks)
        {
            while (Stopwatch.GetTimestamp() < localDeadlineTicks)
            {
                lock (accessSync)
                {
                    ThrowIfDisposed();
                    var descriptorOffset = DescriptorOffset(identity.DescriptorIndex);
                    var state = ReadInt32(descriptorOffset);
                    var generation = ReadUInt64(
                        descriptorOffset
                        + WorkflowTriggerMailboxV1.DescriptorGenerationOffset);
                    if (ServerEpochUnsafe() != identity.ServerEpoch
                        || generation != identity.Generation
                        || state == WorkflowTriggerMailboxV1.MailboxStateFree)
                    {
                        return;
                    }
                }

                Thread.Sleep(1);
            }

            throw new SharedMemoryTriggerException(
                "timeout",
                "Timed out waiting for Workflow Trigger ACK reclaim.");
        }

        private WorkflowTriggerDescriptorIdentity RequireIdentity(
            WorkflowTriggerDescriptorIdentity expected,
            bool allowUnacceptedDeadline)
        {
            var current = ReadIdentity(expected.DescriptorIndex);
            var stable = current.DescriptorIndex == expected.DescriptorIndex
                && current.Generation == expected.Generation
                && current.ServerEpoch == expected.ServerEpoch
                && current.RequestId == expected.RequestId
                && current.OwnerToken == expected.OwnerToken;
            var deadlineMatches = current.BackendDeadlineNs == expected.BackendDeadlineNs
                || (allowUnacceptedDeadline && expected.BackendDeadlineNs == 0);
            if (!stable || !deadlineMatches)
            {
                throw new SharedMemoryTriggerException(
                    "identity_mismatch",
                    "Workflow Trigger descriptor identity changed.");
            }

            return current;
        }

        private void RequireState(
            WorkflowTriggerDescriptorIdentity identity,
            int expectedState)
        {
            RequireIdentity(identity, false);
            if (ReadInt32(DescriptorOffset(identity.DescriptorIndex)) != expectedState)
            {
                throw new SharedMemoryTriggerException(
                    "identity_mismatch",
                    "Workflow Trigger descriptor state changed.");
            }
        }

        private WorkflowTriggerDescriptorIdentity ReadIdentity(int descriptorIndex)
        {
            var descriptorOffset = DescriptorOffset(descriptorIndex);
            return new WorkflowTriggerDescriptorIdentity
            {
                DescriptorIndex = descriptorIndex,
                Generation = ReadUInt64(
                    descriptorOffset + WorkflowTriggerMailboxV1.DescriptorGenerationOffset),
                ServerEpoch = ReadUInt64(
                    descriptorOffset + WorkflowTriggerMailboxV1.DescriptorOwnerEpochOffset),
                RequestId = ReadGuidNetworkOrder(
                    descriptorOffset + WorkflowTriggerMailboxV1.DescriptorRequestIdOffset),
                OwnerToken = ReadUInt64(
                    descriptorOffset + WorkflowTriggerMailboxV1.DescriptorOwnerTokenOffset),
                BackendDeadlineNs = ReadUInt64(
                    descriptorOffset + WorkflowTriggerMailboxV1.DescriptorDeadlineNsOffset)
            };
        }

        private void ValidateHeader()
        {
            lock (accessSync)
            {
                var magic = new byte[Magic.Length];
                view.ReadArray(
                    WorkflowTriggerMailboxV1.CommonMagicOffset,
                    magic,
                    0,
                    magic.Length);
                if (!EqualBytes(magic, Magic)
                    || ReadUInt16(WorkflowTriggerMailboxV1.CommonVersionOffset)
                        != WorkflowTriggerMailboxV1.Version
                    || ReadUInt16(WorkflowTriggerMailboxV1.CommonChannelKindOffset)
                        != WorkflowTriggerMailboxV1.ChannelKindMailbox
                    || ReadInt32(WorkflowTriggerMailboxV1.CommonEndianOffset)
                        != WorkflowTriggerMailboxV1.EndianMarker)
                {
                    throw new SharedMemoryTriggerException(
                        "protocol_error",
                        "Workflow Trigger common header does not match LocalMessage v1.");
                }

                var fingerprint = new byte[32];
                view.ReadArray(
                    WorkflowTriggerMailboxV1.CommonFingerprintOffset,
                    fingerprint,
                    0,
                    fingerprint.Length);
                if (!EqualBytes(
                    fingerprint,
                    HexBytes(WorkflowTriggerMailboxV1.LayoutFingerprintHex)))
                {
                    throw new SharedMemoryTriggerException(
                        "protocol_error",
                        "Workflow Trigger layout fingerprint does not match.");
                }

                if (ReadInt32(WorkflowTriggerMailboxV1.CommonFlagsOffset)
                        != 0
                    || ReadUInt64(WorkflowTriggerMailboxV1.CommonOwnerEpochOffset) == 0
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxDescriptorCountOffset)
                        != WorkflowTriggerMailboxV1.DescriptorCount
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxDescriptorHeaderSizeOffset)
                        != WorkflowTriggerMailboxV1.DescriptorHeaderSize
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxDescriptorStrideOffset)
                        != WorkflowTriggerMailboxV1.DescriptorStrideBytes
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxInlineRequestCapacityOffset)
                        != WorkflowTriggerMailboxV1.InlineRequestCapacityBytes
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxInlineResponseCapacityOffset)
                        != WorkflowTriggerMailboxV1.InlineResponseCapacityBytes
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxPageHeaderSizeOffset)
                        != WorkflowTriggerMailboxV1.PageHeaderSize
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxPageCapacityOffset)
                        != WorkflowTriggerMailboxV1.OverflowPageCapacityBytes
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxPageCountOffset)
                        != WorkflowTriggerMailboxV1.OverflowPageCount
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxMaxPagesPerResponseOffset)
                        != WorkflowTriggerMailboxV1.MaxOverflowPagesPerResponse
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxMaxRequestBytesOffset)
                        != WorkflowTriggerMailboxV1.MaxRequestBytes
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxMaxResponseBytesOffset)
                        != WorkflowTriggerMailboxV1.MaxResponseBytes
                    || ReadInt32(WorkflowTriggerMailboxV1.MailboxCompressionThresholdOffset)
                        != WorkflowTriggerMailboxV1.CompressionThresholdBytes
                    || ReadUInt64(WorkflowTriggerMailboxV1.MailboxDescriptorRegionOffset)
                        != (ulong)WorkflowTriggerMailboxV1.DescriptorRegionOffset
                    || ReadUInt64(WorkflowTriggerMailboxV1.MailboxPageRegionOffset)
                        != (ulong)WorkflowTriggerMailboxV1.PageRegionOffset
                    || ReadUInt64(WorkflowTriggerMailboxV1.MailboxFileSizeOffset)
                        != (ulong)WorkflowTriggerMailboxV1.MailboxFileSizeBytes
                    || ReadFixedAscii(
                        WorkflowTriggerMailboxV1.MailboxProfileIdOffset,
                        64) != WorkflowTriggerMailboxV1.ProfileId)
                {
                    throw new SharedMemoryTriggerException(
                        "protocol_error",
                        "Workflow Trigger Mailbox profile header does not match.");
                }
            }
        }

        private void VerifyOwnerReady()
        {
            if (ServerEpochUnsafe() == 0
                || (ReadInt32(WorkflowTriggerMailboxV1.CommonFlagsOffset)
                    & WorkflowTriggerMailboxV1.FileFlagClosed) != 0)
            {
                throw new SharedMemoryTriggerException(
                    "server_unavailable",
                    "Workflow Trigger owner is closed.");
            }
        }

        private static byte[] EncodeEnvelope(
            string schemaId,
            byte[] payload,
            Guid requestId)
        {
            if (payload == null)
            {
                throw new ArgumentNullException(nameof(payload));
            }

            try
            {
                var first = 0;
                while (first < payload.Length && IsJsonWhitespace(payload[first]))
                {
                    first++;
                }
                var last = payload.Length - 1;
                while (last >= first && IsJsonWhitespace(payload[last]))
                {
                    last--;
                }
                if (last - first + 1 < 2
                    || payload[first] != (byte)'{'
                    || payload[last] != (byte)'}')
                {
                    throw new FormatException("payload is not a JSON object");
                }

                var prefix = EnvelopePrefix(schemaId);
                var suffix = EnvelopeSuffix(requestId);
                var payloadLength = last - first + 1;
                var wireBytes = new byte[prefix.Length + payloadLength + suffix.Length];
                Buffer.BlockCopy(prefix, 0, wireBytes, 0, prefix.Length);
                Buffer.BlockCopy(payload, first, wireBytes, prefix.Length, payloadLength);
                Buffer.BlockCopy(
                    suffix,
                    0,
                    wireBytes,
                    prefix.Length + payloadLength,
                    suffix.Length);
                return wireBytes;
            }
            catch (Exception error)
            {
                throw new SharedMemoryTriggerException(
                    "invalid_request",
                    "Workflow Trigger payload is not valid JSON.",
                    error);
            }
        }

        private static byte[] DecodeEnvelope(
            string expectedSchemaId,
            byte[] wireBytes,
            Guid requestId)
        {
            var segment = DecodeEnvelopeSegment(expectedSchemaId, wireBytes, requestId);
            var payload = new byte[segment.Count];
            if (segment.Array != null)
            {
                Buffer.BlockCopy(segment.Array, segment.Offset, payload, 0, segment.Count);
            }
            return payload;
        }

        private static ArraySegment<byte> DecodeEnvelopeSegment(
            string expectedSchemaId,
            byte[] wireBytes,
            Guid requestId)
        {
            try
            {
                var prefix = EnvelopePrefix(expectedSchemaId);
                var suffix = EnvelopeSuffix(requestId);
                var payloadLength = wireBytes.Length - prefix.Length - suffix.Length;
                if (payloadLength < 2
                    || !MatchesAt(wireBytes, prefix, 0)
                    || !MatchesAt(wireBytes, suffix, prefix.Length + payloadLength)
                    || wireBytes[prefix.Length] != (byte)'{'
                    || wireBytes[prefix.Length + payloadLength - 1] != (byte)'}')
                {
                    throw new FormatException("envelope identity does not match");
                }

                return new ArraySegment<byte>(wireBytes, prefix.Length, payloadLength);
            }
            catch (Exception error)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Workflow Trigger envelope is invalid.",
                    error);
            }
        }

        private static byte[] EnvelopePrefix(string schemaId)
        {
            return Encoding.UTF8.GetBytes(
                "{\"schema_id\":\"" + schemaId + "\",\"payload\":");
        }

        private static byte[] EnvelopeSuffix(Guid requestId)
        {
            return Encoding.UTF8.GetBytes(
                ",\"correlation_id\":\"" + requestId.ToString("D") + "\"}");
        }

        private static bool MatchesAt(byte[] content, byte[] expected, int offset)
        {
            if (offset < 0 || offset + expected.Length > content.Length)
            {
                return false;
            }
            for (var index = 0; index < expected.Length; index++)
            {
                if (content[offset + index] != expected[index])
                {
                    return false;
                }
            }
            return true;
        }

        private static bool IsJsonWhitespace(byte value)
        {
            return value == 0x20 || value == 0x09 || value == 0x0A || value == 0x0D;
        }

        private static int BusinessErrorFromTransport(int errorCode)
        {
            switch (errorCode)
            {
                case WorkflowTriggerMailboxV1.MailboxErrorDeadlineExceeded:
                    return WorkflowTriggerMailboxV1.ErrorCodeDeadlineExceeded;
                case WorkflowTriggerMailboxV1.MailboxErrorCancelled:
                    return WorkflowTriggerMailboxV1.ErrorCodeCancelled;
                case WorkflowTriggerMailboxV1.MailboxErrorInvalidMessage:
                    return WorkflowTriggerMailboxV1.ErrorCodeChecksumMismatch;
                case WorkflowTriggerMailboxV1.MailboxErrorCapacityExhausted:
                    return WorkflowTriggerMailboxV1.ErrorCodeTriggerResponseCapacityExhausted;
                default:
                    return WorkflowTriggerMailboxV1.ErrorCodeProtocolError;
            }
        }

        private static bool EqualBytes(byte[] left, byte[] right)
        {
            if (left.Length != right.Length)
            {
                return false;
            }

            for (var index = 0; index < left.Length; index++)
            {
                if (left[index] != right[index])
                {
                    return false;
                }
            }

            return true;
        }

        private static byte[] HexBytes(string value)
        {
            var bytes = new byte[value.Length / 2];
            for (var index = 0; index < bytes.Length; index++)
            {
                bytes[index] = Convert.ToByte(value.Substring(index * 2, 2), 16);
            }

            return bytes;
        }

        private long DescriptorOffset(int index)
            => WorkflowTriggerMailboxV1.DescriptorRegionOffset
                + index * (long)WorkflowTriggerMailboxV1.DescriptorStrideBytes;

        private long InlineRequestOffset(int index)
            => DescriptorOffset(index) + WorkflowTriggerMailboxV1.DescriptorHeaderSize;

        private long InlineResponseOffset(int index)
            => InlineRequestOffset(index)
                + WorkflowTriggerMailboxV1.InlineRequestCapacityBytes;

        private static long PageOffset(int index)
            => WorkflowTriggerMailboxV1.PageRegionOffset
                + index * (long)WorkflowTriggerMailboxV1.PageStrideBytes;

        private int ReadBoundedSize(long offset, int maximum)
        {
            var value = ReadInt32(offset);
            if (value < 0 || value > maximum)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Workflow Trigger length is outside the contract boundary.");
            }

            return value;
        }

        private string ReadFixedAscii(long offset, int length)
        {
            var bytes = new byte[length];
            view.ReadArray(offset, bytes, 0, bytes.Length);
            var used = Array.IndexOf(bytes, (byte)0);
            return Encoding.ASCII.GetString(bytes, 0, used < 0 ? length : used);
        }

        private ushort ReadUInt16(long offset) => view.ReadUInt16(offset);
        private int ReadInt32(long offset) => view.ReadInt32(offset);
        private uint ReadUInt32(long offset) => unchecked((uint)view.ReadInt32(offset));
        private ulong ReadUInt64(long offset) => unchecked((ulong)view.ReadInt64(offset));
        private void WriteInt32(long offset, int value) => view.Write(offset, value);
        private void WriteUInt32(long offset, uint value)
            => view.Write(offset, unchecked((int)value));
        private void WriteUInt64(long offset, ulong value)
            => view.Write(offset, unchecked((long)value));
        private ulong ServerEpochUnsafe()
            => ReadUInt64(WorkflowTriggerMailboxV1.CommonOwnerEpochOffset);

        private void WriteGuidNetworkOrder(long offset, Guid value)
        {
            var text = value.ToString("N");
            var bytes = new byte[16];
            for (var index = 0; index < bytes.Length; index++)
            {
                bytes[index] = Convert.ToByte(text.Substring(index * 2, 2), 16);
            }

            view.WriteArray(offset, bytes, 0, bytes.Length);
        }

        private Guid ReadGuidNetworkOrder(long offset)
        {
            var bytes = new byte[16];
            view.ReadArray(offset, bytes, 0, bytes.Length);
            return Guid.ParseExact(
                BitConverter.ToString(bytes).Replace("-", string.Empty),
                "N");
        }

        private static ulong CreateNonZeroToken()
        {
            var bytes = new byte[8];
            using (var random = RandomNumberGenerator.Create())
            {
                do
                {
                    random.GetBytes(bytes);
                }
                while (BitConverter.ToUInt64(bytes, 0) == 0);
            }

            return BitConverter.ToUInt64(bytes, 0);
        }

        private static ulong MonotonicNanoseconds()
        {
            var value = Stopwatch.GetTimestamp()
                * (1_000_000_000d / Stopwatch.Frequency);
            return value <= 0d ? 1UL : checked((ulong)value);
        }

        internal static long LocalDeadline(TimeSpan timeout)
        {
            var timeoutTicks = checked((long)(timeout.TotalSeconds * Stopwatch.Frequency));
            return checked(Stopwatch.GetTimestamp() + timeoutTicks);
        }

        internal static long LocalDeadlineFromBackendMonotonicNs(ulong deadlineNs)
        {
            var deadlineTicks = deadlineNs
                * (double)Stopwatch.Frequency
                / 1_000_000_000d;
            if (deadlineTicks <= 0d || deadlineTicks > long.MaxValue)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Workflow Trigger response ACK deadline is invalid.");
            }

            return (long)Math.Floor(deadlineTicks);
        }

        private void ThrowIfDisposed()
        {
            if (disposed)
            {
                throw new ObjectDisposedException(nameof(WorkflowTriggerMailboxClient));
            }
        }
    }

    internal static class WindowsLowLatencyTimer
    {
        private const uint PeriodMilliseconds = 1;
        private static readonly object SyncRoot = new object();
        private static int leaseCount;
        private static bool periodActive;

        [DllImport("winmm.dll", EntryPoint = "timeBeginPeriod")]
        private static extern uint TimeBeginPeriod(uint periodMilliseconds);

        [DllImport("winmm.dll", EntryPoint = "timeEndPeriod")]
        private static extern uint TimeEndPeriod(uint periodMilliseconds);

        internal static IDisposable Acquire()
        {
            lock (SyncRoot)
            {
                if (leaseCount == 0)
                {
                    periodActive = TryBeginPeriod();
                }

                leaseCount += 1;
                return new Lease();
            }
        }

        private static bool TryBeginPeriod()
        {
            if (Environment.OSVersion.Platform != PlatformID.Win32NT)
            {
                return false;
            }

            try
            {
                return TimeBeginPeriod(PeriodMilliseconds) == 0;
            }
            catch (DllNotFoundException)
            {
                return false;
            }
            catch (EntryPointNotFoundException)
            {
                return false;
            }
        }

        private sealed class Lease : IDisposable
        {
            private bool disposed;

            public void Dispose()
            {
                lock (SyncRoot)
                {
                    if (disposed)
                    {
                        return;
                    }

                    disposed = true;
                    leaseCount -= 1;
                    if (leaseCount != 0 || !periodActive)
                    {
                        return;
                    }

                    try
                    {
                        TimeEndPeriod(PeriodMilliseconds);
                    }
                    finally
                    {
                        periodActive = false;
                    }
                }
            }
        }
    }

    internal sealed class ByteRangeGuard : IDisposable
    {
        private readonly FileStream stream;
        private readonly long offset;
        private readonly long length;
        private bool disposed;

        private ByteRangeGuard(FileStream stream, long offset, long length)
        {
            this.stream = stream;
            this.offset = offset;
            this.length = length;
        }

        internal static ByteRangeGuard? TryAcquire(
            string path,
            long offset,
            long length)
        {
            FileStream stream;
            try
            {
                stream = new FileStream(
                    path,
                    FileMode.Open,
                    FileAccess.ReadWrite,
                    FileShare.ReadWrite);
            }
            catch (IOException error)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Shared-memory guard file is unavailable: " + error.Message);
            }

            if (stream.Length < offset + length)
            {
                stream.Dispose();
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Shared-memory guard file is shorter than the requested lock range.");
            }

            try
            {
                stream.Lock(offset, length);
                return new ByteRangeGuard(stream, offset, length);
            }
            catch (IOException)
            {
                stream.Dispose();
                return null;
            }
        }

        internal static ByteRangeGuard Acquire(
            string path,
            long offset,
            long length,
            long localDeadlineTicks)
        {
            while (Stopwatch.GetTimestamp() < localDeadlineTicks)
            {
                var guard = TryAcquire(path, offset, length);
                if (guard != null)
                {
                    return guard;
                }

                Thread.Sleep(1);
            }

            throw new SharedMemoryTriggerException(
                "timeout",
                "Timed out acquiring a shared-memory guard.");
        }

        internal static ByteRangeGuard AcquireReader(
            string path,
            long startOffset,
            int slotCount,
            long localDeadlineTicks)
        {
            if (slotCount <= 0)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Reader guard slot count must be positive.");
            }

            while (Stopwatch.GetTimestamp() < localDeadlineTicks)
            {
                for (var slot = 0; slot < slotCount; slot++)
                {
                    var guard = TryAcquire(path, checked(startOffset + slot), 1);
                    if (guard != null)
                    {
                        return guard;
                    }
                }

                Thread.Sleep(1);
            }

            throw new SharedMemoryTriggerException(
                "timeout",
                "Timed out acquiring a LocalBuffer reader guard.");
        }

        public void Dispose()
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            try
            {
                stream.Unlock(offset, length);
            }
            finally
            {
                stream.Dispose();
            }
        }
    }

    internal static class ZlibCodec
    {
        internal static byte[] Decompress(byte[] encoded, int expectedLength)
        {
            if (encoded == null || encoded.Length < 6)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Zlib response is truncated.");
            }

            var cmf = encoded[0];
            var flg = encoded[1];
            if ((cmf & 0x0f) != 8
                || ((cmf << 8) + flg) % 31 != 0
                || (flg & 0x20) != 0)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Zlib response header is invalid.");
            }

            using (var source = new MemoryStream(
                encoded,
                2,
                encoded.Length - 6,
                false))
            using (var deflate = new DeflateStream(
                source,
                CompressionMode.Decompress,
                false))
            using (var output = new MemoryStream(expectedLength))
            {
                deflate.CopyTo(output);
                var result = output.ToArray();
                var expectedAdler = ((uint)encoded[encoded.Length - 4] << 24)
                    | ((uint)encoded[encoded.Length - 3] << 16)
                    | ((uint)encoded[encoded.Length - 2] << 8)
                    | encoded[encoded.Length - 1];
                if (Adler32(result) != expectedAdler)
                {
                    throw new SharedMemoryTriggerException(
                        "checksum_mismatch",
                        "Zlib response Adler32 mismatch.");
                }

                return result;
            }
        }

        private static uint Adler32(byte[] bytes)
        {
            const uint modulus = 65521;
            uint a = 1;
            uint b = 0;
            for (var index = 0; index < bytes.Length; index++)
            {
                a = (a + bytes[index]) % modulus;
                b = (b + a) % modulus;
            }

            return (b << 16) | a;
        }
    }
}
