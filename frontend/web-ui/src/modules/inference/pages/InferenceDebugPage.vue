<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('inferenceOps.kicker') }}</p>
        <h1>{{ t('inferenceOps.title') }}</h1>
        <p class="page-description">{{ t('inferenceOps.description') }}</p>
      </div>
      <div class="page-actions">
        <label class="segmented-field">
          <span>task_type</span>
          <SelectField :model-value="selectedTaskType" :options="taskTypeOptions" @update:model-value="setTaskType" />
        </label>
        <Button variant="secondary" :disabled="loading" @click="refreshPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <section class="resource-section">
      <div>
        <p class="page-kicker">{{ t('inferenceOps.targetKicker') }}</p>
        <h2>{{ t('inferenceOps.targetTitle') }}</h2>
      </div>
      <EmptyState v-if="!loading && deployments.length === 0" :title="t('inferenceOps.emptyDeploymentsTitle')" :description="t('inferenceOps.emptyDeploymentsDescription')" />
      <div v-else class="form-grid">
        <label class="field field--wide">
          <span>{{ t('inferenceOps.fields.deploymentId') }}</span>
          <SelectField :model-value="selectedDeploymentId" :options="deploymentOptions" @update:model-value="setSelectedDeployment" />
        </label>
      </div>
      <div v-if="selectedDeployment" class="summary-grid">
        <div>
          <span>{{ t('inferenceOps.fields.status') }}</span>
          <strong>{{ selectedDeployment.status }}</strong>
        </div>
        <div>
          <span>{{ t('inferenceOps.fields.model') }}</span>
          <strong>{{ deploymentModelName(selectedDeployment) }}</strong>
        </div>
        <div>
          <span>{{ t('inferenceOps.fields.runtime') }}</span>
          <strong>{{ selectedDeployment.runtime_backend }} / {{ selectedDeployment.device_name }}</strong>
        </div>
        <div>
          <span>{{ t('inferenceOps.fields.instances') }}</span>
          <strong>{{ selectedDeployment.instance_count }}</strong>
        </div>
      </div>
    </section>

    <form class="form-panel" @submit.prevent="runDirectInference">
      <div>
        <p class="page-kicker">{{ t('inferenceOps.requestKicker') }}</p>
        <h2>{{ t('inferenceOps.requestTitle') }}</h2>
      </div>
      <div class="form-grid">
        <label class="field field--wide">
          <span>{{ t('inferenceOps.fields.inputUri') }}</span>
          <input v-model="inputUri" placeholder="project/files/image.jpg" />
        </label>
        <label class="field">
          <span>{{ t('inferenceOps.fields.inputFileId') }}</span>
          <input v-model="inputFileId" />
        </label>
        <label class="field">
          <span>{{ t('inferenceOps.fields.scoreThreshold') }}</span>
          <input v-model.number="scoreThreshold" type="number" min="0" max="1" step="0.01" />
        </label>
        <label class="field">
          <span>{{ t('inferenceOps.fields.transportMode') }}</span>
          <SelectField :model-value="inputTransportMode" :options="inputTransportModeOptions" @update:model-value="setInputTransportMode" />
        </label>
        <FilePicker
          v-model="imageFile"
          class="field--wide"
          icon="image"
          accept="image/*"
          :label="t('inferenceOps.fields.inputImage')"
          :description="t('inferenceOps.filePickerDescription')"
          :disabled="inferenceRunning"
        />
        <label class="field field--wide">
          <span>{{ t('inferenceOps.fields.imageBase64') }}</span>
          <textarea v-model="imageBase64" rows="3" />
        </label>
        <label class="field field--wide">
          <span>{{ t('inferenceOps.fields.displayName') }}</span>
          <input v-model="displayName" />
        </label>
        <label class="checkbox-field">
          <input v-model="saveResultImage" type="checkbox" />
          <span>{{ t('inferenceOps.fields.saveResultImage') }}</span>
        </label>
        <label class="checkbox-field">
          <input v-model="returnPreviewBase64" type="checkbox" />
          <span>{{ t('inferenceOps.fields.returnPreviewBase64') }}</span>
        </label>
      </div>
      <div class="form-actions">
        <Button variant="primary" type="submit" :disabled="inferenceRunning">
          <Send :size="16" />
          {{ t('inferenceOps.actions.directInfer') }}
        </Button>
        <Button variant="secondary" type="button" :disabled="!canWriteTasks || inferenceRunning" @click="submitAsyncInferenceTask">
          <UploadCloud :size="16" />
          {{ t('inferenceOps.actions.submitAsyncTask') }}
        </Button>
      </div>
      <div v-if="asyncInferenceSubmission" class="result-note result-note--actions">
        <span>
          {{ t('inferenceOps.messages.submitted') }}
          <RouterLink :to="`/tasks/${asyncInferenceSubmission.task_id}`">{{ asyncInferenceSubmission.task_id }}</RouterLink>
        </span>
        <Button size="sm" variant="secondary" :disabled="inferenceResultLoading === asyncInferenceSubmission.task_id" @click="toggleInferenceTaskResult(asyncInferenceSubmission.task_id)">
          <Eye :size="14" />
          {{ expandedInferenceTaskId === asyncInferenceSubmission.task_id ? t('inferenceOps.actions.collapseResult') : t('inferenceOps.actions.fetchResult') }}
        </Button>
      </div>
    </form>

    <section v-if="directInferenceResult" class="resource-section">
      <div>
        <p class="page-kicker">{{ t('inferenceOps.resultKicker') }}</p>
        <h2>{{ t('inferenceOps.resultTitle') }}</h2>
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('inferenceOps.fields.detectionCount') }}</span>
          <strong>{{ directInferenceResult.detection_count }}</strong>
        </div>
        <div>
          <span>{{ t('inferenceOps.fields.latency') }}</span>
          <strong>{{ directInferenceResult.latency_ms ?? '-' }}</strong>
        </div>
        <div>
          <span>{{ t('inferenceOps.fields.inputSize') }}</span>
          <strong>{{ directInferenceResult.image_width }} x {{ directInferenceResult.image_height }}</strong>
        </div>
        <div>
          <span>{{ t('inferenceOps.fields.resultObjectKey') }}</span>
          <strong>{{ directInferenceResult.result_object_key || '-' }}</strong>
        </div>
      </div>
      <figure v-if="directPreviewImageSrc" class="inference-preview">
        <img :src="directPreviewImageSrc" :alt="t('inferenceOps.previewAlt')" />
      </figure>
      <pre class="json-view">{{ directInferenceResultJson }}</pre>
    </section>

    <section class="resource-section">
      <div class="section-heading">
        <div>
          <p class="page-kicker">{{ t('inferenceOps.tasksKicker') }}</p>
          <h2>{{ t('inferenceOps.tasksTitle') }}</h2>
        </div>
        <Button variant="secondary" size="sm" :disabled="inferenceTasksLoading" @click="loadInferenceTasks">
          <RefreshCw :size="14" />
          {{ t('common.refresh') }}
        </Button>
      </div>
      <EmptyState v-if="!inferenceTasksLoading && inferenceTasks.length === 0" :title="t('inferenceOps.emptyTasksTitle')" :description="t('inferenceOps.emptyTasksDescription')" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('inferenceOps.columns.task') }}</th>
              <th>{{ t('inferenceOps.columns.status') }}</th>
              <th>{{ t('inferenceOps.columns.createdAt') }}</th>
              <th>{{ t('inferenceOps.fields.detectionCount') }}</th>
              <th>{{ t('inferenceOps.fields.latency') }}</th>
              <th>{{ t('inferenceOps.columns.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in inferenceTasks" :key="task.task_id">
              <td>
                <strong>{{ task.display_name || task.task_id }}</strong>
                <span>{{ task.task_id }}</span>
              </td>
              <td><StatusBadge :tone="statusTone(task.state)">{{ task.state }}</StatusBadge></td>
              <td>{{ formatSystemDateTime(task.created_at) }}</td>
              <td>{{ task.detection_count ?? '-' }}</td>
              <td>{{ task.latency_ms ?? '-' }}</td>
              <td>
                <div class="table-actions table-actions--wrap">
                  <Button size="sm" variant="secondary" :disabled="inferenceResultLoading === task.task_id" @click="toggleInferenceTaskResult(task.task_id)">
                    <Eye :size="14" />{{ expandedInferenceTaskId === task.task_id ? t('inferenceOps.actions.collapseResult') : t('inferenceOps.actions.fetchResult') }}
                  </Button>
                  <RouterLink :to="`/tasks/${task.task_id}`">{{ t('inferenceOps.actions.openTask') }}</RouterLink>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="selectedInferenceTaskResult" class="result-detail">
        <div class="section-heading">
          <div>
            <p class="page-kicker">{{ t('inferenceOps.asyncResultKicker') }}</p>
            <h2>{{ t('inferenceOps.asyncResultTitle') }}</h2>
          </div>
          <Button size="sm" variant="secondary" @click="collapseInferenceTaskResult">
            {{ t('inferenceOps.actions.collapseResult') }}
          </Button>
        </div>
        <div class="summary-grid">
          <div>
            <span>{{ t('inferenceOps.fields.fileStatus') }}</span>
            <strong>{{ selectedInferenceTaskResult.file_status }}</strong>
          </div>
          <div>
            <span>{{ t('inferenceOps.fields.taskState') }}</span>
            <strong>{{ selectedInferenceTaskResult.task_state }}</strong>
          </div>
          <div>
            <span>{{ t('inferenceOps.fields.resultObjectKey') }}</span>
            <strong>{{ selectedInferenceTaskResult.object_key || '-' }}</strong>
          </div>
        </div>
        <figure v-if="selectedInferenceTaskPreviewImageSrc" class="inference-preview">
          <img :src="selectedInferenceTaskPreviewImageSrc" :alt="t('inferenceOps.previewAlt')" />
        </figure>
        <pre class="json-view">{{ selectedInferenceTaskResultJson }}</pre>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Eye, RefreshCw, Send, UploadCloud } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import {
  createTaskInferenceTask,
  getTaskInferenceTaskResult,
  inferTaskDeployment,
  listTaskInferenceTasks,
  type TaskInferencePayload,
  type TaskInferenceTaskResult,
  type TaskInferenceTaskSubmission,
  type TaskInferenceTaskSummary,
} from '../services/inference.service'
import {
  listTaskDeployments,
  type ModelTaskType,
  type TaskDeploymentInstance,
} from '@/modules/deployments/services/deployment.service'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()

type SelectValue = string | number | boolean | null

const taskTypeOptions = [
  { label: 'detection', value: 'detection' },
  { label: 'classification', value: 'classification' },
  { label: 'segmentation', value: 'segmentation' },
  { label: 'pose', value: 'pose' },
  { label: 'obb', value: 'obb' },
]

const deployments = ref<TaskDeploymentInstance[]>([])
const selectedDeploymentId = ref('')
const selectedTaskType = ref<ModelTaskType>('detection')
const loading = ref(false)
const inferenceRunning = ref(false)
const inferenceTasksLoading = ref(false)
const inferenceResultLoading = ref<string | null>(null)
const errorMessage = ref<string | null>(null)

const inputFileId = ref('')
const inputUri = ref('')
const imageBase64 = ref('')
const imageFile = ref<File | null>(null)
const inputTransportMode = ref<'storage' | 'memory'>('memory')
const scoreThreshold = ref(0.3)
const saveResultImage = ref(false)
const returnPreviewBase64 = ref(true)
const displayName = ref('')

const directInferenceResult = ref<TaskInferencePayload | null>(null)
const asyncInferenceSubmission = ref<TaskInferenceTaskSubmission | null>(null)
const inferenceTasks = ref<TaskInferenceTaskSummary[]>([])
const selectedInferenceTaskResult = ref<TaskInferenceTaskResult | null>(null)
const expandedInferenceTaskId = ref<string | null>(null)

const selectedProjectId = computed(() => projectStore.selectedProjectId)
const canReadTasks = computed(() => sessionStore.hasScopes(['tasks:read']))
const canWriteTasks = computed(() => sessionStore.hasScopes(['tasks:write']))
const selectedDeployment = computed(() => deployments.value.find((item) => item.deployment_instance_id === selectedDeploymentId.value) ?? null)
const deploymentOptions = computed(() => deployments.value.map((deployment) => ({
  label: deploymentOptionLabel(deployment),
  value: deployment.deployment_instance_id,
})))
const inputTransportModeOptions = [
  { label: 'storage', value: 'storage' },
  { label: 'memory', value: 'memory' },
]
const directInferenceResultJson = computed(() => (directInferenceResult.value ? JSON.stringify(directInferenceResult.value, null, 2) : ''))
const selectedInferenceTaskResultJson = computed(() => (selectedInferenceTaskResult.value ? JSON.stringify(selectedInferenceTaskResult.value, null, 2) : ''))
const directPreviewImageSrc = computed(() => buildPreviewImageSrc(directInferenceResult.value?.preview_image_base64))
const selectedInferenceTaskPreviewImageSrc = computed(() => buildPreviewImageSrc(selectedInferenceTaskResult.value?.payload.preview_image_base64))

onMounted(async () => {
  if (projectStore.projects.length === 0) {
    await projectStore.loadProjects()
  }
  await refreshPage()
})

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('running') || normalized.includes('complete') || normalized.includes('success') || normalized.includes('ready')) return 'success'
  if (normalized.includes('fail') || normalized.includes('error') || normalized.includes('crash')) return 'danger'
  if (normalized.includes('queue') || normalized.includes('pending') || normalized.includes('created')) return 'warning'
  if (normalized.includes('process') || normalized.includes('start')) return 'info'
  return 'neutral'
}

