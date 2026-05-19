<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Play, RefreshCw, Wand2 } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import {
  createYoloXConversionTask,
  createYoloXTrainingTask,
  getPlatformBaseModelDetail,
  listPlatformBaseModels,
  listYoloXConversionTasks,
  listYoloXTrainingTasks,
  type ConversionTargetKey,
  type PlatformBaseModelDetail,
  type PlatformBaseModelSummary,
  type YoloXConversionTaskSummary,
  type YoloXTrainingTaskSubmissionResponse,
  type YoloXTrainingTaskSummary,
  type YoloXConversionTaskSubmissionResponse,
} from '../services/model.service'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()

const baseModels = ref<PlatformBaseModelSummary[]>([])
const selectedModelDetail = ref<PlatformBaseModelDetail | null>(null)
const trainingTasks = ref<YoloXTrainingTaskSummary[]>([])
const conversionTasks = ref<YoloXConversionTaskSummary[]>([])
const loading = ref(false)
const trainingSubmitting = ref(false)
const conversionSubmitting = ref(false)
const errorMessage = ref<string | null>(null)
const lastTrainingSubmission = ref<YoloXTrainingTaskSubmissionResponse | null>(null)
const lastConversionSubmission = ref<YoloXConversionTaskSubmissionResponse | null>(null)

const trainingDatasetExportId = ref('')
const trainingManifestKey = ref('')
const recipeId = ref('yolox-default')
const modelScale = ref('tiny')
const outputModelName = ref('yolox-custom')
const warmStartModelVersionId = ref('')
const maxEpochs = ref(1)
const batchSize = ref(1)
const evaluationInterval = ref(5)
const precision = ref('fp32')
const inputWidth = ref(640)
const inputHeight = ref(640)
const trainingDisplayName = ref('')

const conversionSourceModelVersionId = ref('')
const conversionTarget = ref<ConversionTargetKey>('onnx')
const conversionRuntimeProfileId = ref('')
const conversionDisplayName = ref('')

const canWriteTasks = computed(() => sessionStore.hasScopes(['tasks:write']))
const selectedProjectId = computed(() => projectStore.selectedProjectId)

const selectedModelAvailableVersions = computed(() => selectedModelDetail.value?.versions ?? selectedModelDetail.value?.available_versions ?? [])

onMounted(async () => {
  if (projectStore.projects.length === 0) {
    await projectStore.loadProjects()
  }
  await refreshPage()
})

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('complete') || normalized.includes('success') || normalized.includes('succeed')) return 'success'
  if (normalized.includes('fail') || normalized.includes('error')) return 'danger'
  if (normalized.includes('queue') || normalized.includes('pending')) return 'warning'
  if (normalized.includes('run') || normalized.includes('process')) return 'info'
  return 'neutral'
}

