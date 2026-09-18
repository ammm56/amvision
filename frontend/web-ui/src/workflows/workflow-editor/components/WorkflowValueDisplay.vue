<template>
  <div class="value-display" :style="appearanceStyles(payload.appearance)" :class="{ 'value-display--overlay': overlay, 'value-display--collapsed': collapsed }" :aria-label="t('workflowDisplay.results')">
    <button v-if="overlay" type="button" class="value-display__toggle" :aria-expanded="!collapsed" @mousedown.stop @dblclick.stop @click.stop="collapsed = !collapsed">{{ t(collapsed ? 'workflowDisplay.expand' : 'workflowDisplay.collapse') }}</button>
    <span v-if="(payload.context as WorkflowJsonObject | null)?.complete === false" class="value-display__pending" role="status">{{ t('workflowDisplay.partial') }}</span>
    <dl v-if="!collapsed" @mousedown.stop @wheel.stop>
      <div v-for="(field, index) in fields" :key="index" :class="{ 'value-display__status': field.format === 'status' }">
        <dt :style="{ color: field.labelColor }">{{ field.label }}</dt><dd :style="{ color: fieldValueColor(field) }">{{ formatDisplayField(field) }}</dd>
      </div>
    </dl>
  </div>
</template>
<script setup lang="ts">
import { useTranslation } from '@/platform/i18n'
const { t } = useTranslation()
import { computed, ref } from 'vue'
import { appearanceStyles, displayFields, fieldValueColor, formatDisplayField } from '../preview/value-display'
import type { WorkflowJsonObject } from '../types'
const props = defineProps<{ payload: WorkflowJsonObject; overlay?: boolean }>()
const collapsed = ref(false)
const fields = computed(() => displayFields(props.payload))
</script>
<style scoped>
.value-display { color: var(--am-text); background: var(--am-surface); padding: 10px 12px; border: 1px solid var(--am-border); border-radius: var(--am-radius-md); font-size: var(--display-font-size, 13px); max-width: 100%; box-sizing: border-box; }
.value-display dl { display: grid; grid-template-columns: minmax(0, 1fr); gap: 5px; margin: 0; }
.value-display dl > div { display: grid; grid-template-columns: minmax(0, 1fr) fit-content(60%); gap: 12px; align-items: baseline; min-width: 0; overflow-wrap: anywhere; }
.value-display dt { color: var(--am-text-muted); }
.value-display dd { min-width: 0; margin: 0; text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }
.value-display__status dd { font-size: var(--display-status-font-size, inherit); }
.value-display__pending { display: block; color: var(--am-warning-text); margin-bottom: 6px; }
.value-display--overlay { display: flex; flex-direction: column; width: var(--display-panel-width, max-content); height: var(--display-panel-height, auto); max-width: min(var(--display-panel-width, 280px), 100%); max-height: 100%; background: color-mix(in srgb, var(--display-background-color, var(--am-surface)) var(--display-background-opacity, 78%), transparent); pointer-events: none; box-shadow: var(--am-shadow-sm); }
.value-display--overlay dl { display: grid; grid-template-columns: minmax(0, 1fr); gap: 5px; min-height: 0; max-height: var(--display-panel-height, min(240px, 50vh)); overflow-y: auto; pointer-events: auto; }
.value-display--overlay dl > div { display: flex; justify-content: space-between; gap: 18px; }
.value-display--overlay .value-display__status { justify-content: flex-start; }
.value-display--overlay .value-display__status dt { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.value-display--overlay .value-display__status dd { font-size: var(--display-status-font-size, 20px); line-height: 1.2; text-transform: uppercase; }
.value-display--collapsed { width: fit-content; height: auto; }
.value-display__toggle { flex: none; pointer-events: auto; display: block; margin: 0 0 4px auto; border: 0; background: transparent; color: var(--am-text-muted); cursor: pointer; font-size: 11px; }
</style>
