<template>
  <section class="runs-card">
    <!-- Filter bar -->
    <div class="runs-toolbar">
      <div class="runs-filters">
        <div class="runs-filter-item">
          <span class="runs-filter-label">实例</span>
          <SelectField
            class="runs-filter-instance"
            floating
            :model-value="filterRuntimeId"
            :options="runtimeFilterOptions"
            aria-label="按实例筛选"
            @update:model-value="onSelectFilter('runtime', $event)"
          />
        </div>

        <div class="runs-filter-item">
          <span class="runs-filter-label">版本</span>
          <SelectField
            fit-options
            floating
            :model-value="filterVersionId"
            :options="versionFilterOptions"
            aria-label="按版本筛选"
            @update:model-value="onSelectFilter('version', $event)"
          />
        </div>

        <div class="runs-filter-item">
          <span class="runs-filter-label">执行状态</span>
          <SelectField
            fit-options
            floating
            :model-value="filterState"
            :options="stateFilterOptions"
            aria-label="按执行状态筛选"
            @update:model-value="onSelectFilter('state', $event)"
          />
        </div>

        <div class="runs-filter-item">
          <span class="runs-filter-label">时间</span>
          <SelectField
            fit-options
            floating
            :model-value="filterTimeRange"
            :options="timeFilterOptions"
            aria-label="按时间筛选"
            @update:model-value="onSelectFilter('time', $event)"
          />
        </div>
      </div>

      <div class="runs-toolbar__right">
        <div class="runs-search">
          <Search :size="14" />
          <input
            v-model="searchQuery"
            type="search"
            maxlength="200"
            placeholder="搜索执行编号"
            aria-label="搜索执行编号"
          />
          <button
            v-if="searchQuery"
            type="button"
            aria-label="清空执行编号搜索"
            @click="searchQuery = ''"
          >
            <X :size="13" />
          </button>
        </div>

        <Button
          variant="secondary"
          size="sm"
          :disabled="loading"
          :loading="loading"
          aria-label="刷新执行记录"
          @click="refresh"
        >
          <RefreshCw v-if="!loading" :size="14" />
        </Button>
      </div>
    </div>

    <!-- Instance-scoped context bar: shown ONLY when a specific instance is selected -->
    <div v-if="selectedFilterRuntime" class="runs-context-bar" data-runs-instance-context>
      <div class="runs-context-bar__info">
        <span>当前筛选实例：</span>
        <strong>{{ selectedFilterRuntime.display_name || selectedFilterRuntime.workflow_runtime_id }}</strong>
        <span class="runs-ctx-sep">·</span>
        <span>记录方式：{{ formatRecordModeLabel(readRuntimeRecordMode(selectedFilterRuntime), true) }}</span>
      </div>
      <Button
        variant="secondary"
        size="sm"
        @click="emit('open-runtime-config', selectedFilterRuntime)"
      >
        实例配置
      </Button>
    </div>

    <!-- Load error -->
    <div v-if="errorMessage" class="runs-state-box">
      <InlineError :message="errorMessage" />
      <Button variant="secondary" size="sm" @click="refresh">重试</Button>
    </div>

    <!-- Loading -->
    <div v-else-if="loading" class="runs-state-box" role="status">
      <span class="runs-muted">正在加载执行记录</span>
    </div>

    <!-- None record mode empty hint -->
    <div
      v-else-if="selectedFilterRuntime && readRuntimeRecordMode(selectedFilterRuntime) === 'none' && rawRuns.length === 0 && !hasSecondaryFilters"
      class="runs-state-box"
    >
      <strong>当前实例未保存执行记录</strong>
      <Button
        variant="secondary"
        size="sm"
        @click="emit('open-runtime-config', selectedFilterRuntime)"
      >
        修改实例配置
      </Button>
    </div>

    <!-- Filtered empty -->
    <div v-else-if="rawRuns.length === 0 && hasAnyFilters" class="runs-state-box">
      <strong>没有符合条件的执行记录</strong>
      <Button variant="secondary" size="sm" @click="clearAllFilters">清空筛选</Button>
    </div>

    <!-- True empty -->
    <div v-else-if="rawRuns.length === 0" class="runs-state-box">
      <strong>暂无执行记录</strong>
    </div>

    <!-- Table -->
    <template v-else>
      <div class="runs-table-wrap">
        <table class="runs-table">
          <thead>
            <tr>
              <th>开始时间</th>
              <th>运行实例</th>
              <th>执行版本</th>
              <th>执行状态</th>
              <th>业务结果</th>
              <th>记录方式</th>
              <th class="col-actions">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="run in rawRuns"
              :key="run.workflow_run_id"
              :class="{ 'is-selected': selectedRunId === run.workflow_run_id }"
              @click="emit('inspect-run', run)"
            >
              <td class="runs-nowrap">{{ formatSystemDateTime(run.started_at || run.created_at) }}</td>
              <td><span class="runs-instance-name" :title="runtimeNameById(run.workflow_runtime_id)">{{ runtimeNameById(run.workflow_runtime_id) }}</span></td>
              <td class="runs-nowrap">{{ versionLabelById(run.workflow_app_version_id) }}</td>
              <td>
                <span class="runs-status-cell" :class="`is-${runStateDotTone(run.state)}`">
                  <span v-if="run.state === 'running'" class="runs-mini-spinner" aria-hidden="true" />
                  <i v-else class="runs-dot" />
                  {{ formatRunStateLabel(run.state) }}
                </span>
              </td>
              <td>
                <span
                  v-if="extractBusinessOutcome(run)"
                  class="runs-biz-text"
                  :class="{ 'is-ng': extractBusinessOutcome(run) === 'NG' }"
                >
                  {{ extractBusinessOutcome(run) }}
                </span>
                <span v-else class="runs-muted">—</span>
              </td>
              <td class="runs-muted">{{ formatRecordModeLabel(readRunRecordMode(run)) }}</td>
              <td class="col-actions" @click.stop>
                <button type="button" class="runs-link-btn" @click="emit('inspect-run', run)">
                  查看
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="runs-pagination">
        <div class="runs-page-meta">
          <SelectField
            fit-options
            floating
            :model-value="String(limit)"
            :options="pageSizeOptions"
            aria-label="每页显示条数"
            @update:model-value="onPageSizeChange"
          />
        </div>
        <PaginationControls
          numbered
          :offset="offset"
          :limit="limit"
          :item-count="rawRuns.length"
          :total-count="backendTotalCount"
          :has-more="backendHasMore"
          @previous="goToOffset(Math.max(0, offset - limit))"
          @next="goToOffset(offset + limit)"
          @go="goToOffset"
        />
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { RefreshCw, Search, X } from '@lucide/vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { getErrorMessage } from '@/shared/api/error'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { listWorkflowRuns } from '../services/workflow-runtime.service'
import type { WorkflowAppRuntime, WorkflowAppVersion, WorkflowRun } from '../types'
import {
  extractBusinessOutcome,
  formatRecordModeLabel,
  formatRunStateLabel,
  readRunRecordMode,
  readRuntimeRecordMode,
  runStateDotTone,
} from '../utils/workflow-run-display'

