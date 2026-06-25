<template>
  <div v-if="visible" class="workflow-graph-minimap" @mousedown.stop="emit('start-navigation', $event)" @contextmenu.stop>
    <button
      type="button"
      class="workflow-graph-minimap__close"
      title="隐藏小地图"
      aria-label="隐藏小地图"
      @mousedown.stop
      @click.stop="emit('toggle')"
    >
      <X :size="14" />
    </button>
    <div class="workflow-graph-minimap__nodes">
      <span
        v-for="miniNode in nodes"
        :key="miniNode.nodeId"
        class="workflow-graph-minimap__node"
        :class="{ 'is-selected': isNodeSelected(miniNode.nodeId) }"
        :style="miniNode.style"
      />
      <span class="workflow-graph-minimap__viewport" :style="viewportStyle" />
    </div>
  </div>
  <button
    v-else
    type="button"
    class="workflow-graph-minimap-toggle"
    title="显示小地图"
    aria-label="显示小地图"
    @mousedown.stop
    @click.stop="emit('toggle')"
  >
    <MapIcon :size="16" />
  </button>
</template>

<script setup lang="ts">
import { Map as MapIcon, X } from '@lucide/vue'

interface WorkflowMinimapNode {
  nodeId: string
  style: Record<string, string>
}

defineProps<{
  visible: boolean
  nodes: WorkflowMinimapNode[]
  viewportStyle: Record<string, string>
  isNodeSelected: (nodeId: string) => boolean
}>()

const emit = defineEmits<{
  'start-navigation': [event: MouseEvent]
  toggle: []
}>()
</script>
