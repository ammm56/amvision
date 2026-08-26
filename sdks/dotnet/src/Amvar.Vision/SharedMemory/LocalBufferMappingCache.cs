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
        private const int StateWriting = 1;
        private readonly object syncRoot = new object();
        private readonly SharedMemoryTriggerClientOptions options;
        private readonly FileStream arenaFile;
        private readonly FileStream allocatorFile;
        private readonly MemoryMappedFile arenaMap;
        private readonly MemoryMappedFile allocatorMap;
        private readonly MemoryMappedViewAccessor arenaView;
        private readonly MemoryMappedViewAccessor allocatorView;
        private bool disposed;
        private bool disposeRequested;
        private int activeLeaseCount;

        internal LocalBufferMappingCache(SharedMemoryTriggerClientOptions options)
        {
            this.options = options ?? throw new ArgumentNullException(nameof(options));
            arenaFile = OpenExact(options.ArenaPath, options.ArenaSizeBytes);
            try
            {
                allocatorFile = new FileStream(
                    options.AllocatorPath,
                    FileMode.Open,
                    FileAccess.ReadWrite,
                    FileShare.ReadWrite | FileShare.Delete);
                try
                {
                    arenaMap = MemoryMappedFile.CreateFromFile(
                        arenaFile,
                        null,
                        0,
                        MemoryMappedFileAccess.ReadWrite,
                        HandleInheritability.None,
                        false);
                    allocatorMap = MemoryMappedFile.CreateFromFile(
                        allocatorFile,
                        null,
                        0,
                        MemoryMappedFileAccess.ReadWrite,
                        HandleInheritability.None,
                        false);
                    arenaView = arenaMap.CreateViewAccessor(
                        0,
                        options.ArenaSizeBytes,
                        MemoryMappedFileAccess.ReadWrite);
                    allocatorView = allocatorMap.CreateViewAccessor(
                        0,
                        allocatorFile.Length,
                        MemoryMappedFileAccess.ReadWrite);
                    ValidateHeader();
                }
                catch
                {
                    allocatorFile.Dispose();
                    throw;
                }
            }
            catch
            {
                arenaFile.Dispose();
                throw;
            }
        }

        internal string GuardPath => options.GuardPath;

        internal int WriterGuardOffset(int descriptorIndex)
        {
            return checked(descriptorIndex * (2 + options.ReaderGuardSlots) + 1);
        }

        internal int ReaderGuardOffset(int descriptorIndex)
        {
            return checked(descriptorIndex * (2 + options.ReaderGuardSlots) + 2);
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
            if (!string.Equals(allocation.ArenaId, options.ArenaId, StringComparison.Ordinal)
                || allocation.DescriptorIndex < 0
                || allocation.DescriptorGeneration <= 0
                || allocation.Offset < 0
                || allocation.ContentLength <= 0
                || allocation.AllocationCapacityBytes < allocation.ContentLength
                || allocation.Offset > options.ArenaSizeBytes - allocation.AllocationCapacityBytes)
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
            allocatorView.ReadArray(56, headerEpoch, 0, headerEpoch.Length);
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
            if (!string.Equals(arenaId, options.ArenaId, StringComparison.Ordinal)
                || descriptorIndex < 0
                || descriptorGeneration <= 0
                || offset < 0
                || contentLength <= 0
                || allocationCapacityBytes < contentLength
                || offset > options.ArenaSizeBytes - allocationCapacityBytes)
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
            allocatorView.ReadArray(56, headerEpoch, 0, headerEpoch.Length);
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

        private void ValidateHeader()
        {
            var magic = new byte[8];
            allocatorView.ReadArray(0, magic, 0, magic.Length);
            if (!string.Equals(Encoding.ASCII.GetString(magic), "AMVLBA01", StringComparison.Ordinal)
                || allocatorView.ReadUInt32(8) != 1
                || allocatorView.ReadUInt32(12) != HeaderSize
                || allocatorView.ReadUInt32(16) != DescriptorStride
                || checked((long)allocatorView.ReadUInt64(24)) != options.ArenaSizeBytes)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "LocalBuffer allocator layout does not match the SDK configuration.");
            }
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
        }

        private static FileStream OpenExact(string path, long expectedLength)
        {
            var file = new FileStream(
                Path.GetFullPath(path),
                FileMode.Open,
                FileAccess.ReadWrite,
                FileShare.ReadWrite | FileShare.Delete);
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