const props = defineProps<{
  projectId: string
  applicationId: string
  runtimes: WorkflowAppRuntime[]
  versions: WorkflowAppVersion[]
  selectedRunId?: string | null
}>()

const emit = defineEmits<{
  'inspect-run': [run: WorkflowRun]
  'open-runtime-config': [runtime: WorkflowAppRuntime]
}>()

const filterRuntimeId = ref('')
const filterVersionId = ref('')
const filterState = ref('')
const filterTimeRange = ref('')
const searchQuery = ref('')
const offset = ref(0)
const limit = ref(20)

const rawRuns = ref<WorkflowRun[]>([])
const backendTotalCount = ref<number | null>(null)
const backendHasMore = ref(false)
const loading = ref(false)
const errorMessage = ref<string | null>(null)
let requestRevision = 0
let searchTimer: ReturnType<typeof setTimeout> | undefined

const runtimeFilterOptions = computed(() => [
  { value: '', label: '全部' },
  ...props.runtimes.map((rt) => ({
    value: rt.workflow_runtime_id,
    label: rt.display_name || rt.workflow_runtime_id,
  })),
])

const versionFilterOptions = computed(() => [
  { value: '', label: '全部' },
  ...props.versions.map((ver) => ({
    value: ver.workflow_app_version_id,
    label: ver.display_version,
  })),
])

const stateFilterOptions = [
  { value: '', label: '全部' },
  { value: 'running', label: '执行中' },
  { value: 'succeeded', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'timed_out', label: '超时' },
  { value: 'cancelled', label: '已取消' },
]

