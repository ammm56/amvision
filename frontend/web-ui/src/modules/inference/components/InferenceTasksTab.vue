<template>
  <section class="inf-tasks-panel">
    <div class="inf-tasks-toolbar">
      <div class="inf-tasks-search">
        <Search :size="15" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索任务名称"
          aria-label="搜索任务名称"
          @input="offset = 0"
        />
        <button v-if="searchQuery" type="button" aria-label="清空搜索" @click="searchQuery = ''; offset = 0">
          <X :size="13" />
        </button>
      </div>

      <div class="inf-tasks-toolbar__filters">
        <SelectField
          fit-options
          :model-value="typeFilter"
          :options="typeFilterOptions"
          aria-label="任务来源类型"
          floating
          @update:model-value="selectTypeFilter"
        />

        <SelectField
          fit-options
          :model-value="statusFilter"
          :options="statusFilterOptions"
          aria-label="任务状态"
          floating
          @update:model-value="selectStatusFilter"
        />

        <Button variant="secondary" :loading="loading" @click="loadAll">
          <RefreshCw v-if="!loading" :size="14" />
          刷新
        </Button>
      </div>
    </div>

    <InlineError :message="errorMessage" />

    <div class="inf-tasks-table-wrap">
      <table class="inf-tasks-table">
        <thead>
          <tr>
            <th>任务名称</th>
            <th>类型</th>
            <th>部署</th>
            <th>进度</th>
            <th>结果</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody v-if="pagedRows.length > 0">
          <tr v-for="row in pagedRows" :key="`${row.kind}-${row.id}`">
            <td class="col-name">
              <strong :title="row.title">{{ row.title }}</strong>
            </td>
            <td class="col-kind">{{ row.kindLabel }}</td>
            <td class="col-deploy">
              <span :title="row.deploymentName">{{ row.deploymentName }}</span>
            </td>
            <td class="col-progress">
              <div class="inf-progress-cell">
                <span>{{ row.completedItems }} / {{ row.totalItems }}</span>
                <div class="inf-progress-track">
                  <div class="inf-progress-fill" :style="{ width: `${row.progressPercent}%` }" />
                </div>
              </div>
            </td>
            <td class="col-result">
              <div class="inf-result-cell">
                <span class="inf-dot-status">
                  <span class="inf-dot" :class="`is-${statusTone(row.status)}`" />
                  <span>{{ formatStatusLabel(row.status) }}</span>
                </span>
                <small v-if="row.subSummary">{{ row.subSummary }}</small>
              </div>
            </td>
            <td class="col-time">{{ formatSystemDateTime(row.createdAt) }}</td>
            <td class="col-actions">
              <div class="inf-row-actions">
                <button type="button" class="inf-link-action is-primary" @click="inspectRow(row)">
                  查看
                </button>
                <button
                  v-if="row.canCancel"
                  type="button"
                  class="inf-link-action is-warn"
                  @click="pendingCancelRow = row"
                >
                  取消
                </button>
                <button
                  v-if="row.canDelete"
                  type="button"
                  class="inf-link-action is-danger"
                  @click="pendingDeleteRow = row"
                >
                  删除
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="!loading && filteredRows.length === 0" class="inf-tasks-empty">
        <FileText :size="36" class="inf-tasks-empty__icon" />
        <p>{{ allRows.length === 0 ? '暂无推理任务' : '无匹配的推理任务' }}</p>
        <Button v-if="allRows.length === 0" size="sm" variant="secondary" @click="emit('back-workbench')">
          返回工作台
        </Button>
        <Button v-else size="sm" variant="secondary" @click="resetFilters">
          清空筛选
        </Button>
      </div>

      <div v-if="filteredRows.length > 0" class="inf-tasks-pagination">
        <PaginationControls
          numbered
          :offset="offset"
          :limit="pageSize"
          :item-count="pagedRows.length"
          :total-count="filteredRows.length"
          :disabled="loading"
          @previous="offset = Math.max(0, offset - pageSize)"
          @next="offset = offset + pageSize"
          @go="offset = $event"
        >
          <template #summary>共 {{ filteredRows.length }} 项</template>
        </PaginationControls>

        <div class="inf-tasks-pagesize">
          <SelectField
            fit-options
            floating
            :model-value="String(pageSize)"
            :options="pageSizeOptions"
            aria-label="每页条数"
            @update:model-value="changePageSize"
          />
        </div>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="pendingCancelRow"
        class="inf-modal-backdrop"
        role="dialog"
        aria-modal="true"
        aria-label="取消推理任务"
        @click.self="pendingCancelRow = null"
      >
        <div class="inf-confirm-modal">
          <header class="inf-confirm-modal__head">
            <div class="inf-confirm-modal__title">
              <AlertCircle :size="18" class="is-warn" />
              <h3>取消推理任务?</h3>
            </div>
            <button type="button" class="inf-modal-x" aria-label="关闭" @click="pendingCancelRow = null">
              <X :size="16" />
            </button>
          </header>
          <div class="inf-confirm-modal__body">
            <p class="inf-confirm-modal__target">任务：{{ pendingCancelRow.title }}</p>
            <div class="inf-confirm-stats">
              <div>
                <small>已完成</small>
                <strong>{{ pendingCancelRow.completedItems }} / {{ pendingCancelRow.totalItems }}</strong>
              </div>
              <div>
                <small>未执行</small>
                <strong>{{ Math.max(0, pendingCancelRow.totalItems - pendingCancelRow.completedItems) }}</strong>
              </div>
            </div>
            <p class="inf-confirm-modal__hint">取消后将保留已完成的结果，正在执行的样本可能完成。</p>
          </div>
          <footer class="inf-confirm-modal__foot">
            <Button variant="secondary" @click="pendingCancelRow = null">继续执行</Button>
            <Button
              variant="primary"
              class="inf-btn-warn"
              :loading="actionBusy"
              @click="confirmCancelTask"
            >
              确认取消
            </Button>
          </footer>
        </div>
      </div>

      <div
        v-if="pendingDeleteRow"
        class="inf-modal-backdrop"
        role="dialog"
        aria-modal="true"
        aria-label="删除任务记录"
        @click.self="pendingDeleteRow = null"
      >
        <div class="inf-confirm-modal">
          <header class="inf-confirm-modal__head">
            <div class="inf-confirm-modal__title">
              <AlertTriangle :size="18" class="is-danger" />
              <h3>{{ pendingDeleteRow.kind === 'batch' ? '删除批量任务?' : '删除推理记录?' }}</h3>
            </div>
            <button type="button" class="inf-modal-x" aria-label="关闭" @click="pendingDeleteRow = null">
              <X :size="16" />
            </button>
          </header>
          <div class="inf-confirm-modal__body">
            <p class="inf-confirm-modal__target">确认删除 “{{ pendingDeleteRow.title }}” 及其关联产物文件？</p>
            <p class="inf-confirm-modal__hint">若结果文件清理失败，记录将被保留以便重试删除。</p>
          </div>
          <footer class="inf-confirm-modal__foot">
            <Button variant="secondary" @click="pendingDeleteRow = null">取消</Button>
            <Button variant="danger" :loading="actionBusy" @click="confirmDeleteTask">
              确认删除
            </Button>
          </footer>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AlertCircle, AlertTriangle, FileText, RefreshCw, Search, X } from '@lucide/vue'

