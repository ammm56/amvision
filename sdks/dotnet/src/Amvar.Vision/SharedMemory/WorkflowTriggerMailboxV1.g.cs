// 由 local_message_channel.v1 + workflow_trigger_rpc_extension.v1 生成；禁止手工修改。
namespace Amvar.Vision.SharedMemory
{
    internal static class WorkflowTriggerMailboxV1
    {
        internal const string ContractId = "amvision.workflow-trigger-rpc-extension.v1";
        internal const string ProfileId = "workflow-trigger-rpc.v1";
        internal const int Version = 1;
        internal const int ChannelKindRpc = 1;
        internal const int EndianMarker = 0x01020304;
        internal const string LayoutFingerprintHex = "1fa3998808b1cdb1d8758839a954d2098d92b337dae246c4f58cbfc64038ed2c";
        internal const string RelativeMmapPath = "local-message/workflow-trigger-main.rpc.mmap";
        internal const string GuardSuffix = ".guard";

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
        internal const int RpcHeaderSize = 256;
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

        internal const int RpcDescriptorCountOffset = 256;
        internal const int RpcDescriptorHeaderSizeOffset = 260;
        internal const int RpcDescriptorStrideOffset = 264;
        internal const int RpcInlineRequestCapacityOffset = 268;
        internal const int RpcInlineResponseCapacityOffset = 272;
        internal const int RpcPageHeaderSizeOffset = 276;
        internal const int RpcPageCapacityOffset = 280;
        internal const int RpcPageCountOffset = 284;
        internal const int RpcMaxPagesPerResponseOffset = 288;
        internal const int RpcMaxRequestBytesOffset = 292;
        internal const int RpcMaxResponseBytesOffset = 296;
        internal const int RpcCompressionThresholdOffset = 300;
        internal const int RpcDescriptorRegionOffset = 304;
        internal const int RpcPageRegionOffset = 312;
        internal const int RpcFileSizeOffset = 320;
        internal const int RpcPollIntervalNsOffset = 328;
        internal const int RpcProfileIdOffset = 336;

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

        internal const int RpcStateFree = 0;
        internal const int RpcStateWritingRequest = 1;
        internal const int RpcStateRequest = 2;
        internal const int RpcStateProcessing = 3;
        internal const int RpcStateResponse = 4;
        internal const int RpcFlagCancelRequested = 1;
        internal const int RpcFlagAcked = 2;
        internal const int RpcFlagResponseCompressed = 4;
        internal const int RpcErrorNone = 0;
        internal const int RpcErrorDeadlineExceeded = 1;
        internal const int RpcErrorCancelled = 2;
        internal const int RpcErrorInvalidMessage = 3;
        internal const int RpcErrorCapacityExhausted = 4;
        internal const int RpcErrorServerFailure = 5;

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
