using System;
using System.Globalization;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Text;

namespace Amvar.Vision.SharedMemory
{
    /// <summary>
    /// 64-bit SDK 进程只映射一次固定 LocalBuffer arena 和 allocator metadata。
    /// 每次调用仅创建轻量 locator lease；图片不会在 SDK 内再次复制。
    /// </summary>
    internal sealed class LocalBufferMappingCache : IDisposable
    {
        private const int HeaderSize = 256;
        private const int DescriptorStride = 256;
        private const int LayoutVersion = 1;
        private const string ArenaId = "local-buffer-main";
        private const int StateWriting = 1;
        private readonly object syncRoot = new object();
        private readonly string arenaPath;
        private readonly string guardPath;
        private readonly long arenaSizeBytes;
        private readonly int readerGuardSlots;
        private readonly int guardStride;
        private readonly string layoutFingerprint;
        private readonly FileStream arenaFile;
        private readonly FileStream allocatorFile;
        private FileStream? guardFile;
        private readonly MemoryMappedFile arenaMap;
        private readonly MemoryMappedFile allocatorMap;
        private readonly MemoryMappedViewAccessor arenaView;
        private readonly MemoryMappedViewAccessor allocatorView;
        private bool disposed;
        private bool disposeRequested;
        private int activeLeaseCount;

        internal LocalBufferMappingCache(SharedMemoryTriggerClientOptions options)
        {
            if (options == null)
            {
                throw new ArgumentNullException(nameof(options));
            }

            var localBufferRoot = Path.Combine(options.BuffersRoot, "local-buffer");
            arenaPath = Path.GetFullPath(Path.Combine(localBufferRoot, "images.mmap"));
            var allocatorPath = Path.GetFullPath(Path.Combine(localBufferRoot, "state.mmap"));
            guardPath = Path.GetFullPath(Path.Combine(localBufferRoot, "access.guard"));
            allocatorFile = new FileStream(
                allocatorPath,
                FileMode.Open,
                FileAccess.ReadWrite,
                FileShare.ReadWrite);
            try
            {
                allocatorMap = MemoryMappedFile.CreateFromFile(
                    allocatorFile,
                    null,
                    0,
                    MemoryMappedFileAccess.ReadWrite,
                    HandleInheritability.None,
                    false);
                allocatorView = allocatorMap.CreateViewAccessor(
                    0,
                    allocatorFile.Length,
                    MemoryMappedFileAccess.ReadWrite);
                var layout = ReadLayout(allocatorView, allocatorFile.Length);
                arenaSizeBytes = layout.ArenaSizeBytes;
                readerGuardSlots = layout.ReaderGuardSlots;
                guardStride = layout.GuardStride;
                layoutFingerprint = layout.LayoutFingerprint;
                arenaFile = OpenExact(arenaPath, arenaSizeBytes);
                try
                {
                    arenaMap = MemoryMappedFile.CreateFromFile(
                        arenaFile,
                        null,
                        0,
                        MemoryMappedFileAccess.ReadWrite,
                        HandleInheritability.None,
                        false);
                    arenaView = arenaMap.CreateViewAccessor(
                        0,
                        arenaSizeBytes,
                        MemoryMappedFileAccess.ReadWrite);
                    ValidateGuardFile(layout.DescriptorCount);
                }
                catch
                {
                    arenaFile.Dispose();
                    throw;
                }
            }
            catch
            {
                allocatorView?.Dispose();
                allocatorMap?.Dispose();
                allocatorFile.Dispose();
                throw;
            }
        }

        internal string ArenaPath => arenaPath;

        internal string GuardPath => guardPath;

        internal int ReaderGuardSlots => readerGuardSlots;

        internal int WriterGuardOffset(int descriptorIndex)
        {
            return checked(descriptorIndex * guardStride + 1);
        }

        internal int ReaderGuardOffset(int descriptorIndex)
        {
            return checked(descriptorIndex * guardStride + 2);
        }

        internal LocalBufferMappingLease Acquire(WorkflowTriggerAllocation allocation)
        {
            if (allocation == null)
            {
                throw new ArgumentNullException(nameof(allocation));
            }

            lock (syncRoot)
            {
                ThrowIfDisposed();
                ValidateAllocation(allocation);
                activeLeaseCount++;
                return new LocalBufferMappingLease(
                    arenaView,
                    allocation.Offset,
                    allocation.ContentLength,
                    ReleaseLease);
            }
        }

