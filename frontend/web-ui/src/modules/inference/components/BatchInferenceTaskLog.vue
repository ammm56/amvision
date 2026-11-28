<template>
  <section class="batch-log" aria-label="任务日志">
    <div class="batch-log__toolbar">
      <Select v-model="level" :options="levels" aria-label="日志级别" />
      <div class="input-with-icon batch-log__search">
        <Search :size="16" aria-hidden="true" />
        <input v-model.trim="search" type="search" aria-label="搜索日志" placeholder="搜索日志" />
      </div>
      <label class="batch-log__follow">
        <input v-model="follow" type="checkbox" />
        自动滚动
      </label>
      <div class="batch-log__actions">
        <Button size="sm" :disabled="!visibleEntries.length" @click="copyPage">
          <Copy :size="15" aria-hidden="true" />复制当前页
        </Button>
        <Button size="sm" :disabled="!entries.length" @click="downloadLog">
          <Download :size="15" aria-hidden="true" />下载日志
        </Button>
      </div>
    </div>

    <div v-if="error" class="batch-log__error">
      <InlineError message="任务日志读取失败" />
      <Button size="sm" :loading="loading" @click="emit('refresh')">重试</Button>
    </div>
    <div class="batch-log__meta">
      <span>{{ rangeLabel }}</span>
      <span v-if="feedback" role="status">{{ feedback }}</span>
    </div>
    <div
      v-if="visibleEntries.length"
      ref="logViewport"
      class="resource-table batch-log__table"
      tabindex="0"
      aria-label="日志列表"
      @scroll="onScroll"
    >
      <table>
        <thead>
          <tr><th scope="col">时间</th><th scope="col">级别</th><th scope="col">阶段</th><th scope="col">消息</th></tr>
        </thead>
        <tbody>
          <tr v-for="entry in visibleEntries" :key="entry.id">
            <td><time :datetime="entry.time">{{ formatLogTime(entry.time) }}</time></td>
            <td>
              <span class="batch-log__level" :class="`is-${entry.level}`">
                <component :is="levelIcons[entry.level]" :size="15" aria-hidden="true" />
                {{ levelLabels[entry.level] }}
              </span>
            </td>
            <td>{{ entry.stage }}</td>
            <td>{{ entry.message }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else-if="!error" class="batch-log__empty" role="status">
      {{ entries.length ? '没有符合条件的日志' : '暂无任务日志' }}
    </p>
    <div class="batch-log__footer">
      <Button size="sm" :disabled="!pageStart" @click="showEarlier">
        <ArrowUp :size="15" aria-hidden="true" />较早日志
      </Button>
      <Button size="sm" :disabled="!filteredEntries.length" @click="returnToLatest">
        <ArrowDown :size="15" aria-hidden="true" />返回最新
      </Button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, CircleAlert, Copy, Download, Info, Search, TriangleAlert } from '@lucide/vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import Select from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import type { BatchInferenceTask, BatchInferenceTaskItem } from '../services/inference.service'

type LogLevel = 'info' | 'warning' | 'error'
interface LogEntry {
  id: string
  time: string
  level: LogLevel
  stage: string
  message: string
}

const props = defineProps<{
  task: BatchInferenceTask
  items: readonly BatchInferenceTaskItem[]
  loading: boolean
  error: boolean
}>()
const emit = defineEmits<{ refresh: [] }>()

const pageSize = 50
const levelLabels = { info: '信息', warning: '警告', error: '错误' }
const levelIcons = { info: Info, warning: TriangleAlert, error: CircleAlert }
const levels = [
  { value: 'all', label: '全部级别' },
  ...Object.entries(levelLabels).map(([value, label]) => ({ value, label })),
]
const taskOutcomes: Record<string, { level: LogLevel; label: string }> = {
  succeeded: { level: 'info', label: '批量推理完成' },
  partial_failed: { level: 'warning', label: '批量推理完成，部分图片失败' },
  failed: { level: 'error', label: '批量推理失败' },
  cancelled: { level: 'warning', label: '批量推理已取消' },
}

const level = ref('all')
const search = ref('')
const follow = ref(true)
const frozenPageEnd = ref<number | null>(null)
const logViewport = ref<HTMLElement | null>(null)
const feedback = ref('')

// 已有任务可直接读取这些保存的时间和状态。原始异常不进入可复制和下载的内容。
const entries = computed(() => {
  const { task, items } = props
  const rows: LogEntry[] = []
  function add(id: string, time: string | null | undefined, level: LogLevel, stage: string, message: string) {
    if (time && Number.isFinite(Date.parse(time))) rows.push({ id, time, level, stage, message })
  }
  add('created', task.created_at, 'info', '任务', `创建任务 · ${task.total_items} 张图片`)
  add('started', task.started_at, 'info', '执行', '开始处理')
  for (const item of items) {
    const name = item.input_label.split(/[\\/]/).at(-1)?.replace(/[\r\n\t]+/g, ' ').trim() || `第 ${item.sequence_no} 张图片`
    if (item.state === 'succeeded') {
      add(item.item_id, item.finished_at, 'info', '图片', `${name}：推理完成`)
    } else if (item.state === 'failed') {
      const decodeFailed = item.error_code === 'DECODE_ERROR'
      add(item.item_id, item.finished_at, 'error', decodeFailed ? '图像解码' : '图片', `${name}：${decodeFailed ? '图像解码失败' : '推理失败'}`)
    }
  }
  const outcome = taskOutcomes[task.state]
  if (outcome) {
    add('finished', task.finished_at, outcome.level, '任务',
      `${outcome.label} · 成功 ${task.succeeded_items}，失败 ${task.failed_items}，未执行 ${task.skipped_items}`)
  }
  return rows.sort((left, right) => Date.parse(left.time) - Date.parse(right.time))
})

