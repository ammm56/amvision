<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('conversionDetail.kicker') }}</p>
        <h1>{{ task?.display_name || taskId }}</h1>
        <p class="page-description">{{ t('conversionDetail.description') }}</p>
      </div>
      <div class="page-actions">
        <RouterLink to="/models">{{ t('conversionDetail.actions.backToModels') }}</RouterLink>
        <RouterLink v-if="task" :to="`/tasks/${task.task_id}`">任务状态</RouterLink>
        <Button
          v-if="task && canWriteTasks"
          variant="danger"
          :disabled="deleting || !canDeleteCurrentTask"
          @click="deleteDialogOpen = true"
        >
          <Trash2 :size="16" />
          {{ t('conversionDetail.actions.delete') }}
        </Button>
        <Button variant="secondary" :disabled="loading" @click="loadDetail">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <section v-if="task" class="resource-section">
      <div class="section-heading">
        <div>
          <p class="page-kicker">{{ t('conversionDetail.summaryKicker') }}</p>
          <h2>{{ t('conversionDetail.summaryTitle') }}</h2>
        </div>
        <StatusBadge :tone="statusTone(task.state)">{{ task.state }}</StatusBadge>
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('conversionDetail.fields.projectId') }}</span>
          <strong>{{ task.project_id }}</strong>
        </div>
        <div>
          <span>{{ t('conversionDetail.fields.modelType') }}</span>
          <strong>{{ task.model_type || '-' }}</strong>
        </div>
        <div>
          <span>{{ t('conversionDetail.fields.sourceModelVersionId') }}</span>
          <strong>{{ task.source_model_version_id || '-' }}</strong>
        </div>
        <div>
          <span>{{ t('conversionDetail.fields.runtimeProfileId') }}</span>
          <strong>{{ task.runtime_profile_id || '-' }}</strong>
        </div>
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('conversionDetail.fields.targetFormats') }}</span>
          <strong>{{ task.target_formats.join(', ') || '-' }}</strong>
        </div>
        <div>
          <span>{{ t('conversionDetail.fields.producedFormats') }}</span>
          <strong>{{ task.produced_formats.join(', ') || '-' }}</strong>
        </div>
        <div>
          <span>{{ t('conversionDetail.fields.outputPrefix') }}</span>
          <strong>{{ task.output_object_prefix || '-' }}</strong>
        </div>
        <div>
          <span>{{ t('conversionDetail.fields.createdAt') }}</span>
          <strong>{{ formatSystemDateTime(task.created_at) }}</strong>
        </div>
      </div>
      <InlineError :message="task.error_message ?? null" />
    </section>

    <section v-if="task" class="resource-section">
      <div>
        <p class="page-kicker">{{ t('conversionDetail.buildsKicker') }}</p>
        <h2>{{ t('conversionDetail.buildsTitle') }}</h2>
      </div>
      <EmptyState
        v-if="task.builds.length === 0"
        :title="t('conversionDetail.emptyBuildsTitle')"
        :description="t('conversionDetail.emptyBuildsDescription')"
      />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('conversionDetail.columns.build') }}</th>
              <th>{{ t('conversionDetail.columns.format') }}</th>
              <th>{{ t('conversionDetail.columns.file') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="build in task.builds" :key="build.model_build_id">
              <td>
                <strong>{{ build.model_build_id }}</strong>
              </td>
              <td>{{ build.build_format || '-' }}</td>
              <td>
                <strong>{{ build.build_file_id || '-' }}</strong>
                <span>{{ build.build_file_uri || '-' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="task" class="operation-grid">
      <article class="resource-section">
        <div>
          <p class="page-kicker">{{ t('conversionDetail.resultKicker') }}</p>
          <h2>{{ t('conversionDetail.resultTitle') }}</h2>
        </div>
        <pre class="json-view">{{ resultJson }}</pre>
      </article>
      <article class="resource-section">
        <div>
          <p class="page-kicker">{{ t('conversionDetail.specKicker') }}</p>
          <h2>{{ t('conversionDetail.specTitle') }}</h2>
        </div>
        <pre class="json-view">{{ taskSpecJson }}</pre>
      </article>
    </section>

    <section v-if="task" class="resource-section">
      <div>
        <p class="page-kicker">{{ t('conversionDetail.eventsKicker') }}</p>
        <h2>{{ t('conversionDetail.eventsTitle') }}</h2>
      </div>
      <EmptyState v-if="task.events.length === 0" :title="t('conversionDetail.emptyEventsTitle')" />
      <ol v-else class="event-timeline">
        <li v-for="event in task.events" :key="event.event_id">
          <time>{{ formatSystemDateTime(event.created_at) }}</time>
          <strong>{{ event.event_type }}</strong>
          <span>{{ event.message }}</span>
        </li>
      </ol>
    </section>

    <ConfirmDialog
      v-if="task && deleteDialogOpen"
      :kicker="t('conversionDetail.deleteDialog.kicker')"
      :title="t('conversionDetail.deleteDialog.title')"
      :message="deleteDialogMessage"
      :confirm-label="t('conversionDetail.actions.delete')"
      :cancel-label="t('common.cancel')"
      :busy="deleting"
      confirm-variant="danger"
      @cancel="deleteDialogOpen = false"
      @confirm="deleteCurrentTask"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RefreshCw, Trash2 } from '@lucide/vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import {
  deleteModelConversionTask,
  getModelConversionTaskDetail,
  type ModelConversionTaskDetail,
  type ModelTaskType,
} from '../services/model.service'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const { t } = useI18n()

const task = ref<ModelConversionTaskDetail | null>(null)
const loading = ref(false)
const deleting = ref(false)
const deleteDialogOpen = ref(false)
const errorMessage = ref<string | null>(null)

const taskId = computed(() => String(route.params.taskId ?? ''))
const taskType = computed<ModelTaskType | null>(() => {
  const value = String(route.params.taskType ?? '')
  return ['detection', 'classification', 'segmentation', 'pose', 'obb'].includes(value)
    ? value as ModelTaskType
    : null
})
const canWriteTasks = computed(() => sessionStore.hasScopes(['models:write', 'tasks:write']))
const canDeleteCurrentTask = computed(() => task.value ? isTerminalTask(task.value.state) : false)
const resultJson = computed(() => JSON.stringify(task.value?.result ?? {}, null, 2))
const taskSpecJson = computed(() => JSON.stringify(task.value?.task_spec ?? {}, null, 2))
const deleteDialogMessage = computed(() => {
  if (!task.value) return ''
  return t('conversionDetail.messages.confirmDelete')
    .replace('{taskId}', task.value.task_id)
    .replace('{buildCount}', String(task.value.builds.length))
})

onMounted(() => {
  void loadDetail()
})

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('complete') || normalized.includes('success') || normalized.includes('succeed')) return 'success'
  if (normalized.includes('fail') || normalized.includes('error')) return 'danger'
  if (normalized.includes('queue') || normalized.includes('pending')) return 'warning'
  if (normalized.includes('run') || normalized.includes('process')) return 'info'
  return 'neutral'
}

function isTerminalTask(state: string): boolean {
  return ['succeeded', 'failed', 'cancelled', 'canceled', 'completed'].includes(state.toLowerCase())
}

async function loadDetail(): Promise<void> {
  if (!taskType.value) {
    errorMessage.value = 'task_type 不能为空'
    return
  }
  loading.value = true
  errorMessage.value = null
  try {
    task.value = await getModelConversionTaskDetail(taskType.value, taskId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('conversionDetail.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function deleteCurrentTask(): Promise<void> {
  if (!taskType.value || !task.value || !canDeleteCurrentTask.value) return

  deleting.value = true
  errorMessage.value = null
  try {
    await deleteModelConversionTask(taskType.value, task.value.task_id)
    await router.push('/models')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('conversionDetail.messages.deleteFailed')
  } finally {
    deleting.value = false
    deleteDialogOpen.value = false
  }
}
</script>