        internal void ValidateAllocation(WorkflowTriggerAllocation allocation)
        {
            if (!string.Equals(allocation.ArenaId, ArenaId, StringComparison.Ordinal)
                || allocation.DescriptorIndex < 0
                || allocation.DescriptorGeneration <= 0
                || allocation.Offset < 0
                || allocation.ContentLength <= 0
                || allocation.AllocationCapacityBytes < allocation.ContentLength
                || allocation.Offset > arenaSizeBytes - allocation.AllocationCapacityBytes
                || !string.Equals(allocation.LayoutFingerprint, layoutFingerprint, StringComparison.OrdinalIgnoreCase))
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Workflow Trigger allocation does not match the trusted LocalBuffer arena.");
            }

            var descriptorOffset = checked(
                HeaderSize + (long)allocation.DescriptorIndex * DescriptorStride);
            if (descriptorOffset < HeaderSize
                || descriptorOffset > allocatorFile.Length - DescriptorStride)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Workflow Trigger descriptor index is outside allocator metadata.");
            }

            var headerEpoch = new byte[16];
            allocatorView.ReadArray(64, headerEpoch, 0, headerEpoch.Length);
            var descriptorState = allocatorView.ReadUInt32(descriptorOffset);
            var descriptorGeneration = allocatorView.ReadUInt64(descriptorOffset + 8);
            var descriptorDataOffset = checked((long)allocatorView.ReadUInt64(descriptorOffset + 48));
            var descriptorCapacity = checked((long)allocatorView.ReadUInt64(descriptorOffset + 56));
            var descriptorContentLength = checked((long)allocatorView.ReadUInt64(descriptorOffset + 64));
            if (descriptorState != StateWriting
                || descriptorGeneration != checked((ulong)allocation.DescriptorGeneration)
                || !string.Equals(ToHex(headerEpoch), allocation.BrokerEpoch, StringComparison.OrdinalIgnoreCase)
                || descriptorDataOffset != allocation.Offset
                || descriptorCapacity != allocation.AllocationCapacityBytes
                || descriptorContentLength != allocation.ContentLength)
            {
                throw new SharedMemoryTriggerException(
                    "stale_reference",
                    "Workflow Trigger allocation descriptor identity is stale.");
            }
        }

        internal void ValidateActiveBufferRef(
            string arenaId,
            string brokerEpoch,
            int descriptorIndex,
            long descriptorGeneration,
            long offset,
            long contentLength,
            long allocationCapacityBytes)
        {
            if (!string.Equals(arenaId, ArenaId, StringComparison.Ordinal)
                || descriptorIndex < 0
                || descriptorGeneration <= 0
                || offset < 0
                || contentLength <= 0
                || allocationCapacityBytes < contentLength
                || offset > arenaSizeBytes - allocationCapacityBytes)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "LocalBuffer result locator does not match the trusted arena.");
            }

            var descriptorOffset = checked(HeaderSize + (long)descriptorIndex * DescriptorStride);
            if (descriptorOffset > allocatorFile.Length - DescriptorStride)
            {
                throw new SharedMemoryTriggerException("protocol_error", "LocalBuffer result descriptor is outside metadata.");
            }

            var headerEpoch = new byte[16];
            allocatorView.ReadArray(64, headerEpoch, 0, headerEpoch.Length);
            if (allocatorView.ReadUInt32(descriptorOffset) != 2
                || allocatorView.ReadUInt64(descriptorOffset + 8) != checked((ulong)descriptorGeneration)
                || !string.Equals(ToHex(headerEpoch), brokerEpoch, StringComparison.OrdinalIgnoreCase)
                || checked((long)allocatorView.ReadUInt64(descriptorOffset + 48)) != offset
                || checked((long)allocatorView.ReadUInt64(descriptorOffset + 56)) != allocationCapacityBytes
                || checked((long)allocatorView.ReadUInt64(descriptorOffset + 64)) != contentLength)
            {
                throw new SharedMemoryTriggerException("stale_reference", "LocalBuffer result descriptor identity is stale.");
            }
        }

        public void Dispose()
        {
            lock (syncRoot)
            {
                if (disposeRequested)
                {
                    return;
                }

                disposeRequested = true;
                if (activeLeaseCount == 0)
                {
                    DisposeResources();
                }
            }
        }

        private void ValidateGuardFile(int descriptorCount)
        {
            var expectedLength = checked((long)descriptorCount * guardStride + 1);
            guardFile = new FileStream(
                guardPath,
                FileMode.Open,
                FileAccess.ReadWrite,
                FileShare.ReadWrite);
            if (guardFile.Length != expectedLength)
            {
                guardFile.Dispose();
                guardFile = null;
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "LocalBuffer guard layout does not match allocator metadata.");
            }
        }

        private static LocalBufferLayout ReadLayout(
            MemoryMappedViewAccessor view,
            long allocatorLength)
        {
            var magic = new byte[8];
            view.ReadArray(0, magic, 0, magic.Length);
            var descriptorCount = checked((int)view.ReadUInt32(20));
            var readerSlots = checked((int)view.ReadUInt32(24));
            var discoveredGuardStride = checked((int)view.ReadUInt32(28));
            var discoveredArenaSize = checked((long)view.ReadUInt64(32));
            var fingerprint = new byte[32];
            view.ReadArray(80, fingerprint, 0, fingerprint.Length);
            var expectedAllocatorLength = checked(
                HeaderSize + (long)descriptorCount * DescriptorStride);
            if (!string.Equals(Encoding.ASCII.GetString(magic), "AMVLBA01", StringComparison.Ordinal)
                || view.ReadUInt32(8) != LayoutVersion
                || view.ReadUInt32(12) != HeaderSize
                || view.ReadUInt32(16) != DescriptorStride
                || descriptorCount <= 0
                || readerSlots <= 0
                || discoveredGuardStride != 2 + readerSlots
                || discoveredArenaSize <= 0
                || allocatorLength != expectedAllocatorLength)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "LocalBuffer allocator header is invalid or unsupported.");
            }

            return new LocalBufferLayout(
                descriptorCount,
                readerSlots,
                discoveredGuardStride,
                discoveredArenaSize,
                ToHex(fingerprint));
        }

        private void ThrowIfDisposed()
        {
            if (disposeRequested || disposed)
            {
                throw new ObjectDisposedException(nameof(LocalBufferMappingCache));
            }
        }

        private void ReleaseLease()
        {
            lock (syncRoot)
            {
                if (activeLeaseCount <= 0)
                {
                    return;
                }

                activeLeaseCount--;
                if (disposeRequested && activeLeaseCount == 0)
                {
                    DisposeResources();
                }
            }
        }

        private void DisposeResources()
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            allocatorView.Dispose();
            arenaView.Dispose();
            allocatorMap.Dispose();
            arenaMap.Dispose();
            allocatorFile.Dispose();
            arenaFile.Dispose();
            guardFile?.Dispose();
        }

        private static FileStream OpenExact(string path, long expectedLength)
        {
            var file = new FileStream(
                Path.GetFullPath(path),
                FileMode.Open,
                FileAccess.ReadWrite,
                FileShare.ReadWrite);
            if (file.Length != expectedLength)
            {
                file.Dispose();
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "LocalBuffer arena file size does not match the SDK configuration.");
            }

            return file;
        }

        private static string ToHex(byte[] value)
        {
            var builder = new StringBuilder(value.Length * 2);
            foreach (var item in value)
            {
                builder.Append(item.ToString("x2", CultureInfo.InvariantCulture));
            }

            return builder.ToString();
        }

        private sealed class LocalBufferLayout
        {
            internal LocalBufferLayout(
                int descriptorCount,
                int readerGuardSlots,
                int guardStride,
                long arenaSizeBytes,
                string layoutFingerprint)
            {
                DescriptorCount = descriptorCount;
                ReaderGuardSlots = readerGuardSlots;
                GuardStride = guardStride;
                ArenaSizeBytes = arenaSizeBytes;
                LayoutFingerprint = layoutFingerprint;
            }

            internal int DescriptorCount { get; }

            internal int ReaderGuardSlots { get; }

            internal int GuardStride { get; }

            internal long ArenaSizeBytes { get; }

            internal string LayoutFingerprint { get; }
        }

        internal sealed class LocalBufferMappingLease : IDisposable
        {
            private MemoryMappedViewAccessor? view;
            private Action? release;

            internal LocalBufferMappingLease(
                MemoryMappedViewAccessor view,
                long offset,
                long size,
                Action release)
            {
                this.view = view;
                this.release = release;
                Offset = offset;
                Size = size;
            }

            internal MemoryMappedViewAccessor View =>
                view ?? throw new ObjectDisposedException(nameof(LocalBufferMappingLease));

            internal long Offset { get; }

            internal long Size { get; }

            public void Dispose()
            {
                view = null;
                var callback = release;
                release = null;
                callback?.Invoke();
            }
        }
    }
}
