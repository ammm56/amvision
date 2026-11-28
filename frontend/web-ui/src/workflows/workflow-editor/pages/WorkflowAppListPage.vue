<template>
  <section class="app-list-page">
    <div v-if="selectedProjectId" class="app-list-toolbar">
      <div class="app-list-search">
        <Search :size="15" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索应用名称"
          aria-label="搜索应用名称"
          @input="offset = 0"
        />
        <button v-if="searchQuery" type="button" aria-label="清空搜索" @click="searchQuery = ''; offset = 0">
          <X :size="13" />
        </button>
      </div>

      <div class="app-list-toolbar__right">
        <div class="app-filter-group">
          <span class="app-filter-label">发布状态</span>
          <Select
            fit-options
            floating
            :model-value="publishFilter"
            :options="publishFilterOptions"
            aria-label="发布状态"
            @update:model-value="selectPublishFilter"
          />
        </div>

        <div class="app-filter-group">
          <span class="app-filter-label">运行状态</span>
          <Select
            fit-options
            floating
            :model-value="runtimeFilter"
            :options="runtimeFilterOptions"
            aria-label="运行状态"
            @update:model-value="selectRuntimeFilter"
          />
        </div>

        <Button
          v-if="canWriteWorkflows"
          variant="secondary"
          data-app-import-btn
          @click="importDrawerOpen = true"
        >
          <FileUp :size="15" />
          导入文档
        </Button>

        <Button variant="secondary" :disabled="loading" :loading="loading" @click="refreshPage">
          <RefreshCw v-if="!loading" :size="15" />
          刷新
        </Button>

        <Button
          v-if="canWriteWorkflows"
          variant="primary"
          data-app-create-btn
          @click="openNewGraph"
        >
          <Plus :size="15" />
          新建应用
        </Button>
      </div>
    </div>

    <InlineError :message="errorMessage" />

    <div v-if="!selectedProjectId" class="app-list-card app-list-empty">
      <p>请先选择项目以管理视觉应用。</p>
      <Button variant="secondary" @click="router.push('/projects')">选择项目</Button>
    </div>

    <div v-else class="app-list-card">
      <div class="app-list-table-wrap">
        <table class="app-list-table">
          <thead>
            <tr>
              <th>应用名称</th>
              <th>最新发布</th>
              <th>运行实例</th>
              <th>触发入口</th>
              <th>更新时间</th>
              <th class="col-actions-th">操作</th>
            </tr>
          </thead>
          <tbody v-if="pagedApps.length > 0">
            <tr
              v-for="row in pagedApps"
              :key="row.application.application_id"
              :class="{ 'is-selected': activeRowId === row.application.application_id }"
              @click="activeRowId = row.application.application_id"
            >
              <td class="col-name">
                <RouterLink
                  :to="detailPath(row.application.application_id)"
                  class="app-name-link"
                  :title="row.application.display_name || row.application.application_id"
                  @click.stop
                >
                  {{ row.application.display_name || row.application.application_id }}
                </RouterLink>
              </td>
              <td class="col-version">
                <span :class="{ 'app-muted': !row.latestVersion }">
                  {{ row.latestVersion ? row.latestVersion.display_version : '未发布' }}
                </span>
              </td>
              <td class="col-runtimes">
                <div class="app-runtime-summary">
                  <template v-if="row.runtimes.length === 0">
                    <span class="app-rt-pill is-neutral">
                      <i class="app-dot" />
                      未创建
                    </span>
                  </template>
                  <template v-else>
                    <span
                      v-for="(seg, segIdx) in summarizeRuntimeCounts(row.runtimes)"
                      :key="seg.key"
                      class="app-rt-pill"
                      :class="`is-${seg.tone}`"
                    >
                      <span v-if="segIdx > 0" class="app-rt-sep">·</span>
                      <i class="app-dot" />
                      {{ seg.label }}
                    </span>
                  </template>
                </div>
              </td>
              <td class="col-triggers">{{ row.triggerCount }}</td>
              <td class="col-time">{{ formatSystemDateTime(row.application.updated_at) }}</td>
              <td class="col-actions" @click.stop>
                <div class="app-row-actions">
                  <button
                    type="button"
                    class="app-link-btn is-primary"
                    @click="openDetail(row.application.application_id)"
                  >
                    查看
                  </button>
                  <button
                    type="button"
                    class="app-link-btn is-primary"
                    @click="openGraphEditor(row.application.application_id)"
                  >
                    图编辑
                  </button>
                  <button
                    type="button"
                    class="app-more-btn"
                    :aria-expanded="openMenuAppId === row.application.application_id"
                    aria-label="更多操作"
                    @click="toggleRowMenu($event, row.application.application_id)"
                  >
                    <MoreHorizontal :size="16" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="!loading && filteredApps.length === 0" class="app-list-empty">
        <Layers :size="36" class="app-list-empty__icon" />
        <p>{{ workflowApps.length === 0 ? '暂无视觉应用' : '没有匹配的应用' }}</p>
        <Button v-if="workflowApps.length === 0 && canWriteWorkflows" variant="primary" size="sm" @click="openNewGraph">
          <Plus :size="14" />
          新建应用
        </Button>
        <Button v-else-if="workflowApps.length > 0" variant="secondary" size="sm" @click="resetFilters">
          清除筛选
        </Button>
      </div>

      <div v-if="filteredApps.length > 0" class="app-list-pagination">
        <PaginationControls
          numbered
          :offset="offset"
          :limit="pageSize"
          :item-count="pagedApps.length"
          :total-count="filteredApps.length"
          :disabled="loading"
          @previous="offset = Math.max(0, offset - pageSize)"
          @next="offset = offset + pageSize"
          @go="offset = $event"
        >
          <template #summary>共 {{ filteredApps.length }} 个应用</template>
        </PaginationControls>

        <div class="app-list-pagesize">
          <Select
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
        v-if="openMenuRow"
        class="app-row-menu"
        :style="menuStyle"
        role="menu"
        @click.stop
      >
        <button type="button" role="menuitem" @click="openInfoDrawer(openMenuRow, false)">
          应用信息
        </button>
        <button
          v-if="canWriteWorkflows"
          type="button"
          role="menuitem"
          @click="openInfoDrawer(openMenuRow, true)"
        >
          编辑信息
        </button>
        <button
          v-if="canWriteWorkflows"
          type="button"
          role="menuitem"
          @click="openCopyDrawer(openMenuRow)"
        >
          复制应用
        </button>
        <button
          v-if="canWriteWorkflows"
          type="button"
          role="menuitem"
          class="is-danger"
          @click="requestDeleteWorkflowApp(openMenuRow)"
        >
          删除应用
        </button>
      </div>
    </Teleport>

    <WorkflowAppInfoDrawer
      :open="infoDrawerOpen"
      :project-id="selectedProjectId"
      :project-name="selectedProjectName"
      :app-summary="infoTargetApp"
      :initial-editing="infoInitialEditing"
      :can-write="canWriteWorkflows"
      @close="infoDrawerOpen = false"
      @updated="handleAppUpdated"
    />

    <WorkflowAppCopyDialog
      :open="copyDrawerOpen"
      :project-id="selectedProjectId"
      :source-app="copyTargetApp"
      @close="copyDrawerOpen = false"
      @copied="handleAppCopied"
    />

    <WorkflowAppImportDialog
      :open="importDrawerOpen"
      :project-id="selectedProjectId"
      @close="importDrawerOpen = false"
      @imported="handleAppImported"
    />

    <ConfirmDialog
      v-if="pendingDeleteWorkflowApp"
      :title="pendingDeleteWorkflowApp.runtimes.length > 0 ? '无法删除应用' : '删除应用?'"
      :message="deleteDialogMessage"
      :confirm-label="pendingDeleteWorkflowApp.runtimes.length > 0 ? '我知道了' : '确认删除'"
      :cancel-label="pendingDeleteWorkflowApp.runtimes.length > 0 ? '' : '取消'"
      :confirm-variant="pendingDeleteWorkflowApp.runtimes.length > 0 ? 'primary' : 'danger'"
      :busy="Boolean(deletingApplicationId)"
      @cancel="pendingDeleteWorkflowApp = null"
      @confirm="handleDeleteConfirm"
    >
      <ul v-if="pendingDeleteWorkflowApp.runtimes.length > 0" class="app-delete-block-list">
        <li v-for="rt in pendingDeleteWorkflowApp.runtimes" :key="rt.workflow_runtime_id">
          <span>{{ rt.display_name || rt.workflow_runtime_id }}</span>
          <small>{{ formatRuntimeState(rt.observed_state) }}</small>
        </li>
      </ul>
    </ConfirmDialog>
  </section>
