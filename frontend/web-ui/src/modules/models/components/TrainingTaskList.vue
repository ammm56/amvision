<template>
  <section class="model-task-list training-list">
    <div class="model-task-list__toolbar">
      <div class="model-task-list__project">
        <h2>{{ projectName || t('modelOps.trainingHistoryTitle') }}</h2>
        <Button v-if="projectName" variant="ghost" @click="$emit('open-base-models')"><Database :size="16" />{{ zh ? '基础模型' : 'Base models' }}</Button>
      </div>
      <label class="model-task-list__search"><Search :size="16" aria-hidden="true" /><input :value="search" @input="setSearch(($event.target as HTMLInputElement).value)" :aria-label="zh ? '搜索任务名称' : 'Search tasks'" :placeholder="zh ? '搜索任务名称' : 'Search tasks'" /></label>
      <label><span>{{ zh ? '任务类型' : 'Task type' }}</span><SelectField :model-value="selectedTaskType" :options="taskTypeOptions || []" :aria-label="zh ? '任务类型' : 'Task type'" @update:model-value="$emit('change-task-type', String($event))" /></label>
      <label><span>{{ zh ? '状态' : 'Status' }}</span><SelectField :model-value="status" @update:model-value="setStatus(String($event))" :options="statusOptions" :aria-label="zh ? '状态' : 'Status'" /></label>
      <Button v-if="projectName" :loading="loading" @click="$emit('refresh')"><RefreshCw :size="16" />{{ t('common.refresh') }}</Button>
    </div>
    <p v-if="trainingTasks.length >= 100" class="training-list__hint">{{ zh ? '当前最多加载 100 条任务，筛选在已加载的任务内进行。' : 'At most 100 tasks are loaded; filters apply to those tasks.' }}</p>
    <p v-if="trainingTasks.length && loadError" class="training-list__hint" role="status">{{ zh ? '刷新失败，当前显示上次加载的任务。' : 'Refresh failed; showing the last loaded tasks.' }} <template v-if="updatedAt">{{ zh ? '最后更新：' : 'Last updated: ' }}{{ formatSystemDateTime(updatedAt, 'minutes') }}</template></p>
    <p v-if="!trainingTasks.length && loading" role="status">{{ t('modelOps.messages.loadingTasks') }}</p>
    <p v-else-if="!trainingTasks.length && loadError" role="status">{{ t('modelOps.messages.tasksUnavailable') }}</p>
    <EmptyState
      v-else-if="trainingTasks.length === 0"
      :title="t('modelOps.emptyTrainingTitle')"
      :description="t('modelOps.emptyTrainingDescription')"
    />
    <p v-else-if="filteredTasks.length === 0" role="status">{{ zh ? '没有符合条件的训练任务。' : 'No training tasks match these filters.' }}</p>
    <div v-else class="resource-table" :aria-busy="loading">
      <table>
        <thead>
          <tr>
            <th>{{ zh ? '任务名称' : 'Task name' }}</th>
            <th>{{ zh ? '模型名称' : 'Model' }}</th>
            <th>{{ zh ? '数据集' : 'Dataset' }}</th>
            <th>{{ zh ? '输出版本' : 'Output version' }}</th>
            <th>{{ t('modelOps.columns.state') }}</th>
            <th>{{ zh ? '训练进度' : 'Training progress' }}</th>
            <th>{{ zh ? '开始时间' : 'Started at' }}</th>
            <th>{{ zh ? '操作' : 'Actions' }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in visibleTasks" :key="task.task_id">
            <td>
              <RouterLink :to="detailLocation(selectedTaskType, task.task_id)">
                <strong class="training-list__task-name" :title="task.display_name || task.task_id">{{ task.display_name || task.task_id }}</strong>
              </RouterLink>
            </td>
            <td :title="task.output_model_name || undefined"><span class="model-task-list__value">{{ [task.model_type?.toUpperCase(), task.model_scale].filter(Boolean).join('-') || task.output_model_name || '—' }}</span></td>
            <td :title="datasetLabel(task)"><span class="model-task-list__value">{{ datasetLabel(task) }}</span></td>
            <td :title="task.model_version_id || task.latest_checkpoint_model_version_id || undefined">
              <span class="model-task-list__value">{{ outputVersionLabel(task) }}</span>
              <span v-if="isDeletedTrainingVersion(task, task.model_version_id || task.latest_checkpoint_model_version_id)" class="training-list__deleted-version">{{ zh ? '版本已删除' : 'Version deleted' }}</span>
            </td>
            <td><TaskStateBadge :state="task.state" appearance="icon" /></td>
            <td>
              <TaskProgress
                :percent="progressPercent(task.progress, task.state)"
                :value-text="epochText(task.progress)"
                :failed="isFailed(task.state)"
                :aria-label="t('modelOps.columns.progress')"
              />
            </td>
            <td>{{ task.started_at ? formatSystemDateTime(task.started_at, 'minutes') : '—' }}</td>
            <td><div class="model-task-list__actions"><RouterLink :to="detailLocation(selectedTaskType, task.task_id)">{{ zh ? '查看' : 'View' }}</RouterLink>
              <ResourceMenu :label="zh ? '更多操作' : 'More actions'" :items="rowActions(task)" @action="runAction(task, $event)" />
            </div></td>
          </tr>
        </tbody>
      </table>
      <ModelListPagination :page="currentPage" :page-size="pageSize" :item-count="visibleTasks.length" :total="filteredTasks.length" :zh="zh" :loading="loading" @page="setPage" @page-size="setPageSize" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useModelTaskListNavigation } from '../model-task-navigation'
