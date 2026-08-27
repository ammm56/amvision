// Workflow Trigger Mailbox v1 的跨语言稳定 fixture。
using System;

namespace Amvar.Vision.SharedMemory
{
    internal static class WorkflowTriggerMailboxV1Fixture
    {
        internal static void Verify()
        {
            Require(
                WorkflowTriggerMailboxV1.ContractId
                    == "amvision.workflow-trigger-mailbox.v1",
                "Workflow Trigger 业务契约 contract id mismatch.");
            Require(
                WorkflowTriggerMailboxV1.RelativeMmapPath
                    == "local-message/workflow-trigger/mailbox.mmap",
                "Workflow Trigger LocalMessage path mismatch.");
            Require(
                WorkflowTriggerMailboxV1.RelativeGuardPath
                    == "local-message/workflow-trigger/access.guard",
                "Workflow Trigger access guard path mismatch.");
            Require(
                WorkflowTriggerMailboxV1.DescriptorHeaderSize == 256
                    && WorkflowTriggerMailboxV1.ExtensionPhaseOffset == 104
                    && WorkflowTriggerMailboxV1.ExtensionHandoffStateOffset == 136,
                "Workflow Trigger descriptor extension offsets mismatch.");
            Require(
                WorkflowTriggerMailboxV1.InlineRequestCapacityBytes == 65536
                    && WorkflowTriggerMailboxV1.InlineResponseCapacityBytes == 65536
                    && WorkflowTriggerMailboxV1.OverflowPageCapacityBytes == 262144
                    && WorkflowTriggerMailboxV1.MaxOverflowPagesPerResponse == 129
                    && WorkflowTriggerMailboxV1.PublicResponseCapacityBytes == 33554432
                    && WorkflowTriggerMailboxV1.MaxResponseBytes == 33619968,
                "Workflow Trigger frozen Mailbox profile mismatch.");
        }

        private static void Require(bool condition, string message)
        {
            if (!condition)
            {
                throw new InvalidOperationException(message);
            }
        }
    }
}