</template>

<script setup lang="ts">
import { FileUp, Layers, MoreHorizontal, Plus, RefreshCw, Search, X } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref, watch, type CSSProperties } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { getErrorMessage } from '@/shared/api/error'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import Select from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import WorkflowAppCopyDialog from '../components/WorkflowAppCopyDialog.vue'
import WorkflowAppImportDialog from '../components/WorkflowAppImportDialog.vue'
import WorkflowAppInfoDrawer from '../components/WorkflowAppInfoDrawer.vue'
import { deleteWorkflowApplication } from '../services/workflow-application.service'
import { listWorkflowApps, type WorkflowAppSummary } from '../services/workflow-app.service'
import type { WorkflowAppRuntime } from '../types'

interface RuntimeSegment {
  key: string
  label: string
  tone: 'ok' | 'neutral' | 'bad' | 'warn'
}

const router = useRouter()
const projectStore = useProjectStore()
const sessionStore = useSessionStore()

const loading = ref(false)
const errorMessage = ref<string | null>(null)
const workflowApps = ref<WorkflowAppSummary[]>([])
let appListRequest = 0
const activeRowId = ref('')
const searchQuery = ref('')
const publishFilter = ref<'all' | 'published' | 'unpublished'>('all')
const runtimeFilter = ref<'all' | 'running' | 'stopped' | 'failed' | 'none'>('all')
const offset = ref(0)
const pageSize = ref(20)