function hasInferenceInput(): boolean {
  return Boolean(inputFileId.value.trim() || inputUri.value.trim() || imageBase64.value.trim() || imageFile.value)
}

function buildInferenceInput() {
  return {
    taskType: selectedTaskType.value,
    projectId: selectedProjectId.value,
    deploymentInstanceId: selectedDeploymentId.value,
    inputFileId: inputFileId.value.trim(),
    inputUri: inputUri.value.trim(),
    imageBase64: imageBase64.value.trim(),
    inputImage: imageFile.value,
    inputTransportMode: inputTransportMode.value,
    scoreThreshold: scoreThreshold.value,
    saveResultImage: saveResultImage.value,
    returnPreviewImageBase64: returnPreviewBase64.value,
    displayName: displayName.value.trim(),
  }
}

function buildPreviewImageSrc(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed) return null
  if (trimmed.startsWith('data:image/')) return trimmed
  return `data:image/jpeg;base64,${trimmed}`
}

function deploymentModelName(deployment: TaskDeploymentInstance): string {
  return deployment.model_name?.trim()
    || deployment.display_name?.trim()
    || deployment.model_build_id?.trim()
    || deployment.model_version_id?.trim()
    || deployment.deployment_instance_id
}

function deploymentOptionLabel(deployment: TaskDeploymentInstance): string {
  const displayName = deployment.display_name?.trim() || deployment.deployment_instance_id
  const modelName = deploymentModelName(deployment)
  return modelName === displayName ? displayName : `${displayName} / ${modelName}`
}