import type { ModelTaskType, TaskDeploymentInstance } from '@/modules/deployments/services/deployment.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { getErrorMessage } from '@/shared/api/error'
import Button from '@/shared/ui/components/Button.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import {
  cancelBatchInferenceTask,
  deleteBatchInferenceTask,
  deleteDirectInferenceRecord,
  listBatchInferenceTasks,
  listDirectInferenceRecords,
  listTaskInferenceTasks,
  SUPPORTED_INFERENCE_TASK_TYPES,
  type BatchInferenceTask,
  type DirectInferenceRecordSummary,
  type TaskInferenceTaskSummary,
} from '../services/inference.service'

interface UnifiedTaskRow {
  kind: 'batch' | 'async' | 'direct'
  id: string
  title: string
  kindLabel: string
  deploymentName: string
  taskType: ModelTaskType
  totalItems: number
  completedItems: number
  progressPercent: number
  status: string
  subSummary: string
  createdAt: string
  canCancel: boolean
  canDelete: boolean
  rawAsync?: TaskInferenceTaskSummary
}

const props = withDefaults(
  defineProps<{
    projectId: string
    deployments: TaskDeploymentInstance[]
    canWriteTasks?: boolean
  }>(),
  {
    canWriteTasks: true,
  },
)

const emit = defineEmits<{
  'open-create': []
  'open-batch': [batchTaskId: string]
  'open-direct-record': [recordId: string]
  'open-async-task': [task: TaskInferenceTaskSummary & { task_type: ModelTaskType }]
  'back-workbench': []
}>()

