<template>
  <div class="additional-evaluations">
    <header v-if="creating">
      <h2>{{ zh ? '创建评估' : 'Create evaluation' }}</h2>
    </header>
    <header v-else class="evaluation-list-tools">
      <label class="evaluation-list-search">
        <Search :size="16" aria-hidden="true" />
        <input
          v-model.trim="searchQuery"
          type="search"
          :aria-label="zh ? '搜索评估任务' : 'Search evaluation tasks'"
          :placeholder="zh ? '搜索评估任务' : 'Search evaluation tasks'"
        />
      </label>
      <div class="evaluation-list-filters">
        <div class="evaluation-filter-item evaluation-filter-item--task">
          <span>{{ zh ? '任务类型' : 'Task type' }}</span>
          <slot name="task-type" />
        </div>
      </div>
      <div class="evaluation-toolbar__end">
        <Button :loading="loading" @click="revision++">
          <RefreshCw v-if="!loading" :size="16" />{{ zh ? '刷新' : 'Refresh' }}
        </Button>
      </div>
    </header>
    <InlineError :message="error" />
    <div v-if="!creating" class="resource-table task-table">
      <table>
        <thead><tr><th scope="col">{{ zh ? '任务名称' : 'Task name' }}</th><th scope="col">{{ zh ? '状态' : 'Status' }}</th><th scope="col">{{ headline.label }}</th><th scope="col">{{ zh ? '样本' : 'Samples' }}</th><th scope="col">{{ zh ? '创建时间' : 'Created' }}</th><th scope="col">{{ zh ? '操作' : 'Actions' }}</th></tr></thead>
        <tbody>
          <tr v-for="task in visibleTasks" :key="task.task_id">
            <td :title="taskName(task)"><span class="task-table__text">{{ taskName(task) }}</span></td>
            <td><TaskStateBadge :state="task.state" appearance="icon" /></td>
            <td>{{ task[headline.key]?.toFixed(3) ?? '—' }}</td>
            <td>{{ task.sample_count ?? '—' }}</td>
            <td>{{ formatSystemDateTime(task.created_at, 'minutes') }}</td>
            <td><ButtonLink size="sm" variant="ghost" class="ui-button--row-view" :to="`/models/${kind}/evaluation-tasks/${encodeURIComponent(task.task_id)}`">{{ zh ? '查看' : 'View' }}</ButtonLink></td>
          </tr>
          <tr v-if="!visibleTasks.length && !error"><td colspan="6" role="status">{{ loading ? (zh ? '加载中…' : 'Loading…') : tasks.length ? (zh ? '没有符合筛选条件的评估任务' : 'No matching evaluation tasks') : (zh ? '暂无评估任务' : 'No evaluation tasks') }}</td></tr>
        </tbody>
      </table>
      <ModelListPagination
        :page="currentPage"
        :page-size="pageSize"
        :item-count="visibleTasks.length"
        :total="filteredTasks.length"
        :zh="zh"
        :loading="loading"
        @page="page = $event"
        @page-size="pageSize = $event; page = 1"
      />
    </div>
    <form v-else class="resource-section evaluation-form" @submit.prevent="submit">
      <template v-if="dense">
        <FilePicker :model-value="file" :label="zh ? '评估数据包' : 'Evaluation bundle'" accept=".zip,application/zip" icon="archive" :disabled="submitting" @update:model-value="file = Array.isArray($event) ? $event[0] ?? null : $event" />
        <p>{{ zh ? 'ZIP 包需包含独立验证或测试集的原图、真值及模型预测，清单为 manifest.json。' : 'Include original images, labels and model predictions from an independent validation or test split, with manifest.json.' }}</p>
        <label v-if="kind === 'anomaly'" class="field"><span>{{ zh ? '判定阈值' : 'Decision threshold' }}</span><input v-model.number="threshold" type="number" min="0" max="1" step="0.001" required /></label>
      </template>
      <template v-else>
      <p v-if="inputLoading" role="status">{{ zh ? '正在读取模型和数据集导出…' : 'Loading model versions and dataset exports…' }}</p>
      <label class="field"><span>{{ zh ? '模型版本' : 'Model version' }}</span><Select v-model="modelId" :options="sourceOptions" :aria-label="zh ? '模型版本' : 'Model version'" /></label>
      <label class="field"><span>{{ zh ? '数据集导出' : 'Dataset export' }}</span><Select v-model="exportId" :options="exportOptions" :aria-label="zh ? '数据集导出' : 'Dataset export'" /></label>
      <p v-if="prefillUnavailable && !modelId" role="status">{{ zh ? '训练输出的模型版本当前不可用，请选择可用版本。' : 'The training output version is unavailable. Select an available version.' }}</p>
      <p v-if="!inputLoading && (!models.length || !exports.length)" role="status">{{ zh ? '需要已登记权重和含 test 或 val 的数据集导出。' : 'A registered checkpoint and a dataset export with a test or val split are required.' }}</p>
      <p v-if="mismatch" role="alert">{{ zh ? '模型和导出的类别顺序不同。' : 'The model and export use different class orders.' }}</p>
      <p v-else-if="selectedExport">{{ zh ? '评估划分' : 'Evaluation split' }} · {{ selectedExport.split_names.includes('test') ? 'test' : 'val' }}</p>
      </template>
      <label class="field"><span>{{ zh ? '任务名称（可选）' : 'Task name (optional)' }}</span><input v-model.trim="name" maxlength="128" /></label>
      <footer>
        <Button :disabled="submitting" @click="creating = false">{{ zh ? '取消' : 'Cancel' }}</Button>
        <Button type="submit" variant="primary" :loading="submitting" :disabled="!readyToSubmit">{{ zh ? '提交评估' : 'Submit evaluation' }}</Button>
      </footer>
    </form>
  </div>
