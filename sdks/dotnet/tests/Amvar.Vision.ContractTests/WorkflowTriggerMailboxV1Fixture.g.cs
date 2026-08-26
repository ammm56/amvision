// 由 workflow_trigger_mailbox.v1.json 自动生成；禁止手工修改。
using System;
using System.Text;
using Amvar.Vision.SharedMemory;

namespace Amvar.Vision.ContractTests
{
    internal static class WorkflowTriggerMailboxV1Fixture
    {
        internal static void Verify()
        {
            AssertHex(BuildFileHeader(), "414d565754473100010000008000000080000000400100000000080000000800400110000001000040000000000008004000080040000000010000000000000008070605040302011817161514131211000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000", "file header");
            AssertHex(BuildDescriptorHeader(), "050000007f0000008899aabbccddeeff080706050403020100112233445566778899aabbccddeeff11223344556677888877665544332211e09304000300000009070605040302010000080001000000443322110000000044443333222211118888777766665555ccccbbbbaaaa999900bcaa9900ffeedd000020000000000000ec5e0000000000807060504030201080070000380400000300000080e9ffff010000000200000001000000010000000000100000008000010000000100000088776655ff00000002000000020000000200000000000000f0debc9a7856341221436587a9cbed0f090000000000000078695a4b3c2d1e0fa8a7a6a5a4a3a2a100000000050000001817161514131211000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000", "descriptor header");
            AssertHex(BuildPageHeader(), "02000000ffffffff0000080001000000d4c3b2a17f0000008899aabbccddeeff1122334455667788080706050403020101000000000000000000000000000000", "page header");
            var checksumInput = Encoding.UTF8.GetBytes("amvision-workflow-trigger-mailbox-v1");
            if (Crc32Ieee.Compute(checksumInput) != 1926652209U)
            {
                throw new InvalidOperationException("CRC32 IEEE fixture 不一致。");
            }
        }