const openMenuAppId = ref<string | null>(null)
const menuStyle = ref<CSSProperties>({})

const infoDrawerOpen = ref(false)
const infoTargetApp = ref<WorkflowAppSummary | null>(null)
const infoInitialEditing = ref(false)

const copyDrawerOpen = ref(false)
const copyTargetApp = ref<WorkflowAppSummary | null>(null)

const importDrawerOpen = ref(false)

const pendingDeleteWorkflowApp = ref<WorkflowAppSummary | null>(null)
const deletingApplicationId = ref<string | null>(null)

const selectedProjectId = computed(() => projectStore.selectedProjectId)
const selectedProjectName = computed(
  () =>
    projectStore.projects.find((p) => p.project_id === selectedProjectId.value)?.display_name ||
    selectedProjectId.value ||
    '默认项目',
)
const canWriteWorkflows = computed(() => sessionStore.hasScopes(['workflows:write']))

const publishFilterOptions = [
  { label: '全部', value: 'all' },
  { label: '已发布', value: 'published' },
  { label: '未发布', value: 'unpublished' },
]

const runtimeFilterOptions = [
  { label: '全部', value: 'all' },
  { label: '运行中', value: 'running' },
  { label: '已停止', value: 'stopped' },
  { label: '异常', value: 'failed' },
  { label: '未创建', value: 'none' },
]

const pageSizeOptions = [10, 20, 50].map((n) => ({ label: `${n} 条/页`, value: String(n) }))

