<template>
  <div
    class="workflow-graph-viewport-controls"
    role="toolbar"
    :aria-label="t('workflowEditor.editor.viewportControls')"
    @mousedown.stop
    @wheel.stop
    @contextmenu.stop
  >
    <button type="button" :title="t('workflowEditor.editor.zoomOut')" :aria-label="t('workflowEditor.editor.zoomOut')" @click="emit('zoomOut')">
      <ZoomOut :size="16" />
    </button>
    <button
      type="button"
      class="workflow-graph-viewport-controls__scale"
      :title="t('workflowEditor.editor.resetView')"
      :aria-label="`${t('workflowEditor.editor.resetView')} · ${scalePercent}%`"
      @click="emit('resetView')"
    >
      {{ scalePercent }}%
    </button>
    <button type="button" :title="t('workflowEditor.editor.zoomIn')" :aria-label="t('workflowEditor.editor.zoomIn')" @click="emit('zoomIn')">
      <ZoomIn :size="16" />
    </button>
    <span aria-hidden="true" />
    <button type="button" :title="t('workflowEditor.editor.fitView')" :aria-label="t('workflowEditor.editor.fitView')" @click="emit('fitView')">
      <Scan :size="16" />
    </button>
    <button
      type="button"
      class="workflow-graph-viewport-controls__minimap"
      :class="{ 'is-active': minimapVisible }"
      :title="minimapVisible ? t('workflowEditor.editor.hideMinimap') : t('workflowEditor.editor.showMinimap')"
      :aria-label="minimapVisible ? t('workflowEditor.editor.hideMinimap') : t('workflowEditor.editor.showMinimap')"
      :aria-pressed="minimapVisible"
      @click="emit('toggleMinimap')"
    >
      <MapIcon :size="16" />
    </button>
  </div>
</template>

<script setup lang="ts">
import { Map as MapIcon, Scan, ZoomIn, ZoomOut } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

defineProps<{
  scalePercent: number
  minimapVisible: boolean
}>()

const emit = defineEmits<{
  zoomOut: []
  zoomIn: []
  fitView: []
  resetView: []
  toggleMinimap: []
}>()

const { t } = useI18n()
</script>

<style scoped>
.workflow-graph-viewport-controls {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 4px;
  border: 1px solid var(--graph-line);
  border-radius: var(--am-radius-md);
  background: color-mix(in srgb, var(--graph-panel) 94%, transparent);
  box-shadow: 0 12px 28px rgb(0 0 0 / 0.2);
}

.workflow-graph-viewport-controls button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 32px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: var(--am-radius-sm);
  color: var(--graph-muted);
  background: transparent;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition:
    color var(--am-motion-fast) var(--am-ease-standard),
    border-color var(--am-motion-fast) var(--am-ease-standard),
    background-color var(--am-motion-fast) var(--am-ease-standard);
}

.workflow-graph-viewport-controls button:hover,
.workflow-graph-viewport-controls button.is-active {
  border-color: var(--graph-line);
  color: var(--graph-text-strong);
  background: var(--graph-panel-strong);
}

.workflow-graph-viewport-controls button:focus-visible {
  outline: 2px solid var(--graph-accent);
  outline-offset: 2px;
}

.workflow-graph-viewport-controls__scale {
  min-width: 54px !important;
  font-variant-numeric: tabular-nums;
}

.workflow-graph-viewport-controls > span {
  width: 1px;
  height: 22px;
  margin: 0 2px;
  background: var(--graph-line);
}

@media (max-width: 720px) {
  .workflow-graph-viewport-controls__minimap {
    display: none !important;
  }
}
</style>
