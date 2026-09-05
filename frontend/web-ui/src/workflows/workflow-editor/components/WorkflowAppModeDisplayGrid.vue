<template>
  <section class="app-mode-displays">
    <article
      v-for="slot in config.displays"
      :key="identity(slot)"
      class="app-mode-displays__slot"
      :class="`app-mode-displays__slot--${slot.size}`"
    >
      <header>
        <strong>{{ slot.title || display(slot)?.title || slot.output_port }}</strong>
        <small>{{ slot.node_id }}</small>
      </header>
      <WorkflowNodePreviewDisplay
        v-if="display(slot)"
        :display="display(slot)!"
        :fallback-title="slot.title || slot.output_port"
        :tooltip="display(slot)!.title"
        @open-display="emit('openDisplay', $event)"
        @open-image="emit('openImage', $event)"
      />
      <div v-else class="app-mode-displays__empty">
        {{ hasRun ? t('workflowEditor.appMode.noCurrentOutput') : t('workflowEditor.appMode.waitingOutput') }}
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { WorkflowAppModeConfig, WorkflowAppModeDisplay } from '../app-mode/workflow-app-mode'
import type { PreviewNodeDisplay, PreviewViewerImage } from '../preview/useWorkflowPreviewDisplays'
import WorkflowNodePreviewDisplay from './WorkflowNodePreviewDisplay.vue'

const props = defineProps<{
  config: WorkflowAppModeConfig
  displays: Record<string, PreviewNodeDisplay>
  hasRun: boolean
}>()
const emit = defineEmits<{
  openDisplay: [display: PreviewNodeDisplay]
  openImage: [image: PreviewViewerImage]
}>()
const { t } = useI18n()

function identity(slot: WorkflowAppModeDisplay): string {
  return JSON.stringify([slot.node_id, slot.output_port])
}

function display(slot: WorkflowAppModeDisplay): PreviewNodeDisplay | null {
  return props.displays[identity(slot)] ?? null
}
</script>

<style scoped>
.app-mode-displays { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 14px; align-content: start; min-width: 0; }
.app-mode-displays__slot { grid-column: span 6; display: grid; grid-template-rows: auto minmax(220px, 1fr); min-width: 0; overflow: hidden; border: 1px solid var(--border-color, #d6dfd9); border-radius: 12px; background: var(--surface-primary, #fff); }
.app-mode-displays__slot--small { grid-column: span 4; }
.app-mode-displays__slot--large { grid-column: 1 / -1; }
.app-mode-displays__slot > header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 12px 14px; border-bottom: 1px solid var(--border-color, #d6dfd9); }
.app-mode-displays__slot > header small { color: var(--text-secondary, #69776e); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-mode-displays__empty { display: grid; place-items: center; min-height: 220px; color: var(--text-secondary, #69776e); background: var(--surface-secondary, #f4f7f5); }
.app-mode-displays :deep(.workflow-graph-node-preview) { min-height: 220px; height: 100%; border: 0; border-radius: 0; }
.app-mode-displays :deep(.workflow-graph-node-preview__image-frame), .app-mode-displays :deep(.workflow-graph-node-preview__image-frame img) { width: 100%; height: 100%; object-fit: contain; }
@media (max-width: 1000px) { .app-mode-displays__slot, .app-mode-displays__slot--small { grid-column: 1 / -1; } }
</style>