</template>

<script setup lang="ts">
import { RefreshCw, Search } from '@lucide/vue'
import { modelDisplayName, modelVersionDisplayName, readCatalogVersionNames } from '../model-display-name'
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listProjectDatasetExports, type DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import { listDatasetVersionPage } from '@/modules/datasets/services/dataset-workspace.service'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import Select from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import ModelListPagination from './ModelListPagination.vue'
import { evaluationDatasetExportOptions, isEligibleEvaluationExport, type EvaluationDatasetVersion } from '../evaluation-dataset-exports'
import { classificationEvaluationTitle, evaluationHeadline, evaluationModelVersionId, usesDefaultClassificationEvaluationName } from '../model-evaluation-types'
import { listDeploymentSourceModels, type DeploymentSourceModelSummary } from '../services/model.service'
import { createDenseEvaluation, createModelEvaluation, isDenseEvaluation, listModelEvaluations, type AdditionalEvaluationKind, type ModelEvaluationRecord } from '../services/model-evaluation.service'

const props = defineProps<{ projectId: string; zh: boolean; canWrite: boolean; kind: AdditionalEvaluationKind }>()
const emit = defineEmits<{ focusMode: [active: boolean] }>()
const route = useRoute()
const router = useRouter()
const tasks = ref<ModelEvaluationRecord[]>([])
const searchQuery = ref('')
const page = ref(1)
const pageSize = ref(20)
const filteredTasks = computed(() => {
  const term = searchQuery.value.trim().toLocaleLowerCase()
  if (!term) return tasks.value
  return tasks.value.filter(task => (
    taskName(task).toLocaleLowerCase().includes(term)
    || task.task_id.toLocaleLowerCase().includes(term)
  ))
})
const pageCount = computed(() => Math.max(1, Math.ceil(filteredTasks.value.length / pageSize.value)))
const currentPage = computed(() => Math.min(page.value, pageCount.value))
const visibleTasks = computed(() => filteredTasks.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value))
watch([searchQuery, () => props.kind], () => { page.value = 1 })
const modelVersionNames = shallowRef(new Map<string, string>())
const revision = ref(0)
const loading = ref(false)
const creating = ref(false)
const inputLoading = ref(false)
const submitting = ref(false)
const error = ref('')
const models = ref<DeploymentSourceModelSummary[]>([])
const exports = ref<DatasetExportSummary[]>([])
const datasetVersions = ref(new Map<string, EvaluationDatasetVersion>())
const modelId = ref('')
const exportId = ref('')
const prefillUnavailable = ref(false)
let pendingPrefill: { projectId: string; versionId: string; exportId: string } | null = null
const name = ref('')
const file = ref<File | null>(null)
const threshold = ref(0.5)
const dense = computed(() => isDenseEvaluation(props.kind))
const headline = computed(() => evaluationHeadline[props.kind])
const formats = {
  classification: ['imagenet-classification-v1'],
  segmentation: ['coco-instance-seg-v1', 'yolo-instance-seg-v1'],
  pose: ['coco-keypoints-v1', 'yolo-pose-v1'],
  obb: ['dota-obb-v1', 'yolo-obb-v1'],
}
const sources = computed(() => models.value.flatMap(model => model.available_versions
  .filter(version => version.checkpoint_storage_uri && version.checkpoint_state !== 'missing')
  .map(version => ({ model, version }))))