const loading = ref(false)
const actionBusy = ref(false)
const errorMessage = ref<string | null>(null)
const searchQuery = ref('')
const typeFilter = ref<'all' | 'batch' | 'async' | 'direct'>('all')
const statusFilter = ref('')
const offset = ref(0)
const pageSize = ref(20)

const batchTasks = ref<BatchInferenceTask[]>([])
const asyncTasks = ref<Array<TaskInferenceTaskSummary & { task_type: ModelTaskType }>>([])
const directRecords = ref<DirectInferenceRecordSummary[]>([])

const pendingCancelRow = ref<UnifiedTaskRow | null>(null)
const pendingDeleteRow = ref<UnifiedTaskRow | null>(null)
let pollTimer: number | undefined

const typeFilterOptions = [
  { label: '全部类型', value: 'all' },
  { label: '批量', value: 'batch' },
  { label: '异步', value: 'async' },
  { label: '同步保存', value: 'direct' },
]

const statusFilterOptions = [
  { label: '全部状态', value: '' },
  { label: '排队中', value: 'queued' },
  { label: '执行中', value: 'running' },
  { label: '已完成', value: 'succeeded' },
  { label: '部分失败', value: 'partial_failed' },
  { label: '失败', value: 'failed' },
  { label: '已取消', value: 'cancelled' },
]

const pageSizeOptions = [10, 20, 50].map((n) => ({
  value: String(n),
  label: `${n} 条/页`,
}))

const deploymentNameMap = computed(() => {
  const map = new Map<string, string>()
  for (const dep of props.deployments) {
    map.set(dep.deployment_instance_id, dep.display_name || dep.deployment_instance_id)
  }
  return map
})

