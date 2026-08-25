using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.IO.MemoryMappedFiles;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
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
        internal byte[] Payload { get; set; } = Array.Empty<byte>();
        internal int ErrorCode { get; set; }
        internal int OutputLeaseCount { get; set; }
        internal int HandoffState { get; set; }
    }

    internal sealed class WorkflowTriggerAllocationRead
    {
        internal WorkflowTriggerDescriptorIdentity Identity { get; set; } = new WorkflowTriggerDescriptorIdentity();
        internal byte[] Payload { get; set; } = Array.Empty<byte>();
    }

    internal sealed class WorkflowTriggerMailboxClient : IDisposable
    {
        private const long DescriptorStride = WorkflowTriggerMailboxV1.DescriptorHeaderSize
            + WorkflowTriggerMailboxV1.InlineRequestCapacityBytes
            + WorkflowTriggerMailboxV1.InlineResponseCapacityBytes;
        private const long DescriptorRegionOffset = WorkflowTriggerMailboxV1.FileHeaderSize;
        private const long PageStride = WorkflowTriggerMailboxV1.PageHeaderSize
            + WorkflowTriggerMailboxV1.OverflowPageCapacityBytes;
        private const long PageRegionOffset = DescriptorRegionOffset
            + WorkflowTriggerMailboxV1.DescriptorCount * DescriptorStride;
        private const long MailboxFileSize = PageRegionOffset
            + WorkflowTriggerMailboxV1.OverflowPageCount * PageStride;
        private static readonly byte[] Magic = { 0x41, 0x4d, 0x56, 0x57, 0x54, 0x47, 0x31, 0x00 };

        private readonly object accessSync = new object();
        private readonly string mailboxPath;
        private readonly FileStream mailboxFile;
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
            mailboxPath = Path.GetFullPath(Path.Combine(buffersRoot, WorkflowTriggerMailboxV1.RelativeMmapPath.Replace('/', Path.DirectorySeparatorChar)));
            try
            {
                mailboxFile = new FileStream(mailboxPath, FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite | FileShare.Delete);
            }
            catch (Exception error)
            {
                timerResolutionLease.Dispose();
                throw new SharedMemoryTriggerException("server_unavailable", "Workflow Trigger mailbox is not available.", error);
            }

            if (mailboxFile.Length != MailboxFileSize)
            {
                mailboxFile.Dispose();
                timerResolutionLease.Dispose();
                throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger mailbox size does not match the frozen contract.");
            }
            try
            {
                mailboxMap = MemoryMappedFile.CreateFromFile(mailboxFile, null, 0, MemoryMappedFileAccess.ReadWrite, HandleInheritability.None, false);
                view = mailboxMap.CreateViewAccessor(0, MailboxFileSize, MemoryMappedFileAccess.ReadWrite);
                ValidateHeader();
            }
            catch
            {
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
                    return ReadUInt64(WorkflowTriggerMailboxV1.FileHeaderServerEpochOffset);
                }
            }
        }

        internal WorkflowTriggerDescriptorIdentity Claim(uint timeoutMs, ulong routeGeneration, byte[] preparePayload, Guid requestId)
        {
            if (timeoutMs == 0)
            {
                throw new ArgumentOutOfRangeException(nameof(timeoutMs));
            }

            if (preparePayload == null || preparePayload.Length > WorkflowTriggerMailboxV1.MaxRequestBytes)
            {
                throw new SharedMemoryTriggerException("trigger_request_too_large", "Workflow Trigger PREPARE exceeds 512 KiB.");
            }

            var ownerToken = CreateNonZeroToken();
            for (var descriptorIndex = 0; descriptorIndex < WorkflowTriggerMailboxV1.DescriptorCount; descriptorIndex++)
            {
                lock (accessSync)
                {
                    ThrowIfDisposed();
                    if (ReadInt32(
                        DescriptorOffset(descriptorIndex)
                        + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset)
                        != WorkflowTriggerMailboxV1.DescriptorStateFree)
                    {
                        continue;
                    }
                }

                using (var guard = ByteRangeGuard.TryAcquire(DescriptorGuardPath(descriptorIndex), 0, 1))
                {
                    if (guard == null)
                    {
                        continue;
                    }

                    lock (accessSync)
                    {
                        ThrowIfDisposed();
                        var descriptorOffset = DescriptorOffset(descriptorIndex);
                        if (ReadInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset)
                            != WorkflowTriggerMailboxV1.DescriptorStateFree)
                        {
                            continue;
                        }

                        var generation = unchecked(ReadUInt64(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderGenerationOffset) + 1UL);
                        if (generation == 0)
                        {
                            generation = 1;
                        }

                        var header = new byte[WorkflowTriggerMailboxV1.DescriptorHeaderSize];
                        view.WriteArray(descriptorOffset, header, 0, header.Length);
                        WriteInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderDescriptorIndexOffset, descriptorIndex);
                        WriteUInt64(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderGenerationOffset, generation);
                        var serverEpoch = ServerEpochUnsafe();
                        WriteUInt64(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderServerEpochOffset, serverEpoch);
                        WriteGuidNetworkOrder(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderRequestIdOffset, requestId);
                        WriteUInt64(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderOwnerTokenOffset, ownerToken);
                        WriteUInt64(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderDeadlineNsOffset, 0);
                        WriteUInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderAcceptedTimeoutMsOffset, timeoutMs);
                        WriteUInt64(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderRouteGenerationOffset, routeGeneration);
                        view.WriteArray(InlineRequestOffset(descriptorIndex), preparePayload, 0, preparePayload.Length);
                        WriteInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderRequestSizeOffset, preparePayload.Length);
                        WriteInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderRequestChecksumAlgorithmOffset, WorkflowTriggerMailboxV1.ChecksumAlgorithmCrc32Ieee);
                        WriteUInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderRequestChecksumOffset, Crc32Ieee.Compute(preparePayload));
                        WriteInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderFirstPageIndexOffset, -1);
                        Thread.MemoryBarrier();
                        WriteInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset, WorkflowTriggerMailboxV1.DescriptorStatePrepare);
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

            throw new SharedMemoryTriggerException("trigger_source_busy", "Workflow Trigger mailbox descriptors are full.");
        }

        internal WorkflowTriggerAllocationRead? TryReadAllocation(WorkflowTriggerDescriptorIdentity claimedIdentity)
        {
            lock (accessSync)
            {
                ThrowIfDisposed();
                var publishedState = ReadInt32(
                    DescriptorOffset(claimedIdentity.DescriptorIndex)
                    + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset);
                if (publishedState == WorkflowTriggerMailboxV1.DescriptorStatePrepare)
                {
                    return null;
                }
            }

            using (var guard = ByteRangeGuard.TryAcquire(DescriptorGuardPath(claimedIdentity.DescriptorIndex), 0, 1))
            {
                if (guard == null)
                {
                    return null;
                }

                lock (accessSync)
                {
                    ThrowIfDisposed();
                    var current = RequireIdentity(claimedIdentity, allowUnacceptedDeadline: true);
                    var descriptorOffset = DescriptorOffset(claimedIdentity.DescriptorIndex);
                    var state = ReadInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset);
                    if (state == WorkflowTriggerMailboxV1.DescriptorStateCancelled)
                    {
                        throw new SharedMemoryTriggerException("cancelled", "Workflow Trigger request was cancelled before image allocation.");
                    }

                    if (state != WorkflowTriggerMailboxV1.DescriptorStateWriting)
                    {
                        return null;
                    }

                    var size = ReadBoundedSize(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderResponseSizeOffset, WorkflowTriggerMailboxV1.InlineResponseCapacityBytes);
                    var payload = new byte[size];
                    view.ReadArray(InlineResponseOffset(claimedIdentity.DescriptorIndex), payload, 0, payload.Length);
                    var checksum = ReadUInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderResponseChecksumOffset);
                    if (Crc32Ieee.Compute(payload) != checksum)
                    {
                        throw new SharedMemoryTriggerException("checksum_mismatch", "Workflow Trigger allocation checksum mismatch.");
                    }

                    return new WorkflowTriggerAllocationRead { Identity = current, Payload = payload };
                }
            }
        }

        internal void PublishRequest(WorkflowTriggerDescriptorIdentity identity, byte[] payload)
        {
            if (payload == null || payload.Length > WorkflowTriggerMailboxV1.MaxRequestBytes)
            {
                throw new SharedMemoryTriggerException("trigger_request_too_large", "Workflow Trigger request exceeds 512 KiB.");
            }

            using (var guard = ByteRangeGuard.Acquire(DescriptorGuardPath(identity.DescriptorIndex), 0, 1, LocalDeadline(TimeSpan.FromSeconds(5))))
            {
                lock (accessSync)
                {
                    ThrowIfDisposed();
                    RequireState(identity, WorkflowTriggerMailboxV1.DescriptorStateWriting);
                    var descriptorOffset = DescriptorOffset(identity.DescriptorIndex);
                    view.WriteArray(InlineRequestOffset(identity.DescriptorIndex), payload, 0, payload.Length);
                    WriteInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderRequestSizeOffset, payload.Length);
                    WriteInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderRequestChecksumAlgorithmOffset, WorkflowTriggerMailboxV1.ChecksumAlgorithmCrc32Ieee);
                    WriteUInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderRequestChecksumOffset, Crc32Ieee.Compute(payload));
                    Thread.MemoryBarrier();
                    WriteInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset, WorkflowTriggerMailboxV1.DescriptorStateRequest);
                }
            }
        }

        internal WorkflowTriggerMailboxResponse? TryReadResponse(WorkflowTriggerDescriptorIdentity identity)
        {
            lock (accessSync)
            {
                ThrowIfDisposed();
                var publishedState = ReadInt32(
                    DescriptorOffset(identity.DescriptorIndex)
                    + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset);
                if (publishedState == WorkflowTriggerMailboxV1.DescriptorStateRequest
                    || publishedState == WorkflowTriggerMailboxV1.DescriptorStateProcessing)
                {
                    return null;
                }
            }

            using (var guard = ByteRangeGuard.TryAcquire(DescriptorGuardPath(identity.DescriptorIndex), 0, 1))
            {
                if (guard == null)
                {
                    return null;
                }

                lock (accessSync)
                {
                    ThrowIfDisposed();
                    var current = RequireIdentity(identity, allowUnacceptedDeadline: true);
                    var descriptorOffset = DescriptorOffset(identity.DescriptorIndex);
                    var state = ReadInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset);
                    if (state == WorkflowTriggerMailboxV1.DescriptorStateCancelled)
                    {
                        throw new SharedMemoryTriggerException("cancelled", "Workflow Trigger request was cancelled.");
                    }

                    if (state != WorkflowTriggerMailboxV1.DescriptorStateResponse)
                    {
                        return null;
                    }

                    var encoded = ReadEncodedResponse(current);
                    var expectedChecksum = ReadUInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderResponseChecksumOffset);
                    if (Crc32Ieee.Compute(encoded) != expectedChecksum)
                    {
                        throw new SharedMemoryTriggerException("checksum_mismatch", "Workflow Trigger response checksum mismatch.");
                    }

                    var codec = ReadInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderResponseCodecOffset);
                    var rawSize = ReadBoundedSize(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderResponseRawSizeOffset, WorkflowTriggerMailboxV1.MaxResponseBytes);
                    var payload = codec == WorkflowTriggerMailboxV1.ResponseCodecNone
                        ? encoded
                        : codec == WorkflowTriggerMailboxV1.ResponseCodecZlib
                            ? ZlibCodec.Decompress(encoded, rawSize)
                            : throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger response codec is not supported.");
                    if (payload.Length != rawSize)
                    {
                        throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger response raw length mismatch.");
                    }

                    return new WorkflowTriggerMailboxResponse
                    {
                        Identity = current,
                        Payload = payload,
                        ErrorCode = ReadInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderErrorCodeOffset),
                        OutputLeaseCount = ReadInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderResponseOutputLeaseCountOffset),
                        HandoffState = ReadInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderHandoffStateOffset)
                    };
                }
            }
        }

        internal void Acknowledge(WorkflowTriggerDescriptorIdentity identity)
        {
            var reclaimDeadline = LocalDeadline(TimeSpan.FromSeconds(5));
            using (var guard = ByteRangeGuard.Acquire(DescriptorGuardPath(identity.DescriptorIndex), 0, 1, reclaimDeadline))
            {
                lock (accessSync)
                {
                    ThrowIfDisposed();
                    RequireState(identity, WorkflowTriggerMailboxV1.DescriptorStateResponse);
                    Thread.MemoryBarrier();
                    WriteInt32(DescriptorOffset(identity.DescriptorIndex) + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset, WorkflowTriggerMailboxV1.DescriptorStateAcked);
                }
            }

            WaitForReclaim(identity, reclaimDeadline);
        }

        private void WaitForReclaim(WorkflowTriggerDescriptorIdentity identity, long localDeadlineTicks)
        {
            while (Stopwatch.GetTimestamp() < localDeadlineTicks)
            {
                lock (accessSync)
                {
                    ThrowIfDisposed();
                    var descriptorOffset = DescriptorOffset(identity.DescriptorIndex);
                    var state = ReadInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset);
                    var generation = ReadUInt64(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderGenerationOffset);
                    var serverEpoch = ServerEpochUnsafe();
                    if (serverEpoch != identity.ServerEpoch
                        || generation != identity.Generation
                        || state == WorkflowTriggerMailboxV1.DescriptorStateFree)
                    {
                        return;
                    }
                }

                Thread.Sleep(1);
            }

            throw new SharedMemoryTriggerException("timeout", "Timed out waiting for Workflow Trigger ACK reclaim.");
        }

        internal void Cancel(WorkflowTriggerDescriptorIdentity identity)
        {
            using (var guard = ByteRangeGuard.Acquire(DescriptorGuardPath(identity.DescriptorIndex), 0, 1, LocalDeadline(TimeSpan.FromSeconds(2))))
            {
                lock (accessSync)
                {
                    ThrowIfDisposed();
                    var current = RequireIdentity(identity, allowUnacceptedDeadline: true);
                    var descriptorOffset = DescriptorOffset(current.DescriptorIndex);
                    var state = ReadInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset);
                    if (state < WorkflowTriggerMailboxV1.DescriptorStatePrepare || state > WorkflowTriggerMailboxV1.DescriptorStateResponse)
                    {
                        return;
                    }

                    WriteInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderCancelRequestedOffset, 1);
                    if (state != WorkflowTriggerMailboxV1.DescriptorStateProcessing)
                    {
                        Thread.MemoryBarrier();
                        WriteInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset, WorkflowTriggerMailboxV1.DescriptorStateCancelled);
                    }
                }
            }
        }

        internal bool IsResponseCurrent(WorkflowTriggerDescriptorIdentity identity)
        {
            using (var guard = ByteRangeGuard.TryAcquire(DescriptorGuardPath(identity.DescriptorIndex), 0, 1))
            {
                if (guard == null)
                {
                    return false;
                }

                lock (accessSync)
                {
                    try
                    {
                        RequireState(identity, WorkflowTriggerMailboxV1.DescriptorStateResponse);
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
                timerResolutionLease.Dispose();
            }
        }

        private byte[] ReadEncodedResponse(WorkflowTriggerDescriptorIdentity identity)
        {
            var descriptorOffset = DescriptorOffset(identity.DescriptorIndex);
            var responseSize = ReadBoundedSize(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderResponseSizeOffset, WorkflowTriggerMailboxV1.MaxResponseBytes);
            var pageCount = ReadInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderResponsePageCountOffset);
            if (pageCount == 0)
            {
                var inline = new byte[responseSize];
                view.ReadArray(InlineResponseOffset(identity.DescriptorIndex), inline, 0, inline.Length);
                return inline;
            }

            if (pageCount < 0 || pageCount > WorkflowTriggerMailboxV1.MaxOverflowPagesPerResponse)
            {
                throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger response page count is invalid.");
            }

            var encoded = new byte[responseSize];
            var written = 0;
            var pageIndex = ReadInt32(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderFirstPageIndexOffset);
            var visited = new HashSet<int>();
            for (var ordinal = 0; ordinal < pageCount; ordinal++)
            {
                if (pageIndex < 0 || pageIndex >= WorkflowTriggerMailboxV1.OverflowPageCount || !visited.Add(pageIndex))
                {
                    throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger response page chain is invalid.");
                }

                var pageOffset = PageOffset(pageIndex);
                if (ReadInt32(pageOffset + WorkflowTriggerMailboxV1.PageHeaderStateOffset) != WorkflowTriggerMailboxV1.PageStateReady
                    || ReadInt32(pageOffset + WorkflowTriggerMailboxV1.PageHeaderDescriptorIndexOffset) != identity.DescriptorIndex
                    || ReadUInt64(pageOffset + WorkflowTriggerMailboxV1.PageHeaderDescriptorGenerationOffset) != identity.Generation
                    || ReadUInt64(pageOffset + WorkflowTriggerMailboxV1.PageHeaderOwnerTokenOffset) != identity.OwnerToken
                    || ReadUInt64(pageOffset + WorkflowTriggerMailboxV1.PageHeaderServerEpochOffset) != identity.ServerEpoch
                    || ReadInt32(pageOffset + WorkflowTriggerMailboxV1.PageHeaderOrdinalOffset) != ordinal)
                {
                    throw new SharedMemoryTriggerException("identity_mismatch", "Workflow Trigger response page identity mismatch.");
                }

                var usedSize = ReadBoundedSize(pageOffset + WorkflowTriggerMailboxV1.PageHeaderUsedSizeOffset, WorkflowTriggerMailboxV1.OverflowPageCapacityBytes);
                if (written > encoded.Length - usedSize)
                {
                    throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger response page chain exceeds the declared response size.");
                }

                var chunk = new byte[usedSize];
                view.ReadArray(pageOffset + WorkflowTriggerMailboxV1.PageHeaderSize, chunk, 0, chunk.Length);
                if (Crc32Ieee.Compute(chunk) != ReadUInt32(pageOffset + WorkflowTriggerMailboxV1.PageHeaderChecksumOffset))
                {
                    throw new SharedMemoryTriggerException("checksum_mismatch", "Workflow Trigger response page checksum mismatch.");
                }

                Buffer.BlockCopy(chunk, 0, encoded, written, chunk.Length);
                written += chunk.Length;
                pageIndex = ReadInt32(pageOffset + WorkflowTriggerMailboxV1.PageHeaderNextPageIndexOffset);
            }

            if (written != encoded.Length || pageIndex != -1)
            {
                throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger response page total length mismatch.");
            }

            return encoded;
        }

        private WorkflowTriggerDescriptorIdentity RequireIdentity(WorkflowTriggerDescriptorIdentity expected, bool allowUnacceptedDeadline)
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
                throw new SharedMemoryTriggerException("identity_mismatch", "Workflow Trigger descriptor identity changed.");
            }

            return current;
        }

        private void RequireState(WorkflowTriggerDescriptorIdentity identity, int expectedState)
        {
            RequireIdentity(identity, allowUnacceptedDeadline: false);
            var state = ReadInt32(DescriptorOffset(identity.DescriptorIndex) + WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset);
            if (state != expectedState)
            {
                throw new SharedMemoryTriggerException("identity_mismatch", "Workflow Trigger descriptor state changed.");
            }
        }

        private WorkflowTriggerDescriptorIdentity ReadIdentity(int descriptorIndex)
        {
            var descriptorOffset = DescriptorOffset(descriptorIndex);
            return new WorkflowTriggerDescriptorIdentity
            {
                DescriptorIndex = descriptorIndex,
                Generation = ReadUInt64(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderGenerationOffset),
                ServerEpoch = ReadUInt64(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderServerEpochOffset),
                RequestId = ReadGuidNetworkOrder(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderRequestIdOffset),
                OwnerToken = ReadUInt64(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderOwnerTokenOffset),
                BackendDeadlineNs = ReadUInt64(descriptorOffset + WorkflowTriggerMailboxV1.DescriptorHeaderDeadlineNsOffset)
            };
        }

        private void ValidateHeader()
        {
            lock (accessSync)
            {
                var actualMagic = new byte[Magic.Length];
                view.ReadArray(WorkflowTriggerMailboxV1.FileHeaderMagicOffset, actualMagic, 0, actualMagic.Length);
                for (var index = 0; index < Magic.Length; index++)
                {
                    if (actualMagic[index] != Magic[index])
                    {
                        throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger mailbox magic does not match.");
                    }
                }

                if (ReadInt32(WorkflowTriggerMailboxV1.FileHeaderVersionOffset) != WorkflowTriggerMailboxV1.Version
                    || ReadInt32(WorkflowTriggerMailboxV1.FileHeaderHeaderSizeOffset) != WorkflowTriggerMailboxV1.FileHeaderSize
                    || ReadInt32(WorkflowTriggerMailboxV1.FileHeaderDescriptorCountOffset) != WorkflowTriggerMailboxV1.DescriptorCount
                    || ReadInt32(WorkflowTriggerMailboxV1.FileHeaderDescriptorStrideOffset) != DescriptorStride
                    || ReadInt32(WorkflowTriggerMailboxV1.FileHeaderOverflowPageCountOffset) != WorkflowTriggerMailboxV1.OverflowPageCount
                    || ReadInt32(WorkflowTriggerMailboxV1.FileHeaderPageStrideOffset) != PageStride
                    || ReadInt32(WorkflowTriggerMailboxV1.FileHeaderChecksumAlgorithmOffset) != WorkflowTriggerMailboxV1.ChecksumAlgorithmCrc32Ieee)
                {
                    throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger mailbox layout does not match the frozen contract.");
                }
            }
        }

        private static long DescriptorOffset(int index) => DescriptorRegionOffset + index * DescriptorStride;
        private static long InlineRequestOffset(int index) => DescriptorOffset(index) + WorkflowTriggerMailboxV1.DescriptorHeaderSize;
        private static long InlineResponseOffset(int index) => InlineRequestOffset(index) + WorkflowTriggerMailboxV1.InlineRequestCapacityBytes;
        private static long PageOffset(int index) => PageRegionOffset + index * PageStride;

        private string DescriptorGuardPath(int descriptorIndex)
        {
            return mailboxPath + WorkflowTriggerMailboxV1.DescriptorGuardSuffix.Replace("{index}", descriptorIndex.ToString(System.Globalization.CultureInfo.InvariantCulture));
        }

        private int ReadBoundedSize(long offset, int maximum)
        {
            var value = ReadInt32(offset);
            if (value < 0 || value > maximum)
            {
                throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger length is outside the contract boundary.");
            }

            return value;
        }

        private int ReadInt32(long offset) => view.ReadInt32(offset);
        private uint ReadUInt32(long offset) => unchecked((uint)view.ReadInt32(offset));
        private ulong ReadUInt64(long offset) => unchecked((ulong)view.ReadInt64(offset));
        private void WriteInt32(long offset, int value) => view.Write(offset, value);
        private void WriteUInt32(long offset, uint value) => view.Write(offset, unchecked((int)value));
        private void WriteUInt64(long offset, ulong value) => view.Write(offset, unchecked((long)value));
        private ulong ServerEpochUnsafe() => ReadUInt64(WorkflowTriggerMailboxV1.FileHeaderServerEpochOffset);

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
            var hex = BitConverter.ToString(bytes).Replace("-", string.Empty);
            return Guid.ParseExact(hex, "N");
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

        internal static long LocalDeadline(TimeSpan timeout)
        {
            var timeoutTicks = checked((long)(timeout.TotalSeconds * Stopwatch.Frequency));
            return checked(Stopwatch.GetTimestamp() + timeoutTicks);
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

        internal static ByteRangeGuard? TryAcquire(string path, long offset, long length)
        {
            FileStream stream;
            try
            {
                // mailbox owner 与 LocalBufferBroker 会在启动时创建并定长 guard。
                // 请求热路径只打开已有文件，避免每次加锁重复执行目录检查、
                // OpenOrCreate 和 SetLength 所产生的 Windows 文件系统抖动。
                stream = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite | FileShare.Delete);
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

        internal static ByteRangeGuard Acquire(string path, long offset, long length, long localDeadlineTicks)
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

            throw new SharedMemoryTriggerException("timeout", "Timed out acquiring a shared-memory guard.");
        }

        internal static ByteRangeGuard AcquireReader(string path, int slotCount, long localDeadlineTicks)
        {
            if (slotCount <= 0)
            {
                throw new SharedMemoryTriggerException("protocol_error", "Reader guard slot count must be positive.");
            }

            while (Stopwatch.GetTimestamp() < localDeadlineTicks)
            {
                for (var slot = 0; slot < slotCount; slot++)
                {
                    var guard = TryAcquire(path, slot, 1);
                    if (guard != null)
                    {
                        return guard;
                    }
                }

                Thread.Sleep(1);
            }

            throw new SharedMemoryTriggerException("timeout", "Timed out acquiring a LocalBuffer reader guard.");
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
                throw new SharedMemoryTriggerException("protocol_error", "Zlib response is truncated.");
            }

            var cmf = encoded[0];
            var flg = encoded[1];
            if ((cmf & 0x0f) != 8 || ((cmf << 8) + flg) % 31 != 0 || (flg & 0x20) != 0)
            {
                throw new SharedMemoryTriggerException("protocol_error", "Zlib response header is invalid or uses a preset dictionary.");
            }

            using (var source = new MemoryStream(encoded, 2, encoded.Length - 6, false))
            using (var deflate = new DeflateStream(source, CompressionMode.Decompress, false))
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
                    throw new SharedMemoryTriggerException("checksum_mismatch", "Zlib response Adler32 mismatch.");
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
