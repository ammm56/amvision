<template>
  <div class="additional-evaluations">
    <header>
      <h2>{{ creating ? (zh ? '创建评估' : 'Create evaluation') : (zh ? '评估任务' : 'Evaluation tasks') }}</h2>
      <div v-if="!creating">
        <Button :loading="loading" @click="revision++">{{ zh ? '刷新' : 'Refresh' }}</Button>
        <Button v-if="canWrite" variant="primary" @click="creating = true"><Plus :size="16" />{{ zh ? '创建评估' : 'Create evaluation' }}</Button>
      </div>
    </header>
    <InlineError :message="error" />
    <div v-if="!creating" class="resource-table task-table">
      <table>
        <thead><tr><th scope="col">{{ zh ? '任务名称' : 'Task name' }}</th><th scope="col">{{ zh ? '状态' : 'Status' }}</th><th scope="col">{{ headline.label }}</th><th scope="col">{{ zh ? '样本' : 'Samples' }}</th><th scope="col">{{ zh ? '创建时间' : 'Created' }}</th><th scope="col">{{ zh ? '操作' : 'Actions' }}</th></tr></thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.task_id">
            <td>{{ task.display_name }}</td><td><TaskStateBadge :state="task.state" /></td>
            <td>{{ task[headline.key]?.toFixed(3) ?? '—' }}</td><td>{{ task.sample_count ?? '—' }}</td>
            <td>{{ formatSystemDateTime(task.created_at, 'minutes') }}</td>
            <td><RouterLink :to="`/models/${kind}/evaluation-tasks/${encodeURIComponent(task.task_id)}`">{{ zh ? '查看' : 'View' }}</RouterLink></td>
          </tr>
          <tr v-if="!tasks.length && !error"><td colspan="6" role="status">{{ loading ? (zh ? '加载中…' : 'Loading…') : (zh ? '暂无评估任务' : 'No evaluation tasks') }}</td></tr>
        </tbody>
      </table>
    </div>
    <form v-else class="resource-section evaluation-form" @submit.prevent="submit">
      <template v-if="dense">
        <FilePicker :model-value="file" :label="zh ? '评估数据包' : 'Evaluation bundle'" accept=".zip,application/zip" icon="archive" :disabled="submitting" @update:model-value="file = Array.isArray($event) ? $event[0] ?? null : $event" />
        <p>{{ zh ? 'ZIP 包需包含独立验证或测试集的原图、真值及模型预测，清单为 manifest.json。' : 'Include original images, labels and model predictions from an independent validation or test split, with manifest.json.' }}</p>
        <label v-if="kind === 'anomaly'" class="field"><span>{{ zh ? '判定阈值' : 'Decision threshold' }}</span><input v-model.number="threshold" type="number" min="0" max="1" step="0.001" required /></label>
      </template>
      <template v-else>
      <p v-if="inputLoading" role="status">{{ zh ? '正在读取模型和数据集导出…' : 'Loading model versions and dataset exports…' }}</p>
      <label class="field"><span>{{ zh ? '模型版本' : 'Model version' }}</span><Select v-model="modelId" :options="sourceOptions" /></label>
      <label class="field"><span>{{ zh ? '数据集导出' : 'Dataset export' }}</span><Select v-model="exportId" :options="exportOptions" /></label>
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
import { modelDisplayName, modelVersionDisplayName } from '../model-display-name'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Plus } from '@lucide/vue'
import { listProjectDatasetExports, type DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import Select from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { evaluationHeadline } from '../model-evaluation-types'
import { listDeploymentSourceModels, type DeploymentSourceModelSummary } from '../services/model.service'
import { createDenseEvaluation, createModelEvaluation, isDenseEvaluation, listModelEvaluations, type AdditionalEvaluationKind, type ModelEvaluationRecord } from '../services/model-evaluation.service'

const props = defineProps<{ projectId: string; zh: boolean; canWrite: boolean; kind: AdditionalEvaluationKind }>()
const router = useRouter()
const tasks = ref<ModelEvaluationRecord[]>([])
const revision = ref(0)
const loading = ref(false)
const creating = ref(false)
const inputLoading = ref(false)
const submitting = ref(false)
const error = ref('')
const models = ref<DeploymentSourceModelSummary[]>([])
const exports = ref<DatasetExportSummary[]>([])
const modelId = ref('')
const exportId = ref('')
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
const exportOptions = computed(() => exports.value.map(item => ({ value: item.dataset_export_id, label: item.display_name || item.dataset_export_id })))
const selectedExport = computed(() => exports.value.find(item => item.dataset_export_id === exportId.value))
const mismatch = computed(() => {
  const labels = sources.value.find(item => item.version.model_version_id === modelId.value)?.version.metadata.category_names
  return Array.isArray(labels) && labels.length > 0 && !!selectedExport.value?.category_names.length
    && JSON.stringify(labels) !== JSON.stringify(selectedExport.value.category_names)
})
const readyToSubmit = computed(() => dense.value ? Boolean(file.value) : Boolean(modelId.value && selectedExport.value && !mismatch.value))

watch([() => props.projectId, revision, creating], async ([project, , open], _, onCleanup) => {
  if (!project) return
  const request = new AbortController()
  onCleanup(() => request.abort())
  error.value = ''
  if (open) {
    modelId.value = ''; exportId.value = ''; name.value = ''
    file.value = null; threshold.value = 0.5
    models.value = []; exports.value = []
    const kind = props.kind
    if (isDenseEvaluation(kind)) return
    inputLoading.value = true
    try {
      const [availableModels, availableExports] = await Promise.all([
        listDeploymentSourceModels(project, kind), listProjectDatasetExports(project, kind, 'completed'),
      ])
      if (request.signal.aborted) return
      models.value = availableModels
      exports.value = availableExports.filter(item => formats[kind].includes(item.format_id)
        && !item.metadata.files_cleaned_at && item.split_names.some(split => ['val', 'test'].includes(split)))
    } catch (cause) { if (!request.signal.aborted) error.value = cause instanceof Error ? cause.message : String(cause) }
    finally { if (!request.signal.aborted) inputLoading.value = false }
    return
  }
  loading.value = true
  try { tasks.value = await listModelEvaluations(props.kind, project, request.signal) }
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
</script>

<style scoped>
.additional-evaluations, .evaluation-form { display:grid; gap:14px; min-width:0; }
.additional-evaluations header, .additional-evaluations header > div, .evaluation-form footer { display:flex; flex-wrap:wrap; align-items:center; gap:10px; }
.additional-evaluations header { justify-content:space-between; }
.additional-evaluations h2, .evaluation-form p { margin:0; }
.evaluation-form { max-width:860px; }
.evaluation-form footer { justify-content:flex-end; }
.task-table { overflow:auto; }
.task-table table { width:100%; table-layout:fixed; }
.task-table :is(td,th) { overflow-wrap:anywhere; }
.task-table th:first-child { width:27%; }
.task-table a { color:var(--am-brand-primary); }
</style>
