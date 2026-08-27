// 由 local_message_channel.v1 + workflow_trigger_mailbox.v1 生成；禁止手工修改。
namespace Amvar.Vision.SharedMemory
{
    internal static class WorkflowTriggerMailboxV1
    {
        internal const string ContractId = "amvision.workflow-trigger-mailbox.v1";
        internal const string ProfileId = "workflow-trigger-mailbox.v1";
        internal const int Version = 1;
        internal const int ChannelKindMailbox = 1;
        internal const int EndianMarker = 0x01020304;
        internal const string LayoutFingerprintHex = "a235669d2fe1f02848bbf816e06efde0f4c1eaae4a19943e2878d9593e83f345";
        internal const string RelativeMmapPath = "local-message/workflow-trigger/mailbox.mmap";
        internal const string RelativeGuardPath = "local-message/workflow-trigger/access.guard";

        internal const int DescriptorCount = 128;
        internal const int InlineRequestCapacityBytes = 65536;
        internal const int InlineResponseCapacityBytes = 65536;
        internal const int OverflowPageCount = 512;
        internal const int OverflowPageCapacityBytes = 262144;
        internal const int MaxOverflowPagesPerResponse = 129;
        internal const int MaxRequestBytes = 65536;
        internal const int PublicResponseCapacityBytes = 33554432;
        internal const int MaxResponseBytes = 33619968;
        internal const int CompressionThresholdBytes = 65536;

        internal const int CommonHeaderSize = 256;
        internal const int MailboxHeaderSize = 256;
        internal const int DescriptorHeaderSize = 256;
        internal const int PageHeaderSize = 64;
        internal const int DescriptorStrideBytes = 131328;
        internal const long DescriptorRegionOffset = 512;
        internal const int PageStrideBytes = 262208;
        internal const long PageRegionOffset = 16810496;
        internal const long MailboxFileSizeBytes = 151060992;

        internal const int CommonMagicOffset = 0;
        internal const int CommonVersionOffset = 8;
        internal const int CommonChannelKindOffset = 10;
        internal const int CommonEndianOffset = 12;
        internal const int CommonFingerprintOffset = 16;
        internal const int CommonOwnerEpochOffset = 64;
        internal const int CommonFlagsOffset = 84;
        internal const int FileFlagClosed = 1;

        internal const int MailboxDescriptorCountOffset = 256;
        internal const int MailboxDescriptorHeaderSizeOffset = 260;
        internal const int MailboxDescriptorStrideOffset = 264;
        internal const int MailboxInlineRequestCapacityOffset = 268;
        internal const int MailboxInlineResponseCapacityOffset = 272;
        internal const int MailboxPageHeaderSizeOffset = 276;
        internal const int MailboxPageCapacityOffset = 280;
        internal const int MailboxPageCountOffset = 284;
        internal const int MailboxMaxPagesPerResponseOffset = 288;
        internal const int MailboxMaxRequestBytesOffset = 292;
        internal const int MailboxMaxResponseBytesOffset = 296;
        internal const int MailboxCompressionThresholdOffset = 300;
        internal const int MailboxDescriptorRegionOffset = 304;
        internal const int MailboxPageRegionOffset = 312;
        internal const int MailboxFileSizeOffset = 320;
        internal const int MailboxPollIntervalNsOffset = 328;
        internal const int MailboxProfileIdOffset = 336;

        internal const int DescriptorStateOffset = 0;
        internal const int DescriptorFlagsOffset = 4;
        internal const int DescriptorGenerationOffset = 8;
        internal const int DescriptorOwnerEpochOffset = 16;
        internal const int DescriptorRequestIdOffset = 24;
        internal const int DescriptorOwnerTokenOffset = 40;
        internal const int DescriptorDeadlineNsOffset = 48;
        internal const int DescriptorRequestSizeOffset = 56;
        internal const int DescriptorRequestChecksumOffset = 60;
        internal const int DescriptorResponseRawSizeOffset = 64;
        internal const int DescriptorResponseChecksumOffset = 68;
        internal const int DescriptorFirstPageIndexOffset = 72;
        internal const int DescriptorResponsePageCountOffset = 76;
        internal const int DescriptorTransportErrorCodeOffset = 80;
        internal const int DescriptorResponseStoredSizeOffset = 84;
        internal const int DescriptorResponseAckDeadlineNsOffset = 88;
        internal const int DescriptorUpdatedAtNsOffset = 96;