function progressText(progress: Record<string, unknown>): string {
  const value = progress.percent ?? progress.progress_percent ?? progress.progress
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)}%` : '-'
}

async function refreshPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const [models, training, conversion] = await Promise.all([
      listPlatformBaseModels(),
      listYoloXTrainingTasks(selectedProjectId.value),
      listYoloXConversionTasks(selectedProjectId.value),
    ])
    baseModels.value = models
    trainingTasks.value = training
    conversionTasks.value = conversion
    if (!selectedModelDetail.value && models[0]) {
      await selectBaseModel(models[0].model_id)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('modelOps.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function selectBaseModel(modelId: string): Promise<void> {
  try {
    selectedModelDetail.value = await getPlatformBaseModelDetail(modelId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('modelOps.messages.detailFailed')
  }
}

function useVersionForTraining(modelVersionId: string): void {
  warmStartModelVersionId.value = modelVersionId
}

function useVersionForConversion(modelVersionId: string): void {
  conversionSourceModelVersionId.value = modelVersionId
}

async function submitTraining(): Promise<void> {
  if (!trainingDatasetExportId.value.trim() && !trainingManifestKey.value.trim()) {
    errorMessage.value = t('modelOps.messages.trainingInputRequired')
    return
  }
  trainingSubmitting.value = true
  errorMessage.value = null
  try {
    lastTrainingSubmission.value = await createYoloXTrainingTask({
      projectId: selectedProjectId.value,
      datasetExportId: trainingDatasetExportId.value.trim(),
      datasetExportManifestKey: trainingManifestKey.value.trim(),
      recipeId: recipeId.value,
      modelScale: modelScale.value,
      outputModelName: outputModelName.value,
      warmStartModelVersionId: warmStartModelVersionId.value.trim(),
      evaluationInterval: evaluationInterval.value,
      maxEpochs: maxEpochs.value,
      batchSize: batchSize.value,
      precision: precision.value,
      inputWidth: inputWidth.value,
      inputHeight: inputHeight.value,
      displayName: trainingDisplayName.value,
    })
    trainingTasks.value = await listYoloXTrainingTasks(selectedProjectId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('modelOps.messages.submitTrainingFailed')
  } finally {
    trainingSubmitting.value = false
  }
}

async function submitConversion(): Promise<void> {
  conversionSubmitting.value = true
  errorMessage.value = null
  try {
    lastConversionSubmission.value = await createYoloXConversionTask({
      projectId: selectedProjectId.value,
      sourceModelVersionId: conversionSourceModelVersionId.value.trim(),
      target: conversionTarget.value,
      runtimeProfileId: conversionRuntimeProfileId.value.trim(),
      displayName: conversionDisplayName.value,
    })
    conversionTasks.value = await listYoloXConversionTasks(selectedProjectId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('modelOps.messages.submitConversionFailed')
  } finally {
    conversionSubmitting.value = false
  }
}
</script>

<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('modelOps.kicker') }}</p>
        <h1>{{ t('modelOps.title') }}</h1>
        <p class="page-description">{{ t('modelOps.description') }}</p>
      </div>
      <div class="page-actions">
        <Button variant="secondary" :disabled="loading" @click="refreshPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <section class="resource-section">
      <div class="section-heading">
        <div>
          <p class="page-kicker">{{ t('modelOps.baseKicker') }}</p>
          <h2>{{ t('modelOps.baseTitle') }}</h2>
        </div>
      </div>
      <EmptyState v-if="!loading && baseModels.length === 0" :title="t('modelOps.emptyModelsTitle')" :description="t('modelOps.emptyModelsDescription')" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('modelOps.columns.model') }}</th>
              <th>{{ t('modelOps.columns.type') }}</th>
              <th>{{ t('modelOps.columns.scale') }}</th>
              <th>{{ t('modelOps.columns.versions') }}</th>
              <th>{{ t('modelOps.columns.builds') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="model in baseModels"
              :key="model.model_id"
              :class="{ 'is-selected': model.model_id === selectedModelDetail?.model_id }"
              @click="selectBaseModel(model.model_id)"
            >
              <td>
                <strong>{{ model.model_name }}</strong>
                <span>{{ model.model_id }}</span>
              </td>
              <td>{{ model.model_type }}</td>
              <td>{{ model.model_scale }}</td>
              <td>{{ model.version_count }}</td>
              <td>{{ model.build_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="selectedModelDetail" class="summary-grid">
        <div>
          <span>{{ t('modelOps.fields.selectedModel') }}</span>
          <strong>{{ selectedModelDetail.model_name }}</strong>
        </div>
        <div>
          <span>{{ t('modelOps.fields.taskType') }}</span>
          <strong>{{ selectedModelDetail.task_type }}</strong>
        </div>
        <div>
          <span>{{ t('modelOps.fields.versionCount') }}</span>
          <strong>{{ selectedModelDetail.versions.length }}</strong>
        </div>
        <div>
          <span>{{ t('modelOps.fields.buildCount') }}</span>
          <strong>{{ selectedModelDetail.builds.length }}</strong>
        </div>
      </div>
      <div v-if="selectedModelAvailableVersions.length" class="compact-list">
        <div v-for="version in selectedModelAvailableVersions" :key="version.model_version_id" class="compact-list__item">
          <div>
            <strong>{{ version.model_version_id }}</strong>
            <span>{{ version.source_kind }}</span>
          </div>
          <div class="table-actions">
            <Button size="sm" variant="secondary" @click="useVersionForTraining(version.model_version_id)">{{ t('modelOps.actions.useWarmStart') }}</Button>
            <Button size="sm" variant="ghost" @click="useVersionForConversion(version.model_version_id)">{{ t('modelOps.actions.useConversionSource') }}</Button>
          </div>
        </div>
      </div>
    </section>

    <div class="operation-grid">
      <form class="form-panel" @submit.prevent="submitTraining">
        <div>
          <p class="page-kicker">{{ t('modelOps.trainingKicker') }}</p>
          <h2>{{ t('modelOps.trainingTitle') }}</h2>
        </div>
        <div class="form-grid">
          <label class="field field--wide">
            <span>{{ t('modelOps.fields.datasetExportId') }}</span>
            <input v-model="trainingDatasetExportId" placeholder="dataset-export-id" />
          </label>
          <label class="field field--wide">
            <span>{{ t('modelOps.fields.datasetManifestKey') }}</span>
            <input v-model="trainingManifestKey" placeholder="project/.../manifest.json" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.recipeId') }}</span>
            <input v-model="recipeId" required />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.modelScale') }}</span>
            <select v-model="modelScale">
              <option value="nano">nano</option>
              <option value="tiny">tiny</option>
              <option value="s">s</option>
              <option value="m">m</option>
              <option value="l">l</option>
              <option value="x">x</option>
            </select>
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.outputModelName') }}</span>
            <input v-model="outputModelName" required />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.warmStart') }}</span>
            <input v-model="warmStartModelVersionId" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.maxEpochs') }}</span>
            <input v-model.number="maxEpochs" type="number" min="1" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.batchSize') }}</span>
            <input v-model.number="batchSize" type="number" min="1" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.evaluationInterval') }}</span>
            <input v-model.number="evaluationInterval" type="number" min="1" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.precision') }}</span>
            <select v-model="precision">
              <option value="fp32">fp32</option>
              <option value="fp16">fp16</option>
            </select>
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.inputWidth') }}</span>
            <input v-model.number="inputWidth" type="number" min="32" step="32" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.inputHeight') }}</span>
            <input v-model.number="inputHeight" type="number" min="32" step="32" />
          </label>
          <label class="field field--wide">
            <span>{{ t('modelOps.fields.displayName') }}</span>
            <input v-model="trainingDisplayName" />
          </label>
        </div>
        <div class="form-actions">
          <Button variant="primary" type="submit" :disabled="!canWriteTasks || trainingSubmitting">
            <Play :size="16" />
            {{ trainingSubmitting ? t('modelOps.actions.submitting') : t('modelOps.actions.submitTraining') }}
          </Button>
        </div>
        <p v-if="lastTrainingSubmission" class="result-note">
          {{ t('modelOps.messages.trainingSubmitted') }}
          <RouterLink :to="`/tasks/${lastTrainingSubmission.task_id}`">{{ lastTrainingSubmission.task_id }}</RouterLink>
        </p>
      </form>

      <form class="form-panel" @submit.prevent="submitConversion">
        <div>
          <p class="page-kicker">{{ t('modelOps.conversionKicker') }}</p>
          <h2>{{ t('modelOps.conversionTitle') }}</h2>
        </div>
        <div class="form-grid">
          <label class="field field--wide">
            <span>{{ t('modelOps.fields.sourceModelVersionId') }}</span>
            <input v-model="conversionSourceModelVersionId" required />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.targetFormat') }}</span>
            <select v-model="conversionTarget">
              <option value="onnx">ONNX</option>
              <option value="onnx-optimized">ONNX optimized</option>
              <option value="openvino-ir-fp32">OpenVINO IR FP32</option>
              <option value="openvino-ir-fp16">OpenVINO IR FP16</option>
              <option value="tensorrt-engine-fp32">TensorRT FP32</option>
              <option value="tensorrt-engine-fp16">TensorRT FP16</option>
            </select>
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.runtimeProfileId') }}</span>
            <input v-model="conversionRuntimeProfileId" />
          </label>
          <label class="field field--wide">
            <span>{{ t('modelOps.fields.displayName') }}</span>
            <input v-model="conversionDisplayName" />
          </label>
        </div>
        <div class="form-actions">
          <Button variant="primary" type="submit" :disabled="!canWriteTasks || conversionSubmitting || !conversionSourceModelVersionId.trim()">
            <Wand2 :size="16" />
            {{ conversionSubmitting ? t('modelOps.actions.submitting') : t('modelOps.actions.submitConversion') }}
          </Button>
        </div>
        <p v-if="lastConversionSubmission" class="result-note">
          {{ t('modelOps.messages.conversionSubmitted') }}
          <RouterLink :to="`/tasks/${lastConversionSubmission.task_id}`">{{ lastConversionSubmission.task_id }}</RouterLink>
        </p>
      </form>
    </div>

    <section class="resource-section">
      <div>
        <p class="page-kicker">{{ t('modelOps.trainingHistoryKicker') }}</p>
        <h2>{{ t('modelOps.trainingHistoryTitle') }}</h2>
      </div>
      <EmptyState v-if="!loading && trainingTasks.length === 0" :title="t('modelOps.emptyTrainingTitle')" :description="t('modelOps.emptyTrainingDescription')" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('modelOps.columns.task') }}</th>
              <th>{{ t('modelOps.columns.state') }}</th>
              <th>{{ t('modelOps.columns.progress') }}</th>
              <th>{{ t('modelOps.columns.outputModel') }}</th>
              <th>{{ t('modelOps.columns.modelVersion') }}</th>
              <th>{{ t('modelOps.columns.createdAt') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in trainingTasks" :key="task.task_id">
              <td>
                <RouterLink :to="`/tasks/${task.task_id}`"><strong>{{ task.display_name || task.task_id }}</strong></RouterLink>
                <span>{{ task.dataset_export_id || task.dataset_export_manifest_key }}</span>
              </td>
              <td><StatusBadge :tone="statusTone(task.state)">{{ task.state }}</StatusBadge></td>
              <td>{{ progressText(task.progress) }}</td>
              <td>{{ task.output_model_name || '-' }}</td>
              <td>{{ task.model_version_id || task.latest_checkpoint_model_version_id || '-' }}</td>
              <td>{{ task.created_at }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="resource-section">
      <div>
        <p class="page-kicker">{{ t('modelOps.conversionHistoryKicker') }}</p>
        <h2>{{ t('modelOps.conversionHistoryTitle') }}</h2>
      </div>
      <EmptyState v-if="!loading && conversionTasks.length === 0" :title="t('modelOps.emptyConversionTitle')" :description="t('modelOps.emptyConversionDescription')" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('modelOps.columns.task') }}</th>
              <th>{{ t('modelOps.columns.state') }}</th>
              <th>{{ t('modelOps.columns.sourceVersion') }}</th>
              <th>{{ t('modelOps.columns.targetFormat') }}</th>
              <th>{{ t('modelOps.columns.builds') }}</th>
              <th>{{ t('modelOps.columns.createdAt') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in conversionTasks" :key="task.task_id">
              <td>
                <RouterLink :to="`/tasks/${task.task_id}`"><strong>{{ task.display_name || task.task_id }}</strong></RouterLink>
                <span>{{ task.task_id }}</span>
              </td>
              <td><StatusBadge :tone="statusTone(task.state)">{{ task.state }}</StatusBadge></td>
              <td>{{ task.source_model_version_id }}</td>
              <td>{{ (task.produced_formats.length ? task.produced_formats : task.target_formats).join(', ') || '-' }}</td>
              <td>{{ task.builds.map((build) => build.model_build_id).join(', ') || '-' }}</td>
              <td>{{ task.created_at }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>