const timeFilterOptions = [
  { value: '', label: '全部' },
  { value: 'today', label: '今天' },
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
]

const pageSizeOptions = [
  { value: '10', label: '10 条/页' },
  { value: '20', label: '20 条/页' },
  { value: '50', label: '50 条/页' },
]

const selectedFilterRuntime = computed(
  () => props.runtimes.find((rt) => rt.workflow_runtime_id === filterRuntimeId.value) ?? null,
)

const hasSecondaryFilters = computed(() =>
  Boolean(filterVersionId.value || filterState.value || filterTimeRange.value || searchQuery.value.trim()),
)

const hasAnyFilters = computed(() => Boolean(filterRuntimeId.value || hasSecondaryFilters.value))

function startedFrom(): string | undefined {
  const now = new Date()
  if (filterTimeRange.value === 'today') {
    now.setHours(0, 0, 0, 0)
    return now.toISOString()
  }
  if (filterTimeRange.value === '7d' || filterTimeRange.value === '30d') {
    const days = filterTimeRange.value === '7d' ? 7 : 30
    return new Date(now.getTime() - days * 86_400_000).toISOString()
  }
}

async function refresh(): Promise<void> {
  clearTimeout(searchTimer)
  const revision = ++requestRevision
  if (!props.projectId || !props.applicationId) return
  loading.value = true
  errorMessage.value = null
  try {
    const result = await listWorkflowRuns({
      projectId: props.projectId,
      applicationId: props.applicationId,
      workflowRuntimeId: filterRuntimeId.value || undefined,
      workflowAppVersionId: filterVersionId.value || undefined,
      state: filterState.value || undefined,
      search: searchQuery.value.trim() || undefined,
      startedFrom: startedFrom(),
      offset: offset.value,
      limit: limit.value,
    })
    if (revision !== requestRevision) return
    const totalCount = result.pagination.totalCount
    if (totalCount !== null && offset.value > 0 && offset.value >= totalCount) {
      offset.value = Math.max(0, Math.floor((totalCount - 1) / limit.value) * limit.value)
      await refresh()
      return
    }
    rawRuns.value = result.items
    backendTotalCount.value = totalCount
    backendHasMore.value = result.pagination.hasMore
  } catch (err) {
    if (revision === requestRevision) errorMessage.value = getErrorMessage(err)
  } finally {
    if (revision === requestRevision) loading.value = false
  }
}

function onSelectFilter(kind: 'runtime' | 'version' | 'state' | 'time', value: string | number | boolean | null): void {
  const str = typeof value === 'string' ? value : ''
  if (kind === 'runtime') filterRuntimeId.value = str
  else if (kind === 'version') filterVersionId.value = str
  else if (kind === 'state') filterState.value = str
  else filterTimeRange.value = str
  offset.value = 0
  void refresh()
}

function onPageSizeChange(value: string | number | boolean | null): void {
  const num = Number(value)
  if (Number.isFinite(num) && num > 0) {
    limit.value = num
    offset.value = 0
    void refresh()
  }
}

function goToOffset(nextOffset: number): void {
  offset.value = Math.max(0, nextOffset)
  void refresh()
}

function clearAllFilters(): void {
  filterRuntimeId.value = ''
  filterVersionId.value = ''
  filterState.value = ''
  filterTimeRange.value = ''
  const hadSearch = Boolean(searchQuery.value)
  searchQuery.value = ''
  offset.value = 0
  if (!hadSearch) void refresh()
}

function runtimeById(runtimeId: string): WorkflowAppRuntime | null {
  return props.runtimes.find((rt) => rt.workflow_runtime_id === runtimeId) ?? null
}

function runtimeNameById(runtimeId: string): string {
  const rt = runtimeById(runtimeId)
  if (rt?.display_name) return rt.display_name
  return runtimeId.length > 20 ? `${runtimeId.slice(0, 10)}…${runtimeId.slice(-6)}` : runtimeId
}

function versionLabelById(versionId: string | null | undefined): string {
  if (!versionId) return '—'
  const found = props.versions.find((v) => v.workflow_app_version_id === versionId)
  if (found) return found.display_version
  return versionId.length > 16 ? `${versionId.slice(0, 8)}…` : versionId
}

watch(
  () => [props.projectId, props.applicationId] as const,
  () => {
    offset.value = 0
    void refresh()
  },
  { immediate: true },
)

