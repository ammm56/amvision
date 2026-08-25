using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Linq;

namespace Amvar.Vision.SharedMemory
{
    /// <summary>
    /// 按 LocalBuffer 文件、Broker epoch 和物理槽位复用 mmap；epoch 变化时
    /// 被替换的映射只在最后一个 writer 释放后关闭。单槽映射同时支持
    /// 32-bit 工业相机宿主进程，避免映射整个大容量 pool。
    /// </summary>
    internal sealed class LocalBufferMappingCache : IDisposable
    {
        private readonly object syncRoot = new object();
        private readonly Dictionary<string, MappingEntry> entries =
            new Dictionary<string, MappingEntry>(StringComparer.OrdinalIgnoreCase);
        private bool disposed;

        internal LocalBufferMappingLease Acquire(WorkflowTriggerAllocation allocation)
        {
            if (allocation == null)
            {
                throw new ArgumentNullException(nameof(allocation));
            }

            var fullPath = Path.GetFullPath(allocation.Path);
            var physicalKey = BuildPhysicalKey(
                fullPath,
                allocation.BrokerEpoch);
            var key = BuildSlotKey(
                physicalKey,
                allocation.Offset);
            lock (syncRoot)
            {
                ThrowIfDisposed();
                foreach (var stale in entries.Values
                    .Where(item => string.Equals(item.FullPath, fullPath, StringComparison.OrdinalIgnoreCase)
                        && !string.Equals(item.PhysicalKey, physicalKey, StringComparison.OrdinalIgnoreCase))
                    .ToArray())
                {
                    stale.Stale = true;
                    TryRemoveAndDispose(stale);
                }

                if (!entries.TryGetValue(key, out var entry))
                {
                    entry = MappingEntry.Open(
                        key,
                        physicalKey,
                        fullPath,
                        allocation.BrokerEpoch,
                        allocation.Offset,
                        allocation.SlotCapacityBytes);
                    entries.Add(key, entry);
                }

                entry.ReferenceCount += 1;
                return new LocalBufferMappingLease(
                    this,
                    entry,
                    allocation.Offset,
                    allocation.Size);
            }
        }

        public void Dispose()
        {
            lock (syncRoot)
            {
                if (disposed)
                {
                    return;
                }

                disposed = true;
                foreach (var entry in entries.Values.ToArray())
                {
                    entry.Stale = true;
                    TryRemoveAndDispose(entry);
                }
            }
        }

        private void Release(MappingEntry entry)
        {
            lock (syncRoot)
            {
                if (entry.ReferenceCount <= 0)
                {
                    throw new InvalidOperationException("LocalBuffer mapping reference count is invalid.");
                }

                entry.ReferenceCount -= 1;
                if (disposed || entry.Stale)
                {
                    TryRemoveAndDispose(entry);
                }
            }
        }

        private void TryRemoveAndDispose(MappingEntry entry)
        {
            if (entry.ReferenceCount != 0)
            {
                return;
            }

            entries.Remove(entry.Key);
            entry.Dispose();
        }

        private void ThrowIfDisposed()
        {
            if (disposed)
            {
                throw new ObjectDisposedException(nameof(LocalBufferMappingCache));
            }
        }

        private static string BuildPhysicalKey(
            string fullPath,
            string brokerEpoch)
        {
            return fullPath + "\n" + brokerEpoch;
        }

        private static string BuildSlotKey(
            string physicalKey,
            long offset)
        {
            return physicalKey
                + "\n"
                + offset.ToString(CultureInfo.InvariantCulture);
        }

        internal sealed class MappingEntry : IDisposable
        {
            private readonly FileStream file;
            private readonly MemoryMappedFile map;

            private MappingEntry(
                string key,
                string physicalKey,
                string fullPath,
                string brokerEpoch,
                FileStream file,
                MemoryMappedFile map,
                MemoryMappedViewAccessor view)
            {
                Key = key;
                PhysicalKey = physicalKey;
                FullPath = fullPath;
                BrokerEpoch = brokerEpoch;
                this.file = file;
                this.map = map;
                View = view;
            }

            internal string Key { get; }

            internal string PhysicalKey { get; }

            internal string FullPath { get; }

            internal string BrokerEpoch { get; }

            internal MemoryMappedViewAccessor View { get; }

            internal int ReferenceCount { get; set; }

            internal bool Stale { get; set; }

            internal static MappingEntry Open(
                string key,
                string physicalKey,
                string fullPath,
                string brokerEpoch,
                long offset,
                long size)
            {
                var file = new FileStream(
                    fullPath,
                    FileMode.Open,
                    FileAccess.ReadWrite,
                    FileShare.ReadWrite | FileShare.Delete);
                try
                {
                    if (offset < 0 || size <= 0 || offset > file.Length - size)
                    {
                        throw new SharedMemoryTriggerException(
                            "protocol_error",
                            "Workflow Trigger allocation is outside the LocalBuffer pool file.");
                    }

                    var map = MemoryMappedFile.CreateFromFile(
                        file,
                        null,
                        0,
                        MemoryMappedFileAccess.ReadWrite,
                        HandleInheritability.None,
                        false);
                    try
                    {
                        var view = map.CreateViewAccessor(
                            offset,
                            size,
                            MemoryMappedFileAccess.ReadWrite);
                        return new MappingEntry(
                            key,
                            physicalKey,
                            fullPath,
                            brokerEpoch,
                            file,
                            map,
                            view);
                    }
                    catch
                    {
                        map.Dispose();
                        throw;
                    }
                }
                catch
                {
                    file.Dispose();
                    throw;
                }
            }

            public void Dispose()
            {
                View.Dispose();
                map.Dispose();
                file.Dispose();
            }
        }

        internal sealed class LocalBufferMappingLease : IDisposable
        {
            private readonly LocalBufferMappingCache owner;
            private MappingEntry? entry;

            internal LocalBufferMappingLease(
                LocalBufferMappingCache owner,
                MappingEntry entry,
                long offset,
                long size)
            {
                this.owner = owner;
                this.entry = entry;
                Offset = offset;
                Size = size;
            }

            internal MemoryMappedViewAccessor View =>
                entry?.View ?? throw new ObjectDisposedException(nameof(LocalBufferMappingLease));

            internal long Offset { get; }

            internal long Size { get; }

            public void Dispose()
            {
                var current = entry;
                if (current == null)
                {
                    return;
                }

                entry = null;
                owner.Release(current);
            }
        }
    }
}