import { isDeletedTrainingVersion } from '../model-version-action'
import { useI18n } from 'vue-i18n'
import { Activity, Copy, Database, RefreshCw, Search } from '@lucide/vue'

import type { ModelTaskType, ModelTrainingTaskSummary } from '../services/model.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import TaskProgress from '@/modules/tasks/components/TaskProgress.vue'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import { normalizeTaskState } from '@/modules/tasks/task-state'
import Button from '@/shared/ui/components/Button.vue'
import ResourceMenu from '@/shared/ui/components/ResourceMenu.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import ModelListPagination from './ModelListPagination.vue'

const props = defineProps<{
  selectedTaskType: ModelTaskType
  trainingTasks: ModelTrainingTaskSummary[]
  loading?: boolean
  loadError?: boolean
  updatedAt?: string
  taskTypeOptions?: Array<{ label: string; value: string }>
  projectName?: string
  datasetNames?: Map<string, string>
  versionNames?: Map<string, string>
  canReuse?: boolean
}>()
defineEmits<{ 'change-task-type': [value: string]; 'open-base-models': []; refresh: [] }>()

const { t, locale } = useI18n()
const router = useRouter()
const zh = computed(() => locale?.value?.startsWith('zh') ?? true)
const { search, status, page, pageSize, detailLocation, setSearch, setStatus, setPage, setPageSize } = useModelTaskListNavigation('training')
const statusOptions = computed(() => [
  { value: 'all', label: zh.value ? '全部' : 'All' },
  { value: 'queued', label: zh.value ? '等待中' : 'Queued' },
  { value: 'running', label: zh.value ? '运行中' : 'Running' },
  { value: 'paused', label: zh.value ? '已暂停' : 'Paused' },
  { value: 'succeeded', label: zh.value ? '已完成' : 'Completed' },
  { value: 'failed', label: zh.value ? '失败' : 'Failed' },
  { value: 'timed_out', label: zh.value ? '超时' : 'Timed out' },
  { value: 'cancelled', label: zh.value ? '已取消' : 'Cancelled' },
])
const filteredTasks = computed(() => props.trainingTasks.filter(task => {
  const term = search.value.trim().toLocaleLowerCase()
  return (!term || `${task.display_name || ''} ${task.task_id} ${task.output_model_name || ''} ${datasetLabel(task)}`.toLocaleLowerCase().includes(term)) && (status.value === 'all' || normalizeTaskState(task.state) === status.value)
}))
const pageCount = computed(() => Math.max(1, Math.ceil(filteredTasks.value.length / pageSize.value)))
const currentPage = computed(() => Math.min(page.value, pageCount.value))
const visibleTasks = computed(() => filteredTasks.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value))

function rowActions(task: ModelTrainingTaskSummary) {
  const actions = [{ id: 'status', label: zh.value ? '任务状态' : 'Task status', icon: Activity }]
  if (props.canReuse && ['succeeded', 'failed', 'timed_out', 'cancelled'].includes(normalizeTaskState(task.state))) actions.push({ id: 'copy', label: zh.value ? '复制训练配置' : 'Copy training settings', icon: Copy })
  return actions
}
function runAction(task: ModelTrainingTaskSummary, action: string): void {
  if (action === 'status') void router?.push(`/tasks/${encodeURIComponent(task.task_id)}`)
  if (action === 'copy') void router?.push({ path: '/models', query: { tab: 'training', task: props.selectedTaskType, trainingFrom: task.task_id } })
}

function datasetLabel(task: ModelTrainingTaskSummary): string {
  const id = task.dataset_version_id || task.dataset_export_id || task.dataset_export_manifest_key
  return id ? props.datasetNames?.get(id) || id : '—'
}
function outputVersionLabel(task: ModelTrainingTaskSummary): string {
  const id = task.model_version_id || task.latest_checkpoint_model_version_id
  return id ? props.versionNames?.get(id) || id.replace(/^model-version-/, '') : '—'
}

function epochValues(progress: Record<string, unknown>): [number, number] | null {
  const { epoch, max_epochs: total } = progress
  return typeof epoch === 'number' && Number.isInteger(epoch) && epoch >= 0
    && typeof total === 'number' && Number.isInteger(total) && total > 0 ? [epoch, total] : null
}

function epochText(progress: Record<string, unknown>): string {
  const values = epochValues(progress)
  return values ? `${values[0]} / ${values[1]}${zh.value ? ' 轮' : ' epochs'}` : ''
}

function progressPercent(progress: Record<string, unknown>, state: string): number | null {
  const value = progress.percent ?? progress.progress_percent ?? progress.progress
  const epochs = epochValues(progress)
  if (epochs && isFailed(state)) return epochs[0] / epochs[1] * 100
  if (isFailed(state) && value === 100) return null
  if (typeof value === 'number' && Number.isFinite(value)) return value
  return epochs ? epochs[0] / epochs[1] * 100 : null
}

function isFailed(state: string): boolean {
  const normalized = normalizeTaskState(state)
  return normalized === 'failed' || normalized === 'timed_out'
}
</script>

<style scoped>
.training-list__hint { color:var(--am-text-muted); }
.resource-table th:first-child { width:20%; }
.resource-table th:nth-child(5) { width:13%; }
.resource-table th:nth-child(7) { width:15%; }
.resource-table th:last-child { width:12%; }
.resource-table td:first-child a { color:var(--am-text); }
.training-list__task-name { display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; overflow:hidden; }
.training-list :deep(.task-state-icon__symbol) { flex-basis:16px; width:16px; height:16px; }
.training-list__deleted-version { display:block; margin-top:3px; color:var(--am-text-muted); font-size:12px; }
</style>