const sourceOptions = computed(() => sources.value.map(({ model, version }) => ({ value: version.model_version_id, label: `${modelDisplayName(model)} · ${modelVersionDisplayName(version, true)}` })))
const exportOptions = computed(() => evaluationDatasetExportOptions(exports.value, datasetVersions.value, props.zh))
const selectedExport = computed(() => exports.value.find(item => item.dataset_export_id === exportId.value))
const mismatch = computed(() => {
  const labels = sources.value.find(item => item.version.model_version_id === modelId.value)?.version.metadata.category_names
  return Array.isArray(labels) && labels.length > 0 && !!selectedExport.value?.category_names.length
    && JSON.stringify(labels) !== JSON.stringify(selectedExport.value.category_names)
})
const readyToSubmit = computed(() => dense.value ? Boolean(file.value) : Boolean(modelId.value && selectedExport.value && !mismatch.value))
watch(creating, active => emit('focusMode', active))
onBeforeUnmount(() => emit('focusMode', false))

function taskName(task: ModelEvaluationRecord): string {
  if (props.kind !== 'classification') return task.display_name
  return classificationEvaluationTitle(task, modelVersionNames.value.get(evaluationModelVersionId(task)) ?? '', props.zh)
}

watch([() => route.query.evaluation, () => route.query.evaluationFrom, () => route.query.datasetFrom,
  () => props.projectId, () => props.canWrite],
([kind, versionId, datasetId, projectId, canWrite]) => {
  if (kind !== props.kind || dense.value || !projectId || !canWrite || typeof versionId !== 'string' || !versionId) return
  pendingPrefill = { projectId, versionId, exportId: typeof datasetId === 'string' ? datasetId : '' }
  if (creating.value) revision.value++
  else creating.value = true
  const { evaluationFrom: _version, datasetFrom: _dataset, ...query } = route.query
  void router.replace({ query })
}, { immediate: true })

watch([() => props.projectId, () => props.kind, revision, creating], async ([project, kind, , open], previous, onCleanup) => {
  if (project !== previous?.[0] || kind !== previous?.[1]) {
    tasks.value = []
    modelVersionNames.value = new Map()
  }
  if (!project) return
  const request = new AbortController()
  onCleanup(() => request.abort())
  error.value = ''
  if (open) {
    const prefill = pendingPrefill?.projectId === project ? pendingPrefill : null
    pendingPrefill = null
    modelId.value = ''; exportId.value = ''; name.value = ''
    file.value = null; threshold.value = 0.5
    models.value = []; exports.value = []; datasetVersions.value = new Map()
    prefillUnavailable.value = false
    if (isDenseEvaluation(kind)) return
    inputLoading.value = true
    try {
      const [availableModels, availableExports] = await Promise.all([
        listDeploymentSourceModels(project, kind, request.signal), listProjectDatasetExports(project, kind, 'completed'),
      ])
      if (request.signal.aborted) return
      const eligibleExports = availableExports.filter(item => isEligibleEvaluationExport(item, formats[kind]))
      const identities = new Map<string, EvaluationDatasetVersion>()
      const missing = new Set(eligibleExports.filter(item => !item.display_name?.trim() || item.version_number == null)
        .map(item => item.dataset_version_id))
      const limit = 100
      try {
        for (let offset = 0; missing.size; offset += limit) {
          const page = await listDatasetVersionPage({ project_id: project, task_type: kind, offset, limit }, request.signal)
          if (request.signal.aborted) return
          for (const item of page.items) {
            if (missing.delete(item.dataset_version_id)) identities.set(item.dataset_version_id, item)
          }
          if (!page.items.length || offset + limit >= page.total) break
        }
      } catch { /* 版本目录暂不可用时保留可选导出，使用导出已有的信息。 */ }
      if (request.signal.aborted) return
      datasetVersions.value = identities
      models.value = availableModels
      exports.value = eligibleExports
      if (prefill) {
        if (sources.value.some(({ version }) => version.model_version_id === prefill.versionId)) {
          modelId.value = prefill.versionId
          if (exports.value.some(item => item.dataset_export_id === prefill.exportId)) exportId.value = prefill.exportId
        } else prefillUnavailable.value = true
      }
    } catch (cause) { if (!request.signal.aborted) error.value = cause instanceof Error ? cause.message : String(cause) }
    finally { if (!request.signal.aborted) inputLoading.value = false }
    return
  }
  loading.value = true
  try {
    const results = await listModelEvaluations(kind, project, request.signal)
    if (request.signal.aborted) return
    tasks.value = results
    if (kind === 'classification') {
      const versionIds = results.filter(usesDefaultClassificationEvaluationName).map(evaluationModelVersionId)
      const names = await readCatalogVersionNames(project, '', versionIds, request.signal).catch(() => new Map<string, string>())
      if (!request.signal.aborted) modelVersionNames.value = names
    }
  }
  catch (cause) { if (!request.signal.aborted) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (!request.signal.aborted) loading.value = false }
}, { immediate: true })

