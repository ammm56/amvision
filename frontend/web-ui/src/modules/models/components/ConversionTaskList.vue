<template>
  <section class="model-task-list conversion-list">
    <div class="model-task-list__toolbar">
      <div class="model-task-list__project">
        <h2>{{ projectName || t('modelOps.conversionHistoryTitle') }}</h2>
        <Button v-if="projectName" variant="ghost" @click="$emit('open-base-models')"><Database :size="16" />{{ zh ? '基础模型' : 'Base models' }}</Button>
      </div>
      <label class="model-task-list__search"><Search :size="16" aria-hidden="true" /><input :value="search" @input="setSearch(($event.target as HTMLInputElement).value)" :aria-label="zh ? '搜索转换任务' : 'Search conversion tasks'" :placeholder="zh ? '搜索任务名称' : 'Search tasks'" /></label>
      <label><span>{{ zh ? '任务类型' : 'Task type' }}</span><SelectField :model-value="selectedTaskType" :options="taskTypeOptions || []" :aria-label="zh ? '任务类型' : 'Task type'" @update:model-value="$emit('change-task-type', String($event))" /></label>
      <label><span>{{ zh ? '状态' : 'Status' }}</span><SelectField :model-value="status" @update:model-value="setStatus(String($event))" :options="statusOptions" :aria-label="zh ? '状态' : 'Status'" /></label>
      <Button :loading="loading" @click="$emit('refresh')"><RefreshCw :size="16" />{{ t('common.refresh') }}</Button>
    </div>
    <div class="model-task-list__section">
    <h3 class="model-task-list__heading">{{ zh ? '转换任务' : 'Conversion tasks' }}</h3>
    <p v-if="conversionTasks.length >= 100" class="conversion-list__hint">{{ zh ? '当前最多加载 100 条任务，筛选在已加载的任务内进行。' : 'At most 100 tasks are loaded; filters apply to those tasks.' }}</p>
    <p v-if="conversionTasks.length && loadError" class="conversion-list__hint" role="status">{{ zh ? '刷新失败，当前显示上次加载的任务。' : 'Refresh failed; showing the last loaded tasks.' }} <template v-if="updatedAt">{{ zh ? '最后更新：' : 'Last updated: ' }}{{ formatSystemDateTime(updatedAt, 'minutes') }}</template></p>
    <p v-if="!conversionTasks.length && loading" role="status">{{ t('modelOps.messages.loadingTasks') }}</p>
    <p v-else-if="!conversionTasks.length && loadError" role="status">{{ t('modelOps.messages.tasksUnavailable') }}</p>
    <EmptyState
      v-else-if="conversionTasks.length === 0"
      :title="t('modelOps.emptyConversionTitle')"
      :description="t('modelOps.emptyConversionDescription')"
    />
    <p v-else-if="filteredTasks.length === 0" role="status">{{ zh ? '没有符合条件的转换任务。' : 'No conversion tasks match these filters.' }}</p>
    <div v-else class="resource-table" :aria-busy="loading">
      <table>
        <thead>
          <tr>
            <th>{{ t('modelOps.columns.sourceVersion') }}</th>
            <th>{{ t('modelOps.columns.targetFormat') }}</th>
            <th>{{ zh ? '精度 / 优化' : 'Precision / optimization' }}</th>
            <th>{{ t('modelOps.columns.state') }}</th>
            <th>{{ t('modelOps.columns.createdAt') }}</th>
            <th>{{ zh ? '操作' : 'Actions' }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in visibleTasks" :key="task.task_id">
            <td :title="task.source_model_version_id">
              <RouterLink :to="detailLocation(task.task_type || selectedTaskType, task.task_id)">
                <strong class="model-task-list__value">{{ sourceLabel(task) }}</strong>
              </RouterLink>
              <small class="model-task-list__value" :title="task.display_name">{{ task.display_name || task.task_id }}</small>
            </td>
            <td>{{ task.target_formats.map(format => conversionFormatName(format, zh)).join(' / ') || '—' }}</td>
            <td>{{ targetPrecision(task) }}</td>
            <td><TaskStateBadge :state="task.state" appearance="icon" /></td>
            <td>{{ formatSystemDateTime(task.created_at, 'minutes') }}</td>
            <td><div class="model-task-list__actions"><RouterLink :to="detailLocation(task.task_type || selectedTaskType, task.task_id)">{{ zh ? '查看' : 'View' }}</RouterLink>
              <ResourceMenu :label="zh ? '更多操作' : 'More actions'" :items="rowActions(task)" @action="runAction(task, $event)" />
            </div></td>
          </tr>
        </tbody>
      </table>
      <ModelListPagination :page="currentPage" :page-size="pageSize" :item-count="visibleTasks.length" :total="filteredTasks.length" :zh="zh" :loading="loading" @page="setPage" @page-size="setPageSize" />
    </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { RouterLink, useRouter } from 'vue-router'
import { useModelTaskListNavigation } from '../model-task-navigation'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Activity, Copy, Database, RefreshCw, Search } from '@lucide/vue'

