// 由 local_message_channel.v1 fixture 冻结；正式业务迁移前只用于跨语言布局门禁。
using System;

namespace Amvar.Vision.ContractTests
{
    internal static class LocalMessageChannelV1Fixture
    {
        internal const string WorkflowTriggerFingerprint = "a235669d2fe1f02848bbf816e06efde0f4c1eaae4a19943e2878d9593e83f345";
        internal const string CommonHeaderFieldsHex = "414d564c4d5347000100010004030201a235669d2fe1f02848bbf816e06efde0f4c1eaae4a19943e2878d9593e83f3457766554433221100ffeeddccbbaa9988080706050403020118171615141312114433221100000000";
        internal const string MailboxProfileHeaderFieldsHex = "80000000000100000001020000000100000001004000000000000400000200008100000000000100000001020000010000020000000000000082000100000000000201090000000040420f0000000000776f726b666c6f772d747269676765722d6d61696c626f782e763100000000000000000000000000000000000000000000000000000000000000000000000000";
        internal const string MailboxDescriptorHeaderHex = "02000000000000000807060504030201181716151413121100112233445566778899aabbccddeeff2827262524232221383736353433323103000000c24124350000000000000000ffffffff000000000000000000000000000000000000000048474645444342410000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";
        internal const string MailboxPageHeaderHex = "020000000000000003000000020000000807060504030201ffffffff04000000a52017db58575655545352511817161514131211000000000000000000000000";

        internal static void Verify()
        {
            var common = ParseHex(CommonHeaderFieldsHex);
            var profile = ParseHex(MailboxProfileHeaderFieldsHex);
            var descriptor = ParseHex(MailboxDescriptorHeaderHex);
            var page = ParseHex(MailboxPageHeaderHex);
            Assert(common.Length == 88, "LocalMessage common fields size mismatch");
            Assert(profile.Length == 144, "LocalMessage Mailbox profile fields size mismatch");
            Assert(descriptor.Length == 256, "LocalMessage descriptor header size mismatch");
            Assert(page.Length == 64, "LocalMessage page header size mismatch");
            Assert(BitConverter.ToUInt16(common, 8) == 1, "LocalMessage version mismatch");
            Assert(BitConverter.ToUInt16(common, 10) == 1, "LocalMessage Mailbox kind mismatch");
            Assert(BitConverter.ToUInt32(common, 12) == 0x01020304U, "LocalMessage endian marker mismatch");
            Assert(ToHex(common, 16, 32) == WorkflowTriggerFingerprint, "LocalMessage fingerprint mismatch");
            Assert(BitConverter.ToUInt32(profile, 0) == 128U, "LocalMessage descriptor count mismatch");
            Assert(BitConverter.ToUInt32(profile, 24) == 262144U, "LocalMessage page capacity mismatch");
            Assert(BitConverter.ToUInt32(descriptor, 0) == 2U, "LocalMessage REQUEST state mismatch");
            Assert(BitConverter.ToInt32(page, 24) == -1, "LocalMessage end page marker mismatch");
        }

        private static byte[] ParseHex(string value)
        {
            var bytes = new byte[value.Length / 2];
            for (var index = 0; index < bytes.Length; index++)
            {
                bytes[index] = Convert.ToByte(value.Substring(index * 2, 2), 16);
            }
            return bytes;
        }

        private static string ToHex(byte[] value, int offset, int length)
        {
            return BitConverter.ToString(value, offset, length).Replace("-", string.Empty).ToLowerInvariant();
        }

        private static void Assert(bool condition, string message)
        {
            if (!condition)
            {
                throw new InvalidOperationException(message);
            }
        }
    }
}