async function submit(): Promise<void> {
  if (!props.canWrite || !readyToSubmit.value || submitting.value) return
  const kind = props.kind
  submitting.value = true
  error.value = ''
  try {
    const result = isDenseEvaluation(kind) && file.value
      ? await createDenseEvaluation(kind, props.projectId, name.value, threshold.value, file.value)
      : await createModelEvaluation(kind, {
        project_id: props.projectId, model_version_id: modelId.value, dataset_export_id: exportId.value, display_name: name.value,
      })
    await router.push(`/models/${kind}/evaluation-tasks/${encodeURIComponent(result.task_id)}`)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { submitting.value = false }
}
defineExpose({ openCreate: () => { if (props.canWrite) creating.value = true } })
</script>

<style scoped>
.additional-evaluations, .evaluation-form { display:grid; gap:14px; min-width:0; }
.evaluation-list-tools { display:flex; align-items:center; flex-wrap:wrap; gap:10px 14px; min-width:0; }
.evaluation-list-search { flex:1 1 200px; max-width:280px; margin-inline-end:auto; display:flex; align-items:center; gap:8px; min-width:0; padding:0 12px; border:1px solid var(--am-border); border-radius:var(--am-radius-md); background:var(--am-surface); color:var(--am-text-muted); }
.evaluation-list-search input { width:100%; min-width:0; min-height:36px; border:0; background:none; color:var(--am-text); }
.evaluation-list-search:focus-within { outline:1px solid var(--am-brand-primary); }
.evaluation-list-filters { display:flex; align-items:center; flex-wrap:wrap; gap:10px 12px; min-width:0; }
.evaluation-filter-item { display:inline-flex; align-items:center; gap:8px; min-width:0; }
.evaluation-filter-item > span { color:var(--am-text-muted); white-space:nowrap; font-size:13px; }
.evaluation-filter-item--task :deep(.ui-select) { width:136px; }
.additional-evaluations header > div, .evaluation-form footer { display:flex; flex-wrap:wrap; align-items:center; gap:10px; }
.additional-evaluations h2, .evaluation-form p { margin:0; }
.evaluation-form { max-width:860px; }
.evaluation-form footer { justify-content:flex-end; }
.task-table { overflow:auto; }
.task-table table { width:100%; table-layout:fixed; }
.task-table th { white-space:nowrap; }
.task-table td { overflow-wrap:anywhere; }
.task-table__text { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.task-table th:nth-child(1) { width:28%; }
.task-table th:nth-child(2) { width:13%; }
.task-table th:nth-child(3) { width:19%; }
.task-table th:nth-child(4) { width:10%; }
.task-table th:nth-child(5) { width:18%; }
.task-table th:nth-child(6) { width:12%; }
</style>