const allRows = computed<UnifiedTaskRow[]>(() => {
  const rows: UnifiedTaskRow[] = []

  for (const b of batchTasks.value) {
    const parts: string[] = []
    if (b.succeeded_items > 0) parts.push(`成功 ${b.succeeded_items}`)
    if (b.failed_items > 0) parts.push(`失败 ${b.failed_items}`)
    if (b.skipped_items > 0) parts.push(`未执行 ${b.skipped_items}`)
    rows.push({
      kind: 'batch',
      id: b.batch_task_id,
      title: b.display_name || b.batch_task_id,
      kindLabel: '批量',
      deploymentName:
        b.deployment_display_name ||
        deploymentNameMap.value.get(b.deployment_instance_id) ||
        b.deployment_instance_id,
      taskType: (b.task_type as ModelTaskType) || 'detection',
      totalItems: Math.max(1, b.total_items),
      completedItems: b.completed_items,
      progressPercent: Math.min(100, Math.round((b.completed_items / Math.max(1, b.total_items)) * 100)),
      status: b.state,
      subSummary: parts.join(' ') || `共 ${b.total_items} 项`,
      createdAt: b.created_at,
      canCancel: props.canWriteTasks && (b.state === 'queued' || b.state === 'running'),
      canDelete: props.canWriteTasks && !['queued', 'running'].includes(b.state),
    })
  }

  for (const a of asyncTasks.value) {
    const terminal = ['succeeded', 'failed', 'cancelled'].includes(a.state)
    const countText =
      typeof a.item_count === 'number'
        ? `目标 ${a.item_count}`
        : a.error_message
          ? a.error_message
          : ''
    rows.push({
      kind: 'async',
      id: a.task_id,
      title: a.display_name || a.task_id,
      kindLabel: '异步',
      deploymentName: deploymentNameMap.value.get(a.deployment_instance_id) || a.deployment_instance_id,
      taskType: a.task_type,
      totalItems: 1,
      completedItems: terminal ? 1 : 0,
      progressPercent: terminal ? 100 : a.state === 'running' ? 50 : 0,
      status: a.state,
      subSummary: countText,
      createdAt: a.created_at,
      canCancel: false,
      canDelete: false,
      rawAsync: a,
    })
  }

  for (const r of directRecords.value) {
    const latencyText =
      typeof r.latency_ms === 'number' ? `${r.latency_ms.toFixed(1)} ms` : ''
    rows.push({
      kind: 'direct',
      id: r.record_id,
      title: r.input_label || r.record_id,
      kindLabel: '同步保存',
      deploymentName:
        r.deployment_display_name ||
        deploymentNameMap.value.get(r.deployment_instance_id) ||
        r.deployment_instance_id,
      taskType: r.task_type,
      totalItems: 1,
      completedItems: 1,
      progressPercent: 100,
      status: 'succeeded',
      subSummary: [`目标 ${r.item_count}`, latencyText].filter(Boolean).join(' · '),
      createdAt: r.created_at,
      canCancel: false,
      canDelete: props.canWriteTasks,
    })
  }

  rows.sort((a, b) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : 0))
  return rows
})

const filteredRows = computed(() => {
  const kw = searchQuery.value.trim().toLowerCase()
  return allRows.value.filter((row) => {
    if (typeFilter.value !== 'all' && row.kind !== typeFilter.value) return false
    if (statusFilter.value && row.status !== statusFilter.value) return false
    if (!kw) return true
    return (
      row.title.toLowerCase().includes(kw) ||
      row.deploymentName.toLowerCase().includes(kw) ||
      row.id.toLowerCase().includes(kw)
    )
  })
})

const pagedRows = computed(() =>
  filteredRows.value.slice(offset.value, offset.value + pageSize.value),
)

const hasActiveTasks = computed(() =>
  allRows.value.some((r) => r.status === 'queued' || r.status === 'running'),
)

watch(
  () => props.projectId,
  () => {
    offset.value = 0
    void loadAll()
  },
)

watch(hasActiveTasks, (active) => {
  syncPolling(active)
})

onMounted(() => {
  void loadAll()
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})

function syncPolling(active: boolean): void {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
  if (active) {
    pollTimer = window.setInterval(() => {
      void loadAll(true)
    }, 3000)
  }
}

async function loadAll(silent = false): Promise<void> {
  if (!props.projectId) return
  if (!silent) loading.value = true
  errorMessage.value = null
  try {
    const [batches, direct, asyncGroups] = await Promise.all([
      listBatchInferenceTasks({ projectId: props.projectId, limit: 100 }),
      listDirectInferenceRecords({ projectId: props.projectId, limit: 100 }),
      Promise.all(
        SUPPORTED_INFERENCE_TASK_TYPES.map((taskType) =>
          listTaskInferenceTasks({ taskType, projectId: props.projectId, limit: 40 })
            .then((items) => items.map((item) => ({ ...item, task_type: taskType })))
            .catch(() => [] as Array<TaskInferenceTaskSummary & { task_type: ModelTaskType }>),
        ),
      ),
    ])
    batchTasks.value = batches
    directRecords.value = direct
    asyncTasks.value = asyncGroups.flat()
  } catch (err) {
    if (!silent) errorMessage.value = getErrorMessage(err)
  } finally {
    if (!silent) loading.value = false
  }
}