const filteredApps = computed(() => {
  const kw = searchQuery.value.trim().toLowerCase()
  return workflowApps.value.filter((item) => {
    if (kw) {
      const name = (item.application.display_name || item.application.application_id).toLowerCase()
      const id = item.application.application_id.toLowerCase()
      if (!name.includes(kw) && !id.includes(kw)) return false
    }
    if (publishFilter.value === 'published' && !item.latestVersion) return false
    if (publishFilter.value === 'unpublished' && Boolean(item.latestVersion)) return false
    if (runtimeFilter.value === 'none' && item.runtimes.length > 0) return false
    if (runtimeFilter.value !== 'all' && runtimeFilter.value !== 'none'
      && !summarizeRuntimeCounts(item.runtimes).some((segment) => segment.key === runtimeFilter.value)) {
      return false
    }
    return true
  })
})

const pagedApps = computed(() => filteredApps.value.slice(offset.value, offset.value + pageSize.value))

const openMenuRow = computed(
  () => workflowApps.value.find((item) => item.application.application_id === openMenuAppId.value) ?? null,
)

const deleteDialogMessage = computed(() => {
  const target = pendingDeleteWorkflowApp.value
  if (!target) return ''
  const name = target.application.display_name || target.application.application_id
  if (target.runtimes.length > 0) {
    return `“${name}” 仍关联 ${target.runtimes.length} 个运行实例，请先停止并删除关联实例后再删除应用：`
  }
  return `确认删除应用 “${name}” 及关联流程草稿？此操作不可撤销。`
})

onMounted(() => {
  window.addEventListener('click', closeRowMenu)
})

onBeforeUnmount(() => {
  appListRequest++
  window.removeEventListener('click', closeRowMenu)
})

watch(
  selectedProjectId,
  async (projectId) => {
    offset.value = 0
    activeRowId.value = ''
    workflowApps.value = []
    if (!projectId) {
      appListRequest++
      loading.value = false
      errorMessage.value = null
      return
    }
    await refreshPage()
  },
  { immediate: true },
)

function closeRowMenu(): void {
  openMenuAppId.value = null
}

function toggleRowMenu(event: MouseEvent, appId: string): void {
  event.stopPropagation()
  if (openMenuAppId.value === appId) {
    openMenuAppId.value = null
    return
  }
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const left = Math.min(rect.right - 136, window.innerWidth - 152)
  const top = rect.bottom + 4
  menuStyle.value = { left: `${Math.max(12, left)}px`, top: `${top}px` }
  openMenuAppId.value = appId
}

function selectPublishFilter(val: string | number | boolean | null): void {
  if (val === 'all' || val === 'published' || val === 'unpublished') {
    publishFilter.value = val
    offset.value = 0
  }
}

function selectRuntimeFilter(val: string | number | boolean | null): void {
  if (val === 'all' || val === 'running' || val === 'stopped' || val === 'failed' || val === 'none') {
    runtimeFilter.value = val
    offset.value = 0
  }
}

function changePageSize(val: string | number | boolean | null): void {
  const next = Number(val)
  if (!Number.isFinite(next) || next <= 0) return
  pageSize.value = next
  offset.value = 0
}

function resetFilters(): void {
  searchQuery.value = ''
  publishFilter.value = 'all'
  runtimeFilter.value = 'all'
  offset.value = 0
}

function summarizeRuntimeCounts(runtimes: WorkflowAppRuntime[]): RuntimeSegment[] {
  let running = 0
  let stopped = 0
  let failed = 0
  let transitioning = 0
  for (const rt of runtimes) {
    if (rt.observed_state === 'running') running++
    else if (rt.observed_state === 'failed') failed++
    else if (rt.observed_state === 'starting' || rt.observed_state === 'stopping') transitioning++
    else stopped++
  }
  const segments: RuntimeSegment[] = []
  if (running > 0) segments.push({ key: 'running', label: `运行 ${running}`, tone: 'ok' })
  if (transitioning > 0) segments.push({ key: 'transitioning', label: `切换中 ${transitioning}`, tone: 'warn' })
  if (stopped > 0) segments.push({ key: 'stopped', label: `停止 ${stopped}`, tone: 'neutral' })
  if (failed > 0) segments.push({ key: 'failed', label: `异常 ${failed}`, tone: 'bad' })
  return segments
}

