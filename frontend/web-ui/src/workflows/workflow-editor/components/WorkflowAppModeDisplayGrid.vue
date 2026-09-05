<template>
  <section class="app-mode-displays">
    <article
      v-for="slot in config.displays"
      :key="identity(slot)"
      class="app-mode-displays__slot"
      :class="[
        `app-mode-displays__slot--${slot.size}`,
        `app-mode-displays__slot--${display(slot)?.kind || 'empty'}`,
      ]"
    >
      <header>
        <strong>{{ title(slot) }}</strong>
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
  nodeTitles: Record<string, string>
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

function title(slot: WorkflowAppModeDisplay): string {
  return slot.title || props.nodeTitles[slot.node_id] || display(slot)?.title || slot.output_port
}
</script>

<style scoped>
.app-mode-displays { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: var(--am-space-lg); align-content: start; min-width: 0; }
.app-mode-displays__slot { grid-column: span 6; display: grid; grid-template-rows: auto minmax(220px, 1fr); min-width: 0; overflow: hidden; border: 1px solid var(--am-border); border-radius: var(--am-radius-md); background: var(--am-surface); color: var(--am-text); }
.app-mode-displays__slot--small { grid-column: span 4; }
.app-mode-displays__slot--large { grid-column: 1 / -1; }
.app-mode-displays__slot > header { display: flex; align-items: center; min-height: 44px; padding: var(--am-space-md) var(--am-space-lg); border-bottom: 1px solid var(--am-border); color: var(--am-text-strong); }
.app-mode-displays__empty { display: grid; place-items: center; min-height: 220px; padding: var(--am-space-lg); color: var(--am-text-muted); background: var(--am-surface-soft); text-align: center; }
.app-mode-displays :deep(.workflow-graph-node-preview) { min-height: 220px; border: 0; border-radius: 0; }
.app-mode-displays :deep(.workflow-graph-node-preview__empty) { border-color: var(--am-border); }
.app-mode-displays__slot--image :deep(.workflow-graph-node-preview__image-frame), .app-mode-displays__slot--image :deep(.workflow-graph-node-preview__image-frame img) { width: 100%; height: auto; object-fit: contain; }
.app-mode-displays__slot--value :deep(.workflow-graph-node-preview) { position: relative; overflow: hidden; }
.app-mode-displays__slot--value :deep(.workflow-graph-node-preview__json) { position: absolute; inset: 6px; min-height: 0; max-height: none; overflow-y: auto; }
@media (max-width: 1000px) { .app-mode-displays__slot, .app-mode-displays__slot--small { grid-column: 1 / -1; } }
</style>