        private static byte[] BuildFileHeader()
        {
            var buffer = new byte[WorkflowTriggerMailboxV1.FileHeaderSize];
            CopyHex(buffer, WorkflowTriggerMailboxV1.FileHeaderMagicOffset, "414d565754473100");
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderVersionOffset, 1U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderHeaderSizeOffset, 128U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderDescriptorCountOffset, 128U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderDescriptorHeaderSizeOffset, 320U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderInlineRequestCapacityOffset, 524288U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderInlineResponseCapacityOffset, 524288U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderDescriptorStrideOffset, 1048896U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderOverflowPageCountOffset, 256U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderPageHeaderSizeOffset, 64U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderPageCapacityOffset, 524288U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderPageStrideOffset, 524352U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderMaxPagesPerResponseOffset, 64U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderChecksumAlgorithmOffset, 1U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.FileHeaderFlagsOffset, 0U);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.FileHeaderServerEpochOffset, 72623859790382856UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.FileHeaderCreatedAtNsOffset, 1230066625199609624UL);
            return buffer;
        }

        private static byte[] BuildDescriptorHeader()
        {
            var buffer = new byte[WorkflowTriggerMailboxV1.DescriptorHeaderSize];
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderStateOffset, 5U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderDescriptorIndexOffset, 127U);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderGenerationOffset, 18441921395520346504UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderServerEpochOffset, 72623859790382856UL);
            CopyHex(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderRequestIdOffset, "00112233445566778899aabbccddeeff");
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderOwnerTokenOffset, 9833440827789222417UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderDeadlineNsOffset, 1234605616436508552UL);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderAcceptedTimeoutMsOffset, 300000U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderFlagsOffset, 3U);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderRouteGenerationOffset, 72623859790382857UL);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderRequestSizeOffset, 524288U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderRequestChecksumAlgorithmOffset, 1U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderRequestChecksumOffset, 287454020U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderRequestReservedOffset, 0U);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderInputLeaseIdFingerprintOffset, 1229801703532086340UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderInputBufferIdFingerprintOffset, 6148933456521300104UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderBrokerEpochOffset, 11068065209510513868UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderBufferGenerationOffset, 15991999704882396160UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderBufferOffsetOffset, 2097152UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderBufferContentLengthOffset, 6220800UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderMediaTypeFingerprintOffset, 1161981756646125696UL);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderImageWidthOffset, 1920U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderImageHeightOffset, 1080U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderImageChannelsOffset, 3U);
            WriteInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderImageRowStrideOffset, -5760);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderImageDtypeOffset, 1U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderImageLayoutOffset, 2U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderImagePixelFormatOffset, 1U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderImageFlagsOffset, 1U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderResponseSizeOffset, 1048576U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderResponseRawSizeOffset, 8388608U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderResponseCodecOffset, 1U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderResponseChecksumAlgorithmOffset, 1U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderResponseChecksumOffset, 1432778632U);
            WriteInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderFirstPageIndexOffset, 255);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderResponsePageCountOffset, 2U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderResponseOutputLeaseCountOffset, 2U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderHandoffStateOffset, 2U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderErrorCodeOffset, 0U);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderWorkerInstanceFingerprintOffset, 1311768467463790320UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderRuntimeRevisionFingerprintOffset, 1147797409030816545UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderRuntimeGenerationOffset, 9UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderSnapshotFingerprintOffset, 1089357896855742840UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderUpdatedAtNsOffset, 11647051513882650536UL);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderCancelReasonOffset, 0U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderResponseFlagsOffset, 5U);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.DescriptorHeaderResponseAckDeadlineNsOffset, 1230066625199609624UL);
            return buffer;
        }

        private static byte[] BuildPageHeader()
        {
            var buffer = new byte[WorkflowTriggerMailboxV1.PageHeaderSize];
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.PageHeaderStateOffset, 2U);
            WriteInt32(buffer, WorkflowTriggerMailboxV1.PageHeaderNextPageIndexOffset, -1);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.PageHeaderUsedSizeOffset, 524288U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.PageHeaderChecksumAlgorithmOffset, 1U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.PageHeaderChecksumOffset, 2712847316U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.PageHeaderDescriptorIndexOffset, 127U);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.PageHeaderDescriptorGenerationOffset, 18441921395520346504UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.PageHeaderOwnerTokenOffset, 9833440827789222417UL);
            WriteUInt64(buffer, WorkflowTriggerMailboxV1.PageHeaderServerEpochOffset, 72623859790382856UL);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.PageHeaderOrdinalOffset, 1U);
            WriteUInt32(buffer, WorkflowTriggerMailboxV1.PageHeaderFlagsOffset, 0U);
            return buffer;
        }

        private static void WriteUInt32(byte[] buffer, int offset, uint value)
        {
            buffer[offset] = (byte)value;
            buffer[offset + 1] = (byte)(value >> 8);
            buffer[offset + 2] = (byte)(value >> 16);
            buffer[offset + 3] = (byte)(value >> 24);
        }

        private static void WriteInt32(byte[] buffer, int offset, int value)
        {
            WriteUInt32(buffer, offset, unchecked((uint)value));
        }

        private static void WriteUInt64(byte[] buffer, int offset, ulong value)
        {
            WriteUInt32(buffer, offset, (uint)value);
            WriteUInt32(buffer, offset + 4, (uint)(value >> 32));
        }

        private static void CopyHex(byte[] buffer, int offset, string text)
        {
            for (var index = 0; index < text.Length; index += 2)
            {
                buffer[offset + index / 2] = Convert.ToByte(text.Substring(index, 2), 16);
            }
        }

        private static void AssertHex(byte[] actual, string expected, string name)
        {
            var text = new StringBuilder(actual.Length * 2);
            foreach (var value in actual)
            {
                text.Append(value.ToString("x2"));
            }

            if (!string.Equals(text.ToString(), expected, StringComparison.Ordinal))
            {
                throw new InvalidOperationException(name + " fixture 不一致。");
            }
        }
    }
}