async function setTaskType(value: SelectValue): Promise<void> {
  const normalized = typeof value === 'string' ? value : String(value ?? '')
  if (!['detection', 'classification', 'segmentation', 'pose', 'obb'].includes(normalized)) return
  selectedTaskType.value = normalized as ModelTaskType
  selectedDeploymentId.value = ''
  directInferenceResult.value = null
  asyncInferenceSubmission.value = null
  selectedInferenceTaskResult.value = null
  expandedInferenceTaskId.value = null
  await refreshPage()
}

async function refreshPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    deployments.value = await listTaskDeployments(selectedTaskType.value, selectedProjectId.value)
    if (!deployments.value.some((item) => item.deployment_instance_id === selectedDeploymentId.value)) {
      selectedDeploymentId.value = deployments.value[0]?.deployment_instance_id ?? ''
    }
    await loadInferenceTasks()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('inferenceOps.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function selectDeployment(): Promise<void> {
  directInferenceResult.value = null
  asyncInferenceSubmission.value = null
  selectedInferenceTaskResult.value = null
  expandedInferenceTaskId.value = null
  await loadInferenceTasks()
}

async function setSelectedDeployment(value: SelectValue): Promise<void> {
  if (typeof value !== 'string') return
  selectedDeploymentId.value = value
  await selectDeployment()
}

