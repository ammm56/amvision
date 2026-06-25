<template>
  <svg class="workflow-graph-links" aria-hidden="true">
    <path
      v-for="link in links"
      :key="`${link.edgeId}-hit-area`"
      class="workflow-graph-link-hit-area"
      :d="linkPath(link)"
      @click.stop="emit('selectLink', link)"
      @contextmenu.prevent.stop="emit('openLinkContextMenu', $event, link)"
    />
    <path
      v-for="link in links"
      :key="link.edgeId"
      class="workflow-graph-link"
      :class="{ 'is-selected': isLinkSelected(link), 'workflow-graph-link--boundary': link.linkKind !== 'edge' }"
      :d="linkPath(link)"
      @click.stop="emit('selectLink', link)"
      @contextmenu.prevent.stop="emit('openLinkContextMenu', $event, link)"
    />
    <circle
      v-for="marker in midpoints"
      :key="`${marker.edgeId}-midpoint`"
      class="workflow-graph-link-midpoint"
      :class="{ 'is-selected': isLinkSelected(marker.link) }"
      :cx="marker.x"
      :cy="marker.y"
      r="4.5"
      @click.stop="emit('selectLink', marker.link)"
      @contextmenu.prevent.stop="emit('openLinkContextMenu', $event, marker.link)"
    />
    <circle
      v-for="handle in reconnectHandles"
      :key="handle.key"
      class="workflow-graph-link-handle workflow-graph-link-handle--center"
      :cx="handle.x"
      :cy="handle.y"
      r="6"
      @mousedown.stop.prevent="emit('startEdgeTargetReconnect', $event, handle.edgeId)"
    >
      <title>拖到新的输入端口重新连接</title>
    </circle>
    <path v-if="showDraft" class="workflow-graph-link workflow-graph-link--draft" :d="draftPath" />
  </svg>
</template>

<script setup lang="ts">
import type { WorkflowEdgeHandleView } from '../canvas/useWorkflowEdgeHandles'
import type { WorkflowGraphLinkView } from '../geometry/useWorkflowGraphGeometry'

defineProps<{
  links: WorkflowGraphLinkView[]
  midpoints: WorkflowEdgeHandleView[]
  reconnectHandles: WorkflowEdgeHandleView[]
  showDraft: boolean
  draftPath: string
  linkPath: (link: WorkflowGraphLinkView) => string
  isLinkSelected: (link: WorkflowGraphLinkView) => boolean
}>()

const emit = defineEmits<{
  selectLink: [link: WorkflowGraphLinkView]
  openLinkContextMenu: [event: MouseEvent, link: WorkflowGraphLinkView]
  startEdgeTargetReconnect: [event: MouseEvent, edgeId: string]
}>()
</script>