function selectTypeFilter(val: string | number | boolean | null): void {
  if (val === 'all' || val === 'batch' || val === 'async' || val === 'direct') {
    typeFilter.value = val
    offset.value = 0
  }
}

function selectStatusFilter(val: string | number | boolean | null): void {
  statusFilter.value = typeof val === 'string' ? val : ''
  offset.value = 0
}

function changePageSize(val: string | number | boolean | null): void {
  const num = Number(val)
  if (!Number.isFinite(num) || num <= 0) return
  pageSize.value = num
  offset.value = 0
}

function resetFilters(): void {
  searchQuery.value = ''
  typeFilter.value = 'all'
  statusFilter.value = ''
  offset.value = 0
}

function inspectRow(row: UnifiedTaskRow): void {
  if (row.kind === 'batch') {
    emit('open-batch', row.id)
  } else if (row.kind === 'direct') {
    emit('open-direct-record', row.id)
  } else if (row.rawAsync) {
    emit('open-async-task', { ...row.rawAsync, task_type: row.taskType })
  }
}

async function confirmCancelTask(): Promise<void> {
  if (!pendingCancelRow.value) return
  actionBusy.value = true
  errorMessage.value = null
  try {
    await cancelBatchInferenceTask(pendingCancelRow.value.id)
    pendingCancelRow.value = null
    await loadAll()
  } catch (err) {
    errorMessage.value = getErrorMessage(err)
  } finally {
    actionBusy.value = false
  }
}

async function confirmDeleteTask(): Promise<void> {
  if (!pendingDeleteRow.value) return
  actionBusy.value = true
  errorMessage.value = null
  const target = pendingDeleteRow.value
  try {
    if (target.kind === 'batch') {
      await deleteBatchInferenceTask(target.id)
      batchTasks.value = batchTasks.value.filter((item) => item.batch_task_id !== target.id)
    } else if (target.kind === 'direct') {
      await deleteDirectInferenceRecord(target.id)
      directRecords.value = directRecords.value.filter((item) => item.record_id !== target.id)
    }
    pendingDeleteRow.value = null
  } catch (err) {
    errorMessage.value = getErrorMessage(err)
  } finally {
    actionBusy.value = false
  }
}

function formatStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '执行中',
    succeeded: '已完成',
    partial_failed: '部分失败',
    failed: '失败',
    cancelled: '已取消',
  }
  return labels[status] || status
}

function statusTone(status: string): 'ok' | 'warn' | 'danger' | 'neutral' {
  if (status === 'succeeded' || status === 'running') return 'ok'
  if (status === 'partial_failed' || status === 'queued') return 'warn'
  if (status === 'failed') return 'danger'
  return 'neutral'
}

defineExpose({ loadAll })
</script>

<style scoped>
.inf-tasks-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.inf-tasks-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px 16px;
}

.inf-tasks-search {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  width: clamp(200px, 20vw, 250px);
  max-width: 100%;
  margin-inline-end: auto;
  padding: 0 10px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface);
  color: var(--am-text-muted);
}

.inf-tasks-search input {
  flex: 1 1 auto;
  min-width: 0;
  border: none;
  background: transparent;
  color: var(--am-text-strong);
  font-size: 13px;
  outline: none;
}

.inf-tasks-search button {
  border: none;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
}

.inf-tasks-toolbar__filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.inf-tasks-toolbar__filters :deep(.ui-select__button) {
  min-height: 36px;
  height: 36px;
}

.inf-tasks-table-wrap {
  width: 100%;
  overflow-x: auto;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-raised);
}

.inf-tasks-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--am-surface-raised);
}

