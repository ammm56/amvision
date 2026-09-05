<template>
  <Transition name="workflow-minimap">
    <div v-if="visible" class="workflow-graph-minimap" @mousedown.stop="emit('start-navigation', $event)" @contextmenu.stop>
      <button
        type="button"
        class="workflow-graph-minimap__close"
        :title="t('workflowEditor.editor.hideMinimap')"
        :aria-label="t('workflowEditor.editor.hideMinimap')"
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
  </Transition>
</template>

<script setup lang="ts">
import { X } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

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

const { t } = useI18n()
</script>