        internal const int ExtensionPhaseOffset = 104;
        internal const int ExtensionCancelReasonOffset = 108;
        internal const int ExtensionRequestedTimeoutMsOffset = 112;
        internal const int ExtensionAcceptedTimeoutMsOffset = 116;
        internal const int ExtensionRouteGenerationOffset = 120;
        internal const int ExtensionErrorCodeOffset = 128;
        internal const int ExtensionOutputLeaseCountOffset = 132;
        internal const int ExtensionHandoffStateOffset = 136;

        internal const int MailboxStateFree = 0;
        internal const int MailboxStateWritingRequest = 1;
        internal const int MailboxStateRequest = 2;
        internal const int MailboxStateProcessing = 3;
        internal const int MailboxStateResponse = 4;
        internal const int MailboxFlagCancelRequested = 1;
        internal const int MailboxFlagAcked = 2;
        internal const int MailboxFlagResponseCompressed = 4;
        internal const int MailboxErrorNone = 0;
        internal const int MailboxErrorDeadlineExceeded = 1;
        internal const int MailboxErrorCancelled = 2;
        internal const int MailboxErrorInvalidMessage = 3;
        internal const int MailboxErrorCapacityExhausted = 4;
        internal const int MailboxErrorServerFailure = 5;

        internal const int PhasePrepare = 1;
        internal const int PhaseWriting = 2;
        internal const int PhaseRequest = 3;
        internal const int PhaseResponse = 5;

        internal const int PageStateFree = 0;
        internal const int PageStateReserved = 1;
        internal const int PageStatePublished = 2;
        internal const int PageStateOffset = 0;
        internal const int PageDescriptorIndexOffset = 8;
        internal const int PageOrdinalOffset = 12;
        internal const int PageDescriptorGenerationOffset = 16;
        internal const int PageNextPageIndexOffset = 24;
        internal const int PageUsedSizeOffset = 28;
        internal const int PageChecksumOffset = 32;
        internal const int PageTokenOffset = 36;
        internal const int PageOwnerEpochOffset = 44;

        internal const int CancelReasonNone = 0;
        internal const int CancelReasonRequestTimeout = 1;
        internal const int CancelReasonExplicit = 2;
        internal const int CancelReasonClientShutdown = 3;
        internal const int HandoffStateNone = 0;
        internal const int HandoffStatePending = 1;
        internal const int HandoffStateComplete = 2;
        internal const int HandoffStateDetached = 3;

        internal const int ErrorCodeNone = 0;
        internal const int ErrorCodeInvalidRequest = 1;
        internal const int ErrorCodeTriggerSourceNotFound = 2;
        internal const int ErrorCodeRouteGenerationMismatch = 3;
        internal const int ErrorCodeTriggerSourceBusy = 4;
        internal const int ErrorCodeWorkflowRuntimeBusy = 5;
        internal const int ErrorCodeWorkflowExecutorBusy = 6;
        internal const int ErrorCodeLocalBufferCapacityExhausted = 7;
        internal const int ErrorCodeLocalBufferOutputCapacityExhausted = 8;
        internal const int ErrorCodeTriggerRequestTooLarge = 9;
        internal const int ErrorCodeTriggerResponseTooLarge = 10;
        internal const int ErrorCodeTriggerResponseCapacityExhausted = 11;
        internal const int ErrorCodeChecksumMismatch = 12;
        internal const int ErrorCodeIdentityMismatch = 13;
        internal const int ErrorCodeDeadlineExceeded = 14;
        internal const int ErrorCodeCancelled = 15;
        internal const int ErrorCodeWorkflowExecutionFailed = 16;
        internal const int ErrorCodeOutputHandoffFailed = 17;
        internal const int ErrorCodeProtocolError = 18;
        internal const int ErrorCodeServerUnavailable = 19;
    }
}