const filteredEntries = computed(() => {
  const keyword = search.value.toLowerCase()
  return entries.value.filter((entry) =>
    (level.value === 'all' || entry.level === level.value)
    && (!keyword || [formatLogTime(entry.time), levelLabels[entry.level], entry.stage, entry.message]
      .some((value) => value.toLowerCase().includes(keyword))),
  )
})
const pageEnd = computed(() => Math.min(frozenPageEnd.value ?? filteredEntries.value.length, filteredEntries.value.length))
const pageStart = computed(() => Math.max(0, pageEnd.value - pageSize))
const visibleEntries = computed(() => filteredEntries.value.slice(pageStart.value, pageEnd.value))
const rangeLabel = computed(() => {
  const total = filteredEntries.value.length
  if (!total) return '共 0 条'
  return pageEnd.value === total
    ? `最近 ${visibleEntries.value.length} 条 · 共 ${total} 条`
    : `第 ${pageStart.value + 1}–${pageEnd.value} 条 · 共 ${total} 条`
})

watch([level, search], () => {
  frozenPageEnd.value = follow.value ? null : filteredEntries.value.length
  feedback.value = ''
})
watch(follow, (enabled) => { frozenPageEnd.value = enabled ? null : pageEnd.value }, { flush: 'sync' })
watch([visibleEntries, follow], () => { if (follow.value) void scrollToEnd() }, { immediate: true })

function formatLogTime(value: string): string {
  const milliseconds = String(new Date(value).getMilliseconds()).padStart(3, '0')
  return `${formatSystemDateTime(value)}.${milliseconds}`
}

async function scrollToEnd() {
  await nextTick()
  const viewport = logViewport.value
  if (viewport) viewport.scrollTop = viewport.scrollHeight
}

function onScroll() {
  const viewport = logViewport.value
  if (follow.value && viewport && viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop > 2) {
    follow.value = false
  }
}

function showEarlier() {
  const earlierEnd = pageStart.value
  follow.value = false
  frozenPageEnd.value = earlierEnd
  void scrollToEnd()
}

function returnToLatest() {
  follow.value = true
  frozenPageEnd.value = null
  void scrollToEnd()
}

function logText(rows: readonly LogEntry[]): string {
  return ['时间\t级别\t阶段\t消息', ...rows.map((entry) =>
    [formatLogTime(entry.time), levelLabels[entry.level], entry.stage, entry.message].join('\t')),
  ].join('\n')
}

async function copyPage() {
  try {
    await navigator.clipboard.writeText(logText(visibleEntries.value))
    feedback.value = '已复制当前页'
  } catch {
    feedback.value = '复制失败，可选中文本复制'
  }
}

function downloadLog() {
  const url = URL.createObjectURL(new Blob([logText(entries.value)], { type: 'text/plain;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.task.batch_task_id}-log.txt`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}
</script>

<style scoped>
.batch-log { display:grid; gap:10px; min-width:0; }
.batch-log__toolbar, .batch-log__actions, .batch-log__footer, .batch-log__error { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.batch-log__toolbar > .ui-select { width:124px; }
.batch-log__search { flex:1 1 160px; min-width:0; max-width:280px; }
.batch-log__search input { min-width:0; }
.batch-log__follow { display:inline-flex; align-items:center; gap:6px; white-space:nowrap; }
.batch-log__follow input { accent-color:var(--am-brand-primary); }
.batch-log__actions { margin-inline-start:auto; }
.batch-log__meta { display:flex; flex-wrap:wrap; justify-content:space-between; gap:6px 12px; color:var(--am-text-muted); font-size:var(--am-type-caption); }
.batch-log__table { max-block-size:clamp(11rem, calc(100dvh - 36rem), 26rem); overflow:auto; }
.batch-log__table table { min-width:0; table-layout:fixed; }
.batch-log__table th { position:sticky; top:0; z-index:1; background:var(--am-surface-muted); }
.batch-log__table :is(th,td) { padding:8px 10px; overflow-wrap:anywhere; }
.batch-log__table th:first-child { width:27%; }
.batch-log__table th:nth-child(2), .batch-log__table th:nth-child(3) { width:14%; }
.batch-log__table tbody tr:last-child td { border-block-end:0; }
.batch-log__table time { font-variant-numeric:tabular-nums; }
.batch-log__level { display:inline-flex; align-items:center; gap:5px; color:var(--am-text-muted); }
.batch-log__level svg { flex:none; }
.batch-log__level.is-warning { color:var(--am-warning-text); }
.batch-log__level.is-error { color:var(--am-danger-text); }
.batch-log__empty { margin:0; padding:24px 10px; border:1px solid var(--am-border); border-radius:var(--am-radius-md); color:var(--am-text-muted); text-align:center; }
.batch-log__footer { justify-content:space-between; }
</style>