.inf-tasks-table th {
  padding: 12px 14px;
  text-align: left;
  font-size: 14px;
  font-weight: 600;
  color: var(--am-text);
  background: var(--am-surface);
  border-bottom: 1px solid var(--am-border);
  white-space: nowrap;
}

.inf-tasks-table td {
  padding: 12px 14px;
  font-size: 14px;
  color: var(--am-text);
  border-bottom: 1px solid var(--am-border);
  vertical-align: middle;
}

.inf-tasks-table tbody tr:last-child td {
  border-bottom: 0;
}

.inf-tasks-table tbody tr:hover {
  background: var(--am-row-hover);
}

.col-name strong {
  display: block;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--am-text-strong);
}

.col-kind {
  white-space: nowrap;
}

.col-deploy span {
  display: block;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inf-progress-cell {
  display: grid;
  gap: 6px;
  min-width: 110px;
  font-variant-numeric: tabular-nums;
}

.inf-progress-track {
  height: 6px;
  border-radius: 999px;
  background: var(--am-progress-track);
  overflow: hidden;
}

.inf-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--am-action-primary);
}

.inf-result-cell {
  display: grid;
  gap: 2px;
}

.inf-result-cell small {
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-dot-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
  white-space: nowrap;
}

.inf-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.inf-dot.is-ok {
  background: var(--am-action-primary);
}

.inf-dot.is-warn {
  background: #f59e0b;
}

.inf-dot.is-danger {
  background: #dc2626;
}

.inf-dot.is-neutral {
  background: #98a2b3;
}

.col-time {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  color: var(--am-text-muted);
}

.col-actions {
  white-space: nowrap;
}

.inf-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  white-space: nowrap;
}

.inf-link-action {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.inf-link-action.is-primary {
  color: var(--am-action-primary);
}

.inf-link-action.is-warn {
  color: #d97706;
}

.inf-link-action.is-danger {
  color: #dc2626;
}

.inf-tasks-empty {
  min-height: 240px;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 10px;
  padding: 36px 20px;
  color: var(--am-text-muted);
  text-align: center;
}

.inf-tasks-empty__icon {
  opacity: 0.45;
}

.inf-tasks-empty p {
  margin: 0;
  font-size: 14px;
}

.inf-tasks-pagination {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 0 14px;
  border-top: 1px solid var(--am-border);
}

.inf-tasks-pagination :deep(.pagination-controls) {
  flex: 1 1 auto;
  min-width: 0;
  border: none;
  padding-inline: 0;
  background: transparent;
}

.inf-tasks-pagesize {
  flex: none;
}

.inf-tasks-pagesize :deep(.ui-select) {
  min-width: 104px;
}

.inf-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 95;
  background: var(--am-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.inf-confirm-modal {
  width: min(440px, 92vw);
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  box-shadow: var(--am-shadow-modal);
  overflow: hidden;
}

.inf-confirm-modal__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--am-border);
}

.inf-confirm-modal__title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.inf-confirm-modal__title h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--am-text-strong);
}

.inf-confirm-modal__title .is-warn {
  color: #f59e0b;
}

.inf-confirm-modal__title .is-danger {
  color: #dc2626;
}

.inf-modal-x {
  border: none;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
  padding: 4px;
}

.inf-confirm-modal__body {
  padding: 16px 20px;
  display: grid;
  gap: 12px;
}

.inf-confirm-modal__target {
  margin: 0;
  font-size: 14px;
  color: var(--am-text-strong);
}

.inf-confirm-stats {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-soft);
}

.inf-confirm-stats small {
  display: block;
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-confirm-stats strong {
  font-size: 16px;
  color: var(--am-text-strong);
}

.inf-confirm-modal__hint {
  margin: 0;
  font-size: 12px;
  color: var(--am-text-muted);
}

.inf-confirm-modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 20px;
  border-top: 1px solid var(--am-border);
}

.inf-btn-warn {
  background: #f59e0b !important;
  border-color: #f59e0b !important;
  color: #ffffff !important;
}
</style>