function setInputTransportMode(value: SelectValue): void {
  inputTransportMode.value = value === 'memory' ? 'memory' : 'storage'
}

async function loadInferenceTasks(): Promise<void> {
  if (!selectedDeploymentId.value || !canReadTasks.value) {
    inferenceTasks.value = []
    return
  }
  inferenceTasksLoading.value = true
  errorMessage.value = null
  try {
    inferenceTasks.value = await listTaskInferenceTasks({
      taskType: selectedTaskType.value,
      projectId: selectedProjectId.value,
      deploymentInstanceId: selectedDeploymentId.value,
      limit: 20,
    })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('inferenceOps.messages.tasksFailed')
  } finally {
    inferenceTasksLoading.value = false
  }
}

async function runDirectInference(): Promise<void> {
  if (!selectedDeploymentId.value || !hasInferenceInput()) {
    errorMessage.value = t('inferenceOps.messages.inputRequired')
    return
  }
  inferenceRunning.value = true
  errorMessage.value = null
  try {
    directInferenceResult.value = null
    directInferenceResult.value = await inferTaskDeployment(buildInferenceInput())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('inferenceOps.messages.inferenceFailed')
  } finally {
    inferenceRunning.value = false
  }
}

async function submitAsyncInferenceTask(): Promise<void> {
  if (!selectedDeploymentId.value || !hasInferenceInput()) {
    errorMessage.value = t('inferenceOps.messages.inputRequired')
    return
  }
  inferenceRunning.value = true
  errorMessage.value = null
  try {
    asyncInferenceSubmission.value = await createTaskInferenceTask(buildInferenceInput())
    await loadInferenceTasks()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('inferenceOps.messages.inferenceFailed')
  } finally {
    inferenceRunning.value = false
  }
}

async function readInferenceTaskResult(taskId: string): Promise<void> {
  inferenceResultLoading.value = taskId
  errorMessage.value = null
  try {
    selectedInferenceTaskResult.value = await getTaskInferenceTaskResult(selectedTaskType.value, taskId)
    expandedInferenceTaskId.value = taskId
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('inferenceOps.messages.resultFailed')
  } finally {
    inferenceResultLoading.value = null
  }
}

async function toggleInferenceTaskResult(taskId: string): Promise<void> {
  if (expandedInferenceTaskId.value === taskId) {
    collapseInferenceTaskResult()
    return
  }
  await readInferenceTaskResult(taskId)
}

function collapseInferenceTaskResult(): void {
  expandedInferenceTaskId.value = null
  selectedInferenceTaskResult.value = null
}
</script>
