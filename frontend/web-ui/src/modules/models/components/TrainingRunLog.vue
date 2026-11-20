<template>
  <SideDrawer :open="open" panel-class="training-log-drawer" :title="zh ? '运行日志' : 'Run log'" :close-label="zh ? '关闭' : 'Close'" @close="emit('close')">
    <div class="training-log">
      <h3>{{ taskName }}</h3>
      <div class="training-log__toolbar">
        <Select v-model="level" :options="levels" :aria-label="zh ? '日志级别' : 'Log level'" />
        <label class="training-log__search"><Search :size="16" aria-hidden="true" />
          <input v-model.trim="query" :aria-label="zh ? '搜索日志内容' : 'Search the run log'" :placeholder="zh ? '搜索日志内容' : 'Search the run log'" />
        </label>
        <label v-if="live" class="training-log__pause"><input v-model="paused" type="checkbox" />{{ zh ? '暂停自动滚动' : 'Pause auto-scroll' }}</label>
        <Button size="sm" :disabled="!entries.length" @click="download"><Download :size="16" />{{ zh ? '下载日志' : 'Download log' }}</Button>
      </div>
      <ol v-if="visible.length" ref="list" class="training-log__rows">
        <li v-for="entry in visible" :key="entry.id">
          <time :datetime="entry.time">{{ formatSystemDateTime(entry.time) }}</time>
          <StatusBadge :tone="entry.level === 'ERROR' ? 'danger' : entry.level === 'WARN' ? 'warning' : 'neutral'">{{ entry.level }}</StatusBadge>
          <div><p>{{ entry.message }}</p><small v-if="entry.metrics">{{ entry.metrics }}</small></div>
        </li>
      </ol>
      <p v-else role="status">{{ entries.length ? (zh ? '没有匹配的日志。' : 'No matching log entries.') : (zh ? '暂无运行记录。' : 'No run events recorded.') }}</p>
    </div>
    <template #footer>
      <div class="training-log__footer">
        <span v-if="entries.length">{{ zh ? '最后更新' : 'Last updated' }} · {{ formatSystemDateTime(entries.at(-1)?.time) }}</span>
        <div>
          <span>{{ zh ? `显示 ${visible.length} / ${filtered.length} 条` : `${visible.length} of ${filtered.length} entries` }}</span>
          <Button v-if="filtered.length > pageSize" size="sm" variant="ghost" @click="pageSize += 200">{{ zh ? '加载更早' : 'Load earlier entries' }}</Button>
        </div>
      </div>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Download, Search } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import Select from '@/shared/ui/components/Select.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { formatModelNumber } from '../model-number-format'
import type { ModelTrainingTaskEvent } from '../services/model.service'

const props = defineProps<{ open: boolean; taskId: string; taskName: string; events: ModelTrainingTaskEvent[]; zh: boolean; live: boolean }>()
const emit = defineEmits<{ close: [] }>()
const level = ref('')
const query = ref('')
const paused = ref(false)
const pageSize = ref(200)
const list = ref<HTMLOListElement>()
const levels = computed(() => [
  { label: props.zh ? '全部' : 'All', value: '' },
  ...['INFO', 'WARN', 'ERROR'].map(value => ({ label: value, value })),
])

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

const entries = computed(() => props.events.map(event => {
  const tag = String(event.payload.level ?? event.event_type).toUpperCase()
  const state = event.payload.state
  const level = tag === 'ERROR' || state === 'failed' ? 'ERROR' : tag === 'WARN' || tag === 'WARNING' ? 'WARN' : 'INFO'
  const progress = record(event.payload.progress)
  const train = record(progress.train_metrics)
  const validation = record(progress.validation_metrics)
  const values = {
    train_loss: train.loss ?? train.total_loss,
    val_loss: validation.loss ?? validation.total_loss,
    current: progress.current_metric_value,
  }
  const metrics = Object.entries(values).flatMap(([key, value]) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) return []
    const label = key === 'current' && typeof progress.current_metric_name === 'string' ? progress.current_metric_name : key
    return [`${label} ${formatModelNumber(value, key === 'current' ? 3 : 4)}`]
  }).join(' · ')
  return { id: event.event_id, time: event.created_at, level, message: event.message || event.event_type, metrics }
}).sort((a, b) => a.time.localeCompare(b.time)))
const filtered = computed(() => {
  const search = query.value.toLowerCase()
  return entries.value.filter(entry => (!level.value || level.value === entry.level)
    && (!search || `${entry.message} ${entry.metrics}`.toLowerCase().includes(search)))
})
const visible = computed(() => filtered.value.slice(-pageSize.value))

watch([level, query], () => { pageSize.value = 200 })
watch(() => props.open, open => {
  if (!open) return
  level.value = ''; query.value = ''; paused.value = false; pageSize.value = 200
})
watch([() => props.open, () => entries.value.at(-1)?.id, paused], () => {
  if (!props.open || !props.live || paused.value || level.value || query.value) return
  void nextTick(() => { if (list.value) list.value.scrollTop = list.value.scrollHeight })
}, { flush: 'post' })

function download(): void {
  const lines = entries.value.map(entry => `${entry.time}\t${entry.level}\t${entry.message}${entry.metrics ? ` · ${entry.metrics}` : ''}`)
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.taskId}-events.log`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<style scoped>
:global(.training-log-drawer.side-drawer) { width:min(580px,calc(100vw - 24px)); }
.training-log { display:grid; gap:14px; min-width:0; }
.training-log h3,.training-log p { margin:0; overflow-wrap:anywhere; }
.training-log__toolbar,.training-log__footer,.training-log__footer > div { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.training-log__toolbar .ui-select { width:95px; }
.training-log__search { display:flex; flex:1 1 145px; align-items:center; gap:6px; min-width:0; padding:0 8px; border:1px solid var(--am-border); border-radius:6px; background:var(--am-surface); }
.training-log__search input { min-width:0; width:100%; height:34px; border:0; background:transparent; color:var(--am-text); }
.training-log__pause { display:flex; gap:4px; align-items:center; }
.training-log__rows { max-height:calc(100dvh - 248px); overflow-y:auto; list-style:none; margin:0; padding:0; }
.training-log__rows li { display:grid; grid-template-columns:141px 52px minmax(0,1fr); align-items:start; gap:8px; padding:10px 2px; border-bottom:1px solid var(--am-border); }
.training-log__rows time,.training-log__rows small,.training-log__footer { color:var(--am-text-muted); font-variant-numeric:tabular-nums; }
.training-log__rows small { display:block; margin-top:3px; overflow-wrap:anywhere; }
.training-log__footer { width:100%; justify-content:space-between; font-size:12px; }
@media (max-width:460px) { .training-log__rows li { grid-template-columns:1fr auto; } .training-log__rows li > div { grid-column:1 / -1; } }
</style>
