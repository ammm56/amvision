<template>
  <div class="value-display" :class="{ 'value-display--overlay': overlay, 'value-display--collapsed': collapsed }" aria-label="结果显示">
    <button v-if="overlay" type="button" class="value-display__toggle" :aria-expanded="!collapsed" @mousedown.stop @dblclick.stop @click.stop="collapsed = !collapsed">{{ collapsed ? '展开结果' : '收起' }}</button>
    <span v-if="(payload.context as WorkflowJsonObject | null)?.complete === false" class="value-display__pending" role="status">汇总中 · 当前为部分结果</span>
    <dl v-if="!collapsed" @mousedown.stop @wheel.stop>
      <div v-for="(field, index) in fields" :key="index" :class="tone(field)">
        <dt>{{ field.label }}</dt><dd>{{ formatDisplayField(field) }}</dd>
      </div>
    </dl>
  </div>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { displayFields, formatDisplayField, type DisplayField } from '../preview/value-display'
import type { WorkflowJsonObject } from '../types'
const props = defineProps<{ payload: WorkflowJsonObject; overlay?: boolean }>()
const collapsed = ref(false)
const fields = computed(() => displayFields(props.payload))
function tone(field: DisplayField): string {
  const color = field.format === 'status' ? field.states[String(field.value)] : ''
  return ['success', 'danger', 'warning'].includes(color ?? '') ? `value-display--${color}` : ''
}
</script>
<style scoped>
.value-display { color: var(--am-text); background: var(--am-surface); padding: 10px 12px; border: 1px solid var(--am-border); border-radius: var(--am-radius-md); font-size: 13px; max-width: 100%; box-sizing: border-box; }
.value-display dl { display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 0; }
.value-display dl > div { display: flex; gap: 6px; align-items: baseline; min-width: 0; overflow-wrap: anywhere; }
.value-display dt { color: var(--am-text-muted); }
.value-display dd { margin: 0; font-weight: 700; font-variant-numeric: tabular-nums; }
.value-display__pending { display: block; color: var(--am-warning-text); margin-bottom: 6px; }
.value-display--overlay { max-width: min(540px, 100%); pointer-events: none; box-shadow: var(--am-shadow-sm); }
.value-display--overlay dl { max-height: min(200px, 30vh); overflow-y: auto; pointer-events: auto; }
.value-display--collapsed { width: fit-content; }
.value-display__toggle { pointer-events: auto; display: block; margin: 0 0 4px auto; border: 0; background: transparent; color: var(--am-text-muted); cursor: pointer; font-size: 11px; }
.value-display--success dd { color: var(--am-success-text, #087847); }
.value-display--danger dd { color: var(--am-danger-text, #b42332); }
.value-display--warning dd { color: var(--am-warning-text, #956000); }
</style>