function formatRuntimeState(state: string): string {
  if (state === 'running') return '运行中'
  if (state === 'stopped') return '已停止'
  if (state === 'failed') return '异常'
  if (state === 'starting') return '启动中'
  if (state === 'stopping') return '停止中'
  return state
}

function detailPath(applicationId: string): string {
  return `/workflows/apps/${encodeURIComponent(applicationId)}`
}

function openDetail(applicationId: string): void {
  void router.push(detailPath(applicationId))
}

function openGraphEditor(applicationId: string): void {
  void router.push(`/workflows/graph/apps/${encodeURIComponent(applicationId)}`)
}

function openNewGraph(): void {
  void router.push('/workflows/graph/new')
}

function openInfoDrawer(row: WorkflowAppSummary, editing: boolean): void {
  openMenuAppId.value = null
  infoTargetApp.value = row
  infoInitialEditing.value = editing
  infoDrawerOpen.value = true
}

function openCopyDrawer(row: WorkflowAppSummary): void {
  openMenuAppId.value = null
  copyTargetApp.value = row
  copyDrawerOpen.value = true
}

function requestDeleteWorkflowApp(row: WorkflowAppSummary): void {
  openMenuAppId.value = null
  pendingDeleteWorkflowApp.value = row
}

async function handleAppUpdated(): Promise<void> {
  infoDrawerOpen.value = false
  await refreshPage()
}

async function handleAppCopied(): Promise<void> {
  copyDrawerOpen.value = false
  await refreshPage()
}

async function handleAppImported(): Promise<void> {
  importDrawerOpen.value = false
  await refreshPage()
}

async function handleDeleteConfirm(): Promise<void> {
  const target = pendingDeleteWorkflowApp.value
  if (!target) return
  if (target.runtimes.length > 0) {
    pendingDeleteWorkflowApp.value = null
    return
  }
  deletingApplicationId.value = target.application.application_id
  errorMessage.value = null
  try {
    await deleteWorkflowApplication(selectedProjectId.value, target.application.application_id)
    pendingDeleteWorkflowApp.value = null
    await refreshPage()
  } catch (err) {
    errorMessage.value = getErrorMessage(err)
  } finally {
    deletingApplicationId.value = null
  }
}

async function refreshPage(): Promise<void> {
  const projectId = selectedProjectId.value
  if (!projectId) return
  const revision = ++appListRequest
  loading.value = true
  errorMessage.value = null
  try {
    const apps: WorkflowAppSummary[] = []
    let pageOffset = 0
    while (true) {
      const result = await listWorkflowApps(projectId, { offset: pageOffset, limit: 100 })
      if (revision !== appListRequest) return
      apps.push(...result.items)
      const next = result.pagination.nextOffset
      if (!result.pagination.hasMore || next === null || next <= pageOffset) break
      pageOffset = next
    }
    workflowApps.value = apps
    if (offset.value >= filteredApps.value.length && offset.value > 0) {
      offset.value = Math.max(0, Math.floor((filteredApps.value.length - 1) / pageSize.value) * pageSize.value)
    }
  } catch (err) {
    if (revision === appListRequest) errorMessage.value = getErrorMessage(err)
  } finally {
    if (revision === appListRequest) loading.value = false
  }
}
</script>

<style scoped>
.app-list-page {
  display: grid;
  gap: 14px;
  min-width: 0;
}

.app-list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 12px;
}

.app-list-search {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1 1 180px;
  max-width: min(320px, 100%);
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-input);
  color: var(--am-text-muted);
}

.app-list-search:focus-within {
  border-color: var(--am-input-focus-ring);
  box-shadow: inset 0 0 0 1px var(--am-input-focus-ring);
}

