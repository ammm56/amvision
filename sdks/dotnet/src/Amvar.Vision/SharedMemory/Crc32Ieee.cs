using System;

namespace Amvar.Vision.SharedMemory
{
    /// <summary>
    /// Workflow Trigger binary contract 使用的 CRC32 IEEE 增量校验器。
    /// </summary>
    internal sealed class Crc32Ieee
    {
        private static readonly uint[][] Tables = BuildTables();
        private uint _state = uint.MaxValue;

        internal uint Value => _state ^ uint.MaxValue;

        internal void Reset()
        {
            _state = uint.MaxValue;
        }

        internal void Append(byte[] buffer, int offset, int count)
        {
            if (buffer == null)
            {
                throw new ArgumentNullException(nameof(buffer));
            }

            if (offset < 0 || count < 0 || offset > buffer.Length - count)
            {
                throw new ArgumentOutOfRangeException(nameof(offset));
            }

            var crc = _state;
            var table0 = Tables[0];
            var table1 = Tables[1];
            var table2 = Tables[2];
            var table3 = Tables[3];
            var table4 = Tables[4];
            var table5 = Tables[5];
            var table6 = Tables[6];
            var table7 = Tables[7];
            var table8 = Tables[8];
            var table9 = Tables[9];
            var table10 = Tables[10];
            var table11 = Tables[11];
            var table12 = Tables[12];
            var table13 = Tables[13];
            var table14 = Tables[14];
            var table15 = Tables[15];
            var end = offset + count;
            while (offset <= end - 16)
            {
                var first = crc
                    ^ buffer[offset]
                    ^ ((uint)buffer[offset + 1] << 8)
                    ^ ((uint)buffer[offset + 2] << 16)
                    ^ ((uint)buffer[offset + 3] << 24);
                crc = table15[first & 0xff]
                    ^ table14[(first >> 8) & 0xff]
                    ^ table13[(first >> 16) & 0xff]
                    ^ table12[first >> 24]
                    ^ table11[buffer[offset + 4]]
                    ^ table10[buffer[offset + 5]]
                    ^ table9[buffer[offset + 6]]
                    ^ table8[buffer[offset + 7]]
                    ^ table7[buffer[offset + 8]]
                    ^ table6[buffer[offset + 9]]
                    ^ table5[buffer[offset + 10]]
                    ^ table4[buffer[offset + 11]]
                    ^ table3[buffer[offset + 12]]
                    ^ table2[buffer[offset + 13]]
                    ^ table1[buffer[offset + 14]]
                    ^ table0[buffer[offset + 15]];
                offset += 16;
            }

            while (offset <= end - 8)
            {
                var first = crc
                    ^ buffer[offset]
                    ^ ((uint)buffer[offset + 1] << 8)
                    ^ ((uint)buffer[offset + 2] << 16)
                    ^ ((uint)buffer[offset + 3] << 24);
                crc = table7[first & 0xff]
                    ^ table6[(first >> 8) & 0xff]
                    ^ table5[(first >> 16) & 0xff]
                    ^ table4[first >> 24]
                    ^ table3[buffer[offset + 4]]
                    ^ table2[buffer[offset + 5]]
                    ^ table1[buffer[offset + 6]]
                    ^ table0[buffer[offset + 7]];
                offset += 8;
            }

            while (offset < end)
            {
                crc = table0[(crc ^ buffer[offset]) & 0xff] ^ (crc >> 8);
                offset += 1;
            }

            _state = crc;
        }

        internal unsafe void Append(ReadOnlySpan<byte> buffer)
        {
            fixed (byte* pointer = buffer)
            {
                Append(pointer, buffer.Length);
            }
        }

        private unsafe void Append(byte* buffer, int length)
        {
            var crc = _state;
            var table0 = Tables[0];
            var table1 = Tables[1];
            var table2 = Tables[2];
            var table3 = Tables[3];
            var table4 = Tables[4];
            var table5 = Tables[5];
            var table6 = Tables[6];
            var table7 = Tables[7];
            var table8 = Tables[8];
            var table9 = Tables[9];
            var table10 = Tables[10];
            var table11 = Tables[11];
            var table12 = Tables[12];
            var table13 = Tables[13];
            var table14 = Tables[14];
            var table15 = Tables[15];
            var offset = 0;
            var end = length;
            while (offset <= end - 16)
            {
                var first = crc
                    ^ buffer[offset]
                    ^ ((uint)buffer[offset + 1] << 8)
                    ^ ((uint)buffer[offset + 2] << 16)
                    ^ ((uint)buffer[offset + 3] << 24);
                crc = table15[first & 0xff]
                    ^ table14[(first >> 8) & 0xff]
                    ^ table13[(first >> 16) & 0xff]
                    ^ table12[first >> 24]
                    ^ table11[buffer[offset + 4]]
                    ^ table10[buffer[offset + 5]]
                    ^ table9[buffer[offset + 6]]
                    ^ table8[buffer[offset + 7]]
                    ^ table7[buffer[offset + 8]]
                    ^ table6[buffer[offset + 9]]
                    ^ table5[buffer[offset + 10]]
                    ^ table4[buffer[offset + 11]]
                    ^ table3[buffer[offset + 12]]
                    ^ table2[buffer[offset + 13]]
                    ^ table1[buffer[offset + 14]]
                    ^ table0[buffer[offset + 15]];
                offset += 16;
            }

            while (offset <= end - 8)
            {
                var first = crc
                    ^ buffer[offset]
                    ^ ((uint)buffer[offset + 1] << 8)
                    ^ ((uint)buffer[offset + 2] << 16)
                    ^ ((uint)buffer[offset + 3] << 24);
                crc = table7[first & 0xff]
                    ^ table6[(first >> 8) & 0xff]
                    ^ table5[(first >> 16) & 0xff]
                    ^ table4[first >> 24]
                    ^ table3[buffer[offset + 4]]
                    ^ table2[buffer[offset + 5]]
                    ^ table1[buffer[offset + 6]]
                    ^ table0[buffer[offset + 7]];
                offset += 8;
            }

            while (offset < end)
            {
                crc = table0[(crc ^ buffer[offset]) & 0xff] ^ (crc >> 8);
                offset += 1;
            }

            _state = crc;
        }

        internal static uint Compute(byte[] buffer)
        {
            var checksum = new Crc32Ieee();
            checksum.Append(buffer, 0, buffer.Length);
            return checksum.Value;
        }

        private static uint[][] BuildTables()
        {
            var tables = new uint[16][];
            tables[0] = new uint[256];
            for (uint index = 0; index < 256; index += 1)
            {
                var value = index;
                for (var bit = 0; bit < 8; bit += 1)
                {
                    value = (value & 1) != 0
                        ? 0xedb88320U ^ (value >> 1)
                        : value >> 1;
                }

                tables[0][index] = value;
            }

            for (var tableIndex = 1; tableIndex < tables.Length; tableIndex += 1)
            {
                tables[tableIndex] = new uint[256];
                for (var index = 0; index < 256; index += 1)
                {
                    var previous = tables[tableIndex - 1][index];
                    tables[tableIndex][index] =
                        tables[0][previous & 0xff] ^ (previous >> 8);
                }
            }

            return tables;
        }
    }
}