import type { ModelConversionTaskSummary, ModelTaskType } from '../services/model.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import { normalizeTaskState } from '@/modules/tasks/task-state'
import Button from '@/shared/ui/components/Button.vue'
import ResourceMenu from '@/shared/ui/components/ResourceMenu.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import ModelListPagination from './ModelListPagination.vue'
import { conversionFormatName } from '../conversion-task-presentation'

const props = defineProps<{
  selectedTaskType: ModelTaskType
  conversionTasks: ModelConversionTaskSummary[]
  loading?: boolean
  loadError?: boolean
  updatedAt?: string
  taskTypeOptions?: Array<{ label: string; value: string }>
  projectName?: string
  sourceNames?: Map<string, string>
  canReuse?: boolean
}>()
defineEmits<{ 'change-task-type': [value: string]; 'open-base-models': []; refresh: [] }>()

const { t, locale } = useI18n()
const router = useRouter()
const zh = computed(() => locale?.value?.startsWith('zh') ?? true)
const { search, status, page, pageSize, detailLocation, setSearch, setStatus, setPage, setPageSize } = useModelTaskListNavigation('conversion')
const statusOptions = computed(() => [
  { value: 'all', label: zh.value ? '全部' : 'All' },
  { value: 'queued', label: zh.value ? '等待中' : 'Queued' },
  { value: 'running', label: zh.value ? '运行中' : 'Running' },
  { value: 'succeeded', label: zh.value ? '已完成' : 'Completed' },
  { value: 'failed', label: zh.value ? '失败' : 'Failed' },
  { value: 'timed_out', label: zh.value ? '超时' : 'Timed out' },
  { value: 'cancelled', label: zh.value ? '已取消' : 'Cancelled' },
])
const filteredTasks = computed(() => props.conversionTasks.filter(task => {
  const term = search.value.trim().toLocaleLowerCase()
  return (!term || `${task.display_name || ''} ${task.task_id} ${task.source_model_version_id || ''} ${sourceLabel(task)}`.toLocaleLowerCase().includes(term)) && (status.value === 'all' || normalizeTaskState(task.state) === status.value)
}))
const pageCount = computed(() => Math.max(1, Math.ceil(filteredTasks.value.length / pageSize.value)))
const currentPage = computed(() => Math.min(page.value, pageCount.value))
const visibleTasks = computed(() => filteredTasks.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value))
function rowActions(task: ModelConversionTaskSummary) {
  const actions = [{ id: 'status', label: zh.value ? '任务状态' : 'Task status', icon: Activity }]
  if (props.canReuse && ['failed', 'timed_out', 'cancelled'].includes(normalizeTaskState(task.state))) actions.push({ id: 'copy', label: zh.value ? '复制转换配置' : 'Copy conversion settings', icon: Copy })
  return actions
}
function runAction(task: ModelConversionTaskSummary, action: string): void {
  if (action === 'status') void router?.push(`/tasks/${encodeURIComponent(task.task_id)}`)
  if (action === 'copy') void router?.push({ path: '/models', query: { ...router.currentRoute.value.query, tab: 'conversion', task: task.task_type || props.selectedTaskType, conversionFrom: task.task_id } })
}
function sourceLabel(task: ModelConversionTaskSummary): string {
  return props.sourceNames?.get(task.source_model_version_id) || '—'
}
function targetPrecision(task: ModelConversionTaskSummary): string {
  const precisions = task.builds.filter(build => task.target_formats.includes(build.build_format)).map(build => build.runtime_precision?.toUpperCase()).filter(Boolean)
  return [...new Set(precisions)].join(' / ') || '—'
}

</script>

<style scoped>
.conversion-list__hint { color:var(--am-text-muted); margin-inline:14px; }
.resource-table th:first-child { width:32%; }
.resource-table th:nth-child(4) { width:13%; }
.resource-table th:nth-child(5) { width:19%; }
.resource-table th:last-child { width:12%; }
.resource-table td:first-child a { color:var(--am-text); }
.resource-table td:first-child small { color:var(--am-text-muted); }
</style>