watch(searchQuery, () => {
  clearTimeout(searchTimer)
  requestRevision++
  offset.value = 0
  loading.value = true
  errorMessage.value = null
  searchTimer = setTimeout(() => void refresh(), 220)
}, { flush: 'sync' })

onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  requestRevision++
})

defineExpose({ refresh })
</script>

<style scoped>
.runs-card {
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  overflow: hidden;
  min-width: 0;
}

.runs-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 14px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--am-border);
}

.runs-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 14px;
}

.runs-filter-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.runs-filter-instance {
  width: clamp(104px, 14vw, 170px);
  min-width: 0;
}

.runs-filter-label {
  font-size: 13px;
  color: var(--am-text-muted);
  white-space: nowrap;
}

.runs-toolbar__right {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-inline-start: auto;
}

.runs-search {
  display: flex;
  align-items: center;
  gap: 6px;
  width: clamp(144px, 17vw, 210px);
  max-width: 100%;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-input);
  color: var(--am-text-muted);
}

.runs-search:focus-within {
  border-color: var(--am-input-focus-ring);
  box-shadow: inset 0 0 0 1px var(--am-input-focus-ring);
}

.runs-search input {
  flex: 1 1 auto;
  min-width: 0;
  border: none;
  outline: none;
  box-shadow: none;
  background: transparent;
  color: var(--am-text-strong);
  font-size: 13px;
}

.runs-search input:focus-visible {
  border-color: transparent;
  outline: none;
  box-shadow: none;
}

.runs-search input::-webkit-search-cancel-button { display: none; }

.runs-search button {
  border: none;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
  padding: 2px;
}

.runs-context-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding: 9px 16px;
  background: var(--am-surface-soft);
  border-bottom: 1px solid var(--am-border);
  font-size: 13px;
}

.runs-context-bar__info {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  color: var(--am-text-muted);
}

.runs-context-bar__info strong {
  color: var(--am-text-strong);
}

.runs-ctx-sep {
  margin: 0 2px;
}

.runs-state-box {
  padding: 40px 20px;
  display: grid;
  justify-items: center;
  gap: 8px;
  text-align: center;
}

.runs-state-box strong {
  font-size: 14px;
  color: var(--am-text-strong);
}

.runs-muted {
  color: var(--am-text-muted);
  font-size: 13px;
}

.runs-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.runs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.runs-table th {
  text-align: left;
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text);
  background: var(--am-table-header, var(--am-surface));
  border-bottom: 1px solid var(--am-border);
  white-space: nowrap;
}

.runs-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--am-border);
  color: var(--am-text-strong);
  vertical-align: middle;
}

.runs-table tbody tr {
  cursor: pointer;
}

.runs-table tbody tr:last-child td {
  border-bottom: none;
}

.runs-table tbody tr:hover {
  background: var(--am-hover-surface);
}

.runs-table tbody tr.is-selected {
  background: var(--am-row-selected);
}

.runs-nowrap {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.runs-instance-name {
  display: block;
  max-width: clamp(160px, 24vw, 360px);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runs-status-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.runs-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.runs-status-cell.is-ok .runs-dot {
  background: var(--am-action-primary);
}

.runs-status-cell.is-bad .runs-dot {
  background: #dc2626;
}

.runs-status-cell.is-warn .runs-dot {
  background: #f59e0b;
}

.runs-status-cell.is-neutral .runs-dot {
  background: var(--am-text-muted);
}

.runs-mini-spinner {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--am-border);
  border-top-color: var(--am-text-muted);
  animation: runs-spin 0.9s linear infinite;
}

@keyframes runs-spin {
  to {
    transform: rotate(360deg);
  }
}

.runs-biz-text {
  font-weight: 600;
}

.runs-biz-text.is-ng {
  color: #dc2626;
}

.col-actions {
  width: 88px;
  white-space: nowrap;
}

.runs-link-btn {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--am-action-primary);
  cursor: pointer;
}

.runs-link-btn:hover {
  color: var(--am-action-primary-hover);
}

.runs-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 14px;
  padding: 10px 16px;
  border-top: 1px solid var(--am-border);
}

.runs-page-meta {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.runs-pagination :deep(.pagination-controls) {
  border: none;
  padding: 0;
  background: transparent;
  flex: 1;
}

@media (prefers-reduced-motion: reduce) {
  .runs-mini-spinner { animation: none; }
}
</style>