.app-list-search input {
  flex: 1 1 auto;
  min-width: 0;
  border: none;
  outline: none;
  box-shadow: none;
  background: transparent;
  color: var(--am-text-strong);
  font-size: 13px;
}

.app-list-search input:focus-visible {
  border-color: transparent;
  outline: none;
  box-shadow: none;
}

.app-list-search button {
  border: none;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
  padding: 2px;
}

.app-list-toolbar__right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.app-filter-group {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.app-filter-label {
  font-size: 13px;
  color: var(--am-text-muted);
  white-space: nowrap;
}

.app-list-card {
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  overflow: hidden;
}

.app-list-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.app-list-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.app-list-table th {
  text-align: left;
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text);
  background: var(--am-table-header, var(--am-surface));
  border-bottom: 1px solid var(--am-border);
  white-space: nowrap;
}

.app-list-table td {
  padding: 13px 16px;
  border-bottom: 1px solid var(--am-border);
  color: var(--am-text-strong);
  vertical-align: middle;
}

.app-list-table tbody tr {
  transition: background-color 120ms ease;
}

.app-list-table tbody tr:hover {
  background: var(--am-row-hover);
}

.app-list-table tbody tr.is-selected {
  background: var(--am-row-selected);
}

.app-name-link {
  color: var(--am-text-strong);
  font-weight: 600;
  text-decoration: none;
}

.app-name-link:hover {
  color: var(--am-action-primary);
}

.app-muted {
  color: var(--am-text-muted);
}

.app-runtime-summary {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.app-rt-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
}

.app-rt-sep {
  color: var(--am-text-muted);
  margin-right: 2px;
}

.app-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.app-rt-pill.is-ok .app-dot {
  background: var(--am-action-primary);
}

.app-rt-pill.is-neutral {
  color: var(--am-text-muted);
}

.app-rt-pill.is-neutral .app-dot {
  background: var(--am-text-muted);
}

.app-rt-pill.is-bad {
  color: #dc2626;
}

.app-rt-pill.is-bad .app-dot {
  background: #dc2626;
}

.app-rt-pill.is-warn {
  color: #d97706;
}

.app-rt-pill.is-warn .app-dot {
  background: #f59e0b;
}

.col-triggers,
.col-time {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.col-actions-th,
.col-actions {
  width: 150px;
  white-space: nowrap;
}

.app-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 14px;
}

.app-link-btn {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--am-action-primary);
  cursor: pointer;
}

.app-more-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--am-text);
  cursor: pointer;
}

.app-more-btn:hover {
  background: var(--am-hover-surface);
}

.app-list-empty {
  padding: 48px 20px;
  display: grid;
  justify-items: center;
  gap: 10px;
  color: var(--am-text-muted);
  text-align: center;
}

.app-list-empty__icon {
  opacity: 0.45;
}

.app-list-empty p {
  margin: 0;
  font-size: 14px;
}

.app-list-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
}

.app-list-pagination :deep(.pagination-controls) {
  border: none;
  padding: 0;
  background: transparent;
  flex: 1 1 auto;
}

.app-list-pagesize {
  flex: none;
}

.app-row-menu {
  position: fixed;
  z-index: calc(var(--am-z-modal) + 2);
  min-width: 136px;
  padding: 6px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
  box-shadow: var(--am-shadow-floating);
  display: grid;
  gap: 2px;
}

.app-row-menu button {
  padding: 7px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--am-text-strong);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.app-row-menu button:hover {
  background: var(--am-hover-surface);
}

.app-row-menu button.is-danger {
  color: #dc2626;
}

.app-delete-block-list {
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--am-surface-soft);
  border: 1px solid var(--am-border);
  list-style: none;
  display: grid;
  gap: 6px;
  font-size: 13px;
}

.app-delete-block-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--am-text-strong);
}

.app-delete-block-list small {
  color: var(--am-text-muted);
}
</style>
