<template>
  <section class="evaluation-panel">
    <header v-show="!step && (!compareOpen || conflicts.length)" ref="listToolbar" class="evaluation-list-tools">
      <div class="evaluation-toolbar">
        <h2>{{ zh ? '评估任务' : 'Evaluation tasks' }}</h2>
        <div>
          <Button :loading="loading" @click="load"><RefreshCw :size="16" />{{ zh ? '刷新' : 'Refresh' }}</Button>
          <Button v-if="canWrite" variant="primary" @click="openWizard()"><Plus :size="16" />{{ zh ? '创建评估' : 'Create evaluation' }}</Button>
        </div>
      </div>
      <div class="evaluation-list-filters">
        <label class="field"><span>{{ zh ? '任务类型' : 'Task type' }}</span><slot name="task-type" /></label>
        <label class="field"><span>{{ zh ? '数据版本' : 'Dataset version' }}</span><Select v-model="filterDataset" floating :options="datasetFilters" :aria-label="zh ? '数据版本' : 'Dataset version'" /></label>
        <label class="field"><span>{{ zh ? '数据划分' : 'Dataset split' }}</span><Select v-model="filterSplit" floating :options="splitFilters" :aria-label="zh ? '数据划分' : 'Dataset split'" /></label>
      </div>
      <label class="evaluation-list-search"><Search :size="16" aria-hidden="true" /><input v-model.trim="filterQuery" type="search" :aria-label="zh ? '搜索模型版本' : 'Search model versions'" :placeholder="zh ? '搜索模型版本' : 'Search model versions'" /></label>
    </header>
    <InlineError :message="error" />
    <div v-show="!step && (!compareOpen || conflicts.length)" class="resource-table evaluation-table">
      <table>
        <thead><tr>
          <th scope="col"><span class="sr-only">{{ zh ? '选择' : 'Select' }}</span></th><th scope="col">{{ zh ? '模型版本' : 'Model version' }}</th>
          <th scope="col">{{ zh ? '数据与划分' : 'Data and split' }}</th><th scope="col">{{ zh ? '后端 / 精度' : 'Backend / precision' }}</th>
          <th scope="col">{{ zh ? '主指标' : 'Primary metric' }}</th><th scope="col">{{ zh ? '状态' : 'Status' }}</th><th scope="col">{{ zh ? '操作' : 'Actions' }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in pageTasks" :key="row.task_id" :class="{ 'is-selected': selected.includes(row.task_id) }">
            <td><input v-model="selected" type="checkbox" :value="row.task_id" :disabled="row.state !== 'succeeded' || !row.report_object_key || (selected.length >= 4 && !selected.includes(row.task_id))" :aria-label="row.display_name" /></td>
            <td><strong class="evaluation-table__text" :title="taskModelLabel(row)">{{ taskModelLabel(row) }}</strong><small class="evaluation-table__text" :title="row.display_name">{{ row.display_name }}</small></td>
            <td><span class="evaluation-table__text" :title="taskDatasetLabel(row)">{{ taskDatasetLabel(row) }}</span><small>{{ [taskSplit(row), row.report_summary.sample_count == null ? '' : `${row.report_summary.sample_count} ${zh ? '张' : 'images'}`].filter(Boolean).join(' · ') || '—' }}</small></td>
            <td>{{ evaluationRuntime({ task: row, report: {} }) }}</td>
            <td><small>mAP50–95</small><strong>{{ evaluationMetric(row.state === 'succeeded' ? row.map50_95 : null) }}</strong></td>
            <td><StatusBadge v-if="row.state === 'succeeded' && row.report_summary.coverage?.failed" tone="warning" with-dot>{{ zh ? '部分失败' : 'Partially evaluated' }}</StatusBadge><TaskStateBadge v-else :state="row.state" /><small>{{ formatSystemDateTime(row.created_at, 'minutes') }}</small></td>
            <td><RouterLink :to="`/models/detection/evaluation-tasks/${encodeURIComponent(row.task_id)}`">{{ zh ? '查看' : 'View' }}</RouterLink></td>
          </tr>
          <tr v-if="!pageTasks.length"><td colspan="7" role="status">{{ loading ? (zh ? '加载中' : 'Loading') : error ? (zh ? '评估列表读取失败' : 'Could not load evaluations') : tasks.length ? (zh ? '没有符合筛选条件的评估任务' : 'No matching evaluation tasks') : (zh ? '暂无目标检测评估任务' : 'No detection evaluation tasks') }}</td></tr>
        </tbody>
      </table>
    </div>
    <div v-show="!step && (!compareOpen || conflicts.length)" class="evaluation-list-footer">
      <div class="evaluation-toolbar evaluation-selection">
        <span aria-live="polite">{{ zh ? `已选 ${selected.length} 项 · 选择同一数据划分和规则的评估进行比较` : `${selected.length} selected · Compare evaluations that share a split and rules` }}</span>
        <div>
          <Button size="sm" :disabled="!selected.length" @click="selected = []">{{ zh ? '清空' : 'Clear selection' }}</Button>
          <Button class="evaluation-compare-trigger" size="sm" variant="primary" :disabled="selected.length < 2" @click="openComparison">{{ zh ? '比较结果' : 'Compare results' }}</Button>
        </div>
      </div>
      <ModelListPagination :page="taskOffset / taskLimit + 1" :page-size="taskLimit" :item-count="pageTasks.length"
        :total="filteredTasks.length" :zh="zh" :loading="loading" @page="taskOffset = ($event - 1) * taskLimit" @page-size="taskLimit = $event" />
    </div>
    <template v-if="step">
      <div class="evaluation-toolbar"><div><Button :disabled="submitting" @click="closeWizard">{{ zh ? '返回' : 'Back' }}</Button><h2 ref="wizardTitle" tabindex="-1">{{ zh ? '创建评估' : 'Create evaluation' }}</h2></div></div>
      <ol class="evaluation-steps" :aria-label="zh ? '创建评估进度' : 'Evaluation setup progress'">
        <li v-for="(label, index) in wizardSteps" :key="label" :class="{ 'is-complete': step > index + 1 }" :aria-current="step === index + 1 ? 'step' : undefined">
          <span><Check v-if="step > index + 1" :size="16" aria-hidden="true" /><template v-else>{{ index + 1 }}</template></span>{{ label }}
        </li>
      </ol>
      <form class="resource-section evaluation-form" @submit.prevent="advance">
        <template v-if="step === 1">
          <section class="evaluation-form-card">
            <h3>{{ zh ? '模型信息' : 'Model information' }}</h3>
            <div class="evaluation-model-fields">
              <label class="field"><span>{{ zh ? '模型版本' : 'Model version' }}</span><Select v-model="sourceId" floating :aria-label="zh ? '模型版本' : 'Model version'" :options="sourceOptions" :disabled="inputLoading || !sourceOptions.length" /></label>
              <dl v-if="source" class="evaluation-model-facts">
                <div><dt>{{ zh ? '任务类型' : 'Task type' }}</dt><dd>{{ zh ? '目标检测' : 'Detection' }}</dd></div>
                <div><dt>{{ zh ? '模型产物' : 'Model artifact' }}</dt><dd>PyTorch · {{ zh ? '原始模型权重' : 'Original checkpoint' }}</dd></div>
                <div><dt>{{ zh ? '模型系列' : 'Model family' }}</dt><dd>{{ source.model.model_type }}</dd></div>
              </dl>
            </div>
            <p v-if="inputLoading" role="status">{{ zh ? '正在加载模型与导出…' : 'Loading models and exports…' }}</p>
            <template v-else-if="inputError">
              <InlineError :message="inputError" />
              <div><Button size="sm" @click="loadWizardInputs()">{{ zh ? '重新加载' : 'Reload sources' }}</Button></div>
            </template>
            <p v-else-if="!sourceOptions.length" class="evaluation-fact">{{ zh ? '当前项目暂无可用于评估的目标检测模型版本。' : 'This project has no detection model versions available for evaluation.' }}</p>
          </section>
          <section class="evaluation-form-card">
            <h3>{{ zh ? '评估数据' : 'Evaluation data' }}</h3>
            <div class="evaluation-data-fields">
              <label class="field"><span>{{ zh ? '数据集导出' : 'Dataset export' }}</span><Select v-model="exportId" floating :aria-label="zh ? '数据集导出' : 'Dataset export'" :options="exportOptions" :disabled="inputLoading || !exportOptions.length" /></label>
              <label class="field"><span>{{ zh ? '数据划分' : 'Dataset split' }}</span><Select v-model="split" floating :aria-label="zh ? '数据划分' : 'Dataset split'" :options="splits" :disabled="!splits.length" /></label>
              <p v-if="selectedExport" class="evaluation-fact">{{ splits.length === 1 && split === 'val' ? (zh ? '该导出未配置 test，本次使用 val。' : 'This export provides val for evaluation.') : (zh ? '每次评估使用一个数据划分。' : 'Each evaluation uses one split.') }}</p>
            </div>
            <p v-if="!inputLoading && !inputError && !exportOptions.length" class="evaluation-fact">{{ zh ? '请先完成包含 val 或 test 的 COCO 数据集导出。' : 'Create a COCO dataset export containing val or test first.' }}</p>
          </section>
          <section v-if="source && selectedExport" class="evaluation-form-card">
            <h3>{{ zh ? '类别映射' : 'Class mapping' }}</h3>
            <InlineError v-if="classMismatch" :message="zh ? '数据集与模型的类别或顺序不一致。' : 'The dataset and model use different classes or class orders.'" />
            <table v-if="classRows.length" class="evaluation-mapping">
              <thead><tr><th scope="col">ID</th><th scope="col">{{ zh ? '模型类别' : 'Model class' }}</th><th scope="col">{{ zh ? '数据集类别' : 'Dataset class' }}</th></tr></thead>
              <tbody><tr v-for="row in classRows" :key="row.index"><td>{{ row.index }}</td><td>{{ row.model || '—' }}</td><td>{{ row.dataset || '—' }}</td></tr></tbody>
            </table>
            <p v-if="!modelLabels.length" class="evaluation-fact">{{ zh ? '模型类别将从权重对应的标签文件读取，并在提交前核对。' : 'The model labels file is checked before submission.' }}</p>
          </section>
          <section v-if="source" class="evaluation-form-card">
            <h3>{{ zh ? '图像预处理' : 'Image preprocessing' }}</h3>
            <p class="evaluation-fact">{{ preprocessing }}</p>
          </section>
        </template>
        <template v-else-if="step === 2">
          <section class="evaluation-form-card">
            <h3>{{ zh ? '评估指标规则' : 'Evaluation metric rules' }}</h3>
            <dl class="evaluation-facts">
              <div><dt>{{ zh ? '主要指标' : 'Metrics' }}</dt><dd>mAP50–95 · mAP50</dd></div>
              <div><dt>{{ zh ? 'IoU 范围与步长' : 'IoU range and step' }}</dt><dd>0.50–0.95 · 0.05</dd></div>
              <div><dt>{{ zh ? '指标候选最低分' : 'Metric score floor' }}</dt><dd>{{ metricScoreFloor }}</dd></div>
            </dl>
          </section>
          <section class="evaluation-form-card">
            <h3>{{ zh ? '错误样本与 P/R 展示工作点' : 'Sample errors and P/R operating point' }}</h3>
            <div class="evaluation-rule-fields">
              <label class="field"><span>{{ zh ? '置信度阈值' : 'Score threshold' }}</span><input v-model.number="score" type="number" min="0" max="1" step="any" required /></label>
              <dl class="evaluation-facts"><div><dt>{{ zh ? '匹配 IoU' : 'Matching IoU' }}</dt><dd>0.50</dd></div></dl>
            </div>
            <p class="evaluation-fact">{{ zh ? '漏检、误检和工作点的 Precision / Recall 使用此阈值。AP 与完整 PR 曲线使用上方的候选最低分。' : 'Sample errors and operating-point precision and recall use this threshold. AP and the full PR curve use the metric score floor above.' }}</p>
          </section>
          <section class="evaluation-form-card">
            <h3>{{ zh ? '后处理与类别顺序' : 'Postprocessing and class order' }}</h3>
            <div class="evaluation-rule-fields">
              <label v-if="supportsNms" class="field"><span>{{ zh ? 'NMS 阈值' : 'NMS threshold' }}</span><input v-model.number="nms" type="number" min="0" max="1" step="any" :placeholder="zh ? '模型默认' : 'Model default'" /></label>
              <dl class="evaluation-facts"><div><dt>{{ zh ? '类别顺序' : 'Class order' }}</dt><dd>{{ modelLabels.join(' / ') || (zh ? '沿用模型标签文件' : 'From the model labels file') }}</dd></div></dl>
            </div>
          </section>
          <section class="evaluation-form-card">
            <h3>{{ zh ? '结果包' : 'Result package' }}</h3>
            <label class="evaluation-check"><input v-model="saveResultPackage" type="checkbox" />{{ zh ? '保存可下载的评估结果 ZIP' : 'Save a downloadable evaluation ZIP' }}</label>
          </section>
        </template>
        <template v-else>
          <section class="evaluation-form-card">
            <h3>{{ zh ? '评估配置概览' : 'Evaluation summary' }}</h3>
            <dl class="evaluation-facts evaluation-scope">
              <div><dt>{{ zh ? '模型版本' : 'Model version' }}</dt><dd :title="sourceId">{{ source ? modelDisplayName(source.model) : '—' }}<small>{{ source ? modelVersionDisplayName(source.version) : '—' }}</small></dd></div>
              <div><dt>{{ zh ? '数据集与划分' : 'Dataset and split' }}</dt><dd>{{ exportOptions.find(option => option.value === exportId)?.label || exportId }} · {{ split }}</dd></div>
              <div><dt>{{ zh ? '图像数' : 'Images' }}</dt><dd>{{ preview?.sample_count?.toLocaleString() ?? '—' }}</dd></div>
              <div><dt>{{ zh ? '标注对象数（GT）' : 'Ground-truth objects' }}</dt><dd>{{ preview?.annotation_count?.toLocaleString() ?? '—' }}</dd></div>
            </dl>
          </section>
          <section class="evaluation-form-card">
            <h3>{{ zh ? '评估指标设置' : 'Metric settings' }}</h3>
            <dl class="evaluation-facts">
              <div><dt>{{ zh ? '主要指标' : 'Metrics' }}</dt><dd>mAP50–95 · mAP50</dd></div>
              <div><dt>{{ zh ? '置信度阈值' : 'Score threshold' }}</dt><dd>{{ formatThreshold(score) }}</dd></div>
              <div><dt>{{ zh ? '匹配 IoU' : 'Matching IoU' }}</dt><dd>0.50</dd></div>
              <div><dt>{{ zh ? '指标候选最低分' : 'Metric score floor' }}</dt><dd>{{ metricScoreFloor }}</dd></div>
            </dl>
          </section>
          <section class="evaluation-form-card">
            <h3>{{ zh ? '执行设置' : 'Execution settings' }}</h3>
            <dl class="evaluation-facts">
              <div><dt>{{ zh ? '运行时与精度' : 'Runtime and precision' }}</dt><dd>{{ runtimeLabel }}</dd></div>
              <div><dt>{{ zh ? '执行设备' : 'Device' }}</dt><dd>{{ preview?.device_name ?? '—' }}</dd></div>
              <div><dt>{{ zh ? '输入尺寸' : 'Input size' }}</dt><dd>{{ preview?.input_size.join(' × ') ?? '—' }}</dd></div>
              <div><dt>{{ zh ? '批大小' : 'Batch size' }}</dt><dd>1</dd></div>
              <div v-if="supportsNms"><dt>{{ zh ? 'NMS 阈值' : 'NMS threshold' }}</dt><dd>{{ nms === '' ? (zh ? '模型默认' : 'Model default') : formatThreshold(nms) }}</dd></div>
            </dl>
          </section>
          <section class="evaluation-form-card">
            <h3>{{ zh ? '检查项' : 'Preflight checks' }}</h3>
            <p v-if="previewLoading" role="status">{{ zh ? '正在检查评估范围…' : 'Checking evaluation scope…' }}</p>
            <template v-else-if="preview">
              <ul class="evaluation-checks">
                <li><Check :size="16" aria-hidden="true" />{{ zh ? '模型权重可用，执行设置已解析' : 'Checkpoint is available and execution settings are resolved' }}</li>
                <li><Check :size="16" aria-hidden="true" />{{ zh ? '类别顺序一致' : 'Class order matches' }} · {{ preview.category_names.join(' / ') }}</li>
                <li v-if="preview.annotation_count != null"><Check :size="16" aria-hidden="true" />{{ zh ? '所选划分的 COCO 标注文件可读取' : 'The COCO annotation file for this split is readable' }}</li>
              </ul>
            </template>
            <template v-else>
              <InlineError :message="previewError" />
              <div><Button size="sm" @click="retryPreview++">{{ zh ? '重新检查' : 'Retry check' }}</Button></div>
            </template>
            <label class="field evaluation-task-name"><span>{{ zh ? '任务名称（可选）' : 'Task name (optional)' }}</span><input v-model.trim="name" maxlength="128" /></label>
          </section>
        </template>
        <div class="evaluation-toolbar evaluation-form-actions">
          <Button v-if="step > 1" :disabled="submitting" @click="step--">{{ zh ? '上一步' : 'Previous' }}</Button>
          <div class="evaluation-toolbar__end"><Button :disabled="submitting" @click="closeWizard">{{ zh ? '取消' : 'Cancel' }}</Button><Button type="submit" variant="primary" :loading="submitting" :disabled="!valid || (step === 3 && !preview)">{{ step < 3 ? (zh ? '下一步' : 'Next') : (zh ? '提交评估' : 'Submit evaluation') }}</Button></div>
        </div>
      </form>
    </template>
    <DetectionEvaluationComparison v-if="compareOpen && !conflicts.length" :zh="zh" :rows="comparison" :version-names="taskModelNames"
      :baseline="baseline" :error="comparisonError" :loading="comparisonLoading" :datasets="comparisonDatasets"
      @back="closeComparison" @retry="compare" @baseline="baseline = $event" @remove="removeComparisonRow" @samples="openComparisonSamples" />
    <Teleport to="body">
      <ConfirmDialog v-if="compareOpen && conflicts.length" scroll-body size="wide" confirm-variant="primary"
        :title="zh ? '无法直接比较' : 'These evaluations cannot be compared'"
        :message="zh ? '所选结果的评估条件不一致。' : 'The selected results use different evaluation settings.'"
        :confirm-label="zh ? '按相同条件重新评估' : 'Re-evaluate with the same settings'"
        :cancel-label="zh ? '返回选择' : 'Return to selection'" :show-confirm="!!reEvaluation"
        @cancel="closeComparison" @confirm="repeatEvaluation">
        <template #title-icon><span class="comparison-conflict__icon"><TriangleAlert :size="20" aria-hidden="true" /></span></template>
        <div class="comparison-conflict">
          <div class="comparison-conflict__rows">
            <div v-for="(row, index) in comparison" :key="row.task.task_id">
              <header><b>{{ 'ABCD'[index] }}</b>{{ conflictDatasetLabel(row) }}</header>
              <div>
                <strong>{{ taskModelNames.get(row.task.model_version_id) || row.task.display_name }}</strong>
                <dl>
                  <dt>{{ zh ? '任务类型' : 'Task type' }}</dt><dd>{{ zh ? '目标检测' : 'Detection' }} · {{ evaluationRuntime(row) }}</dd>
                  <dt>{{ zh ? '样本范围' : 'Sample scope' }}</dt><dd>{{ comparisonScope(row).split || '—' }} · {{ comparisonScope(row).count ?? '—' }} {{ zh ? '张' : 'images' }}</dd>
                </dl>
              </div>
            </div>
          </div>
          <div class="comparison-conflict__reasons">
            <strong>{{ zh ? '比较条件不一致' : 'Comparison settings differ' }}</strong>
            <ul><li v-for="item in conflicts" :key="item.row.task.task_id">
              {{ resultLabel(0) }} / {{ resultLabel(item.index) }}：
              <ul><li v-for="reason in item.reasons" :key="reason.kind">
                {{ conflictLabel(reason.kind) }}<template v-if="reason.a">：{{ reason.a }} / {{ reason.b }}</template>
              </li></ul>
            </li></ul>
          </div>
        </div>
      </ConfirmDialog>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Check, Plus, RefreshCw, Search, TriangleAlert } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { getDatasetExportDetail, listProjectDatasetExports, type DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import { getDatasetWorkspace, listDatasetRecordPage, listDatasetVersionPage } from '@/modules/datasets/services/dataset-workspace.service'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import ModelListPagination from './ModelListPagination.vue'
import DetectionEvaluationComparison from './DetectionEvaluationComparison.vue'
import { comparisonConflicts, comparisonScope, evaluationMetric, evaluationRuntime, type EvaluationComparisonRow } from '../detection-evaluation-comparison'
import Select from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { modelDisplayName, modelVersionDisplayName, readCatalogVersionNames } from '../model-display-name'
import { formatSmallModelNumber } from '../model-number-format'
import { listDeploymentSourceModels, type DeploymentSourceModelSummary } from '../services/model.service'
import { createDetectionEvaluation, getDetectionEvaluation, getDetectionEvaluationReport, listDetectionEvaluations, previewDetectionEvaluation, type DetectionEvaluationInput, type DetectionEvaluationPreview, type DetectionEvaluationTask } from '../services/model-evaluation.service'

const props = defineProps<{ projectId: string; zh: boolean; canWrite: boolean }>()
const emit = defineEmits<{ focusMode: [active: boolean] }>()
const router = useRouter()
const route = useRoute()
const tasks = ref<DetectionEvaluationTask[]>([])
const filterDataset = ref('')
const filterSplit = ref('')
const filterQuery = ref('')
const taskLimit = ref(20)
const taskOffset = ref(0)
const taskDatasetNames = ref(new Map<string, string>())
const taskModelNames = ref(new Map<string, string>())
const allFilter = computed(() => ({ value: '', label: props.zh ? '全部' : 'All' }))
function datasetIdentity(row: DetectionEvaluationTask): string {
  return row.dataset_version_id || row.dataset_export_id || ''
}
function taskDatasetLabel(row: DetectionEvaluationTask): string {
  const id = datasetIdentity(row)
  return taskDatasetNames.value.get(id) || id || '—'
}
function taskModelLabel(row: DetectionEvaluationTask): string {
  return taskModelNames.value.get(row.model_version_id) || row.model_type || '—'
}
function taskSplit(row: DetectionEvaluationTask): string {
  return row.split_name || row.report_summary.split_name || row.progress.split_name || ''
}
const datasetFilters = computed(() => [allFilter.value, ...Array.from(new Map(tasks.value
  .filter(row => datasetIdentity(row))
  .map(row => [datasetIdentity(row), taskDatasetLabel(row)])), ([value, label]) => ({ value, label }))])
const splitFilters = computed(() => [allFilter.value, ...Array.from(new Set(tasks.value.map(taskSplit).filter(Boolean)), value => ({ value, label: value }))])
const filteredTasks = computed(() => {
  const query = filterQuery.value.toLocaleLowerCase()
  return tasks.value.filter(row => (!filterDataset.value || datasetIdentity(row) === filterDataset.value)
    && (!filterSplit.value || taskSplit(row) === filterSplit.value)
    && (!query || [taskModelLabel(row), row.display_name, row.model_version_id, row.model_type].some(value => value.toLocaleLowerCase().includes(query))))
})
const pageTasks = computed(() => filteredTasks.value.slice(taskOffset.value, taskOffset.value + taskLimit.value))
watch([filterDataset, filterSplit, filterQuery, taskLimit], () => { taskOffset.value = 0 })
watch(() => filteredTasks.value.length, length => {
  taskOffset.value = Math.min(taskOffset.value, Math.max(0, Math.ceil(length / taskLimit.value) - 1) * taskLimit.value)
})
const selected = ref<string[]>([])
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const step = ref(0)
const wizardTitle = ref<HTMLElement | null>(null)
const sourceId = ref('')
const exportId = ref('')
const split = ref<'val' | 'test'>('val')
const score = ref<number | ''>(0.25)
const saveResultPackage = ref(true)
const nms = ref<number | ''>(0.7)
const name = ref('')
const preview = ref<DetectionEvaluationPreview | null>(null)
const previewLoading = ref(false)
const previewError = ref('')
const retryPreview = ref(0)
const inputLoading = ref(false)
const inputError = ref('')
const models = ref<DeploymentSourceModelSummary[]>([])
const datasetExports = ref<DatasetExportSummary[]>([])
const exportLabels = ref(new Map<string, string>())
const wizardSteps = computed(() => props.zh ? ['模型与数据', '评估规则', '检查'] : ['Model and data', 'Evaluation rules', 'Review'])
const sources = computed(() => models.value.filter(model => model.task_type === 'detection')
  .flatMap(model => model.available_versions.filter(version => version.checkpoint_storage_uri && version.checkpoint_state !== 'missing')
    .map(version => ({ model, version }))))
const sourceOptions = computed(() => sources.value.map(({ model, version }) => ({
  value: version.model_version_id, label: `${modelDisplayName(model)} · ${modelVersionDisplayName(version, true)}`,
})))
const source = computed(() => sources.value.find(item => item.version.model_version_id === sourceId.value))
const supportsNms = computed(() => ['yolov8', 'yolo11', 'yolox'].includes(source.value?.model.model_type ?? ''))
const exports = computed(() => datasetExports.value.filter(item => item.task_type === 'detection' && item.format_id === 'coco-detection-v1'
  && item.status === 'completed' && !item.metadata.files_cleaned_at && item.split_names.some(split => ['val', 'test'].includes(split))))
const exportOptions = computed(() => exports.value.map(item => ({
  value: item.dataset_export_id,
  label: exportLabels.value.get(item.dataset_export_id) || item.display_name || item.dataset_id,
  description: formatSystemDateTime(item.created_at, 'minutes'),
})))
const selectedExport = computed(() => exports.value.find(item => item.dataset_export_id === exportId.value))
const splits = computed(() => ['val', 'test'].filter(item => selectedExport.value?.split_names.includes(item)).map(value => ({ value, label: value })))
const modelLabels = computed(() => {
  const labels = source.value?.version.metadata.category_names
  return Array.isArray(labels) && labels.every(label => typeof label === 'string') ? labels as string[] : []
})
const datasetLabels = computed(() => selectedExport.value?.category_names ?? [])
const classRows = computed(() => Array.from({ length: Math.max(modelLabels.value.length, datasetLabels.value.length) },
  (_, index) => ({ index, model: modelLabels.value[index], dataset: datasetLabels.value[index] })))
const classMismatch = computed(() => modelLabels.value.length > 0 && classRows.value.some(row => row.model !== row.dataset))
const preprocessing = computed(() => {
  const value = source.value?.version.metadata.model_input_spec
  if (value && typeof value === 'object' && 'preprocess' in value && typeof value.preprocess === 'string') {
    const spec = value as { preprocess: string; color_space?: string; normalization?: string; spatial_size?: { width?: number; height?: number } }
    const size = spec.spatial_size
    const dimensions = size?.width && size?.height ? `${size.width} × ${size.height}` : ''
    const preprocess = spec.preprocess === 'yolox-top-left-letterbox'
      ? (props.zh ? 'YOLOX Letterbox（左上对齐）' : 'YOLOX Letterbox (top-left)')
      : spec.preprocess
    const normalization = spec.normalization === 'none' ? (props.zh ? '不归一化' : 'No normalization')
      : spec.normalization === 'zero-to-one' ? '0–1' : spec.normalization
    return [[preprocess, dimensions].filter(Boolean).join(' '), spec.color_space, normalization].filter(Boolean).join(' → ')
  }
  if (['yolov8', 'yolo11', 'yolo26'].includes(source.value?.model.model_type ?? '')) {
    return props.zh ? 'Letterbox → RGB → 像素值缩放至 0–1' : 'Letterbox → RGB → Scale pixels to 0–1'
  }
  return props.zh ? '沿用所选模型的推理预处理配置。' : 'Uses the selected model’s inference preprocessing.'
})
const runtimeLabel = computed(() => {
  if (!preview.value) return '—'
  const backend = preview.value.runtime_backend === 'pytorch' ? 'PyTorch' : preview.value.runtime_backend
  return [backend, preview.value.runtime_precision?.toUpperCase()].filter(Boolean).join(' · ')
})
function formatThreshold(value: number | ''): string {
  return typeof value === 'number' ? formatSmallModelNumber(value) : '—'
}
const metricScoreFloor = computed(() => typeof score.value === 'number' ? formatThreshold(Math.min(0.001, score.value)) : '—')
const valid = computed(() => !inputLoading.value && !inputError.value && !!source.value && !!selectedExport.value && !classMismatch.value
  && splits.value.some(option => option.value === split.value))
const compareOpen = ref(false)
const comparison = ref<EvaluationComparisonRow[]>([])
const comparisonDatasets = ref<DatasetExportSummary[]>([])
const comparisonLoading = ref(false)
const comparisonError = ref('')
const baseline = ref('')
const listToolbar = ref<HTMLElement | null>(null)
const conflicts = computed(() => comparisonConflicts(comparison.value))
watch(() => step.value > 0 || (compareOpen.value && !conflicts.value.length), active => emit('focusMode', active))
watch(step, async current => {
  await nextTick()
  const heading = current ? wizardTitle.value : listToolbar.value
  heading?.closest('.workbench-shell__content')?.scrollTo({ top: 0 })
  wizardTitle.value?.focus({ preventScroll: true })
})
onBeforeUnmount(() => emit('focusMode', false))
type EvaluationPrefill = { modelId: string; exportId: string; split: 'val' | 'test' | null; score: number; nms: number | null; saveResultPackage?: boolean }
let wizardPrefill: EvaluationPrefill | undefined
const reEvaluation = computed<EvaluationPrefill | null>(() => {
  const first = comparison.value[0]
  const candidate = conflicts.value[0]?.row
  if (!props.canWrite || !first || !candidate?.task.model_version_id) return null
  const scope = comparisonScope(first)
  if (!scope.exportId || (scope.split !== 'val' && scope.split !== 'test') || scope.score == null) return null
  return { modelId: candidate.task.model_version_id, exportId: scope.exportId, split: scope.split,
    score: scope.score, nms: scope.nms, saveResultPackage: candidate.task.save_result_package }
})
let loadRequest: AbortController | undefined
let compareRequest: AbortController | undefined
let inputRevision = 0

function resultLabel(index: number): string { return props.zh ? `结果 ${'ABCD'[index]}` : `Result ${'ABCD'[index]}` }
function conflictDatasetLabel(row: EvaluationComparisonRow): string {
  const scope = comparisonScope(row)
  const dataset = comparisonDatasets.value.find(item => item.dataset_export_id === scope.exportId)
  if (!dataset?.display_name) return scope.version ?? scope.exportId ?? '—'
  return dataset.version_number == null ? dataset.display_name : `${dataset.display_name} · v${dataset.version_number}`
}
function conflictLabel(kind: 'partial' | 'missing' | 'dataset' | 'samples' | 'rules' | 'classes'): string {
  return (props.zh ? {
    partial: '部分失败报告不能直接比较，请修复数据后重新评估', missing: '报告缺少可用于比较的条件', dataset: '数据集版本或导出不同', samples: '样本范围不同', rules: '评估规则不同', classes: '类别或标注数量不同',
  } : {
    partial: 'Partial reports cannot be compared; repair the data and rerun', missing: 'Report is missing comparison settings', dataset: 'Dataset version or export differs', samples: 'Sample scope differs', rules: 'Evaluation rules differ', classes: 'Classes or annotation counts differ',
  })[kind]
}
function openComparison(): void {
  comparison.value = []
  comparisonDatasets.value = []
  comparisonError.value = ''
  baseline.value = ''
  compareOpen.value = true
}
function closeComparison(): void {
  compareOpen.value = false
  if (route.query.evalCompare) {
    const { evalCompare: _compare, evalBaseline: _baseline, ...query } = route.query
    void router.replace({ query })
  }
  void nextTick(() => listToolbar.value?.parentElement?.querySelector<HTMLElement>('.evaluation-compare-trigger')?.focus())
}
async function openComparisonSamples(id: string): Promise<void> {
  const context = { evalCompare: comparison.value.map(row => row.task.task_id), evalBaseline: baseline.value }
  await router.replace({ query: { ...route.query, ...context } })
  await router.push({ path: `/models/detection/evaluation-tasks/${encodeURIComponent(id)}`, query: { ...context, tab: 'samples' } })
}
function removeComparisonRow(id: string): void {
  if (comparison.value.length <= 2 || baseline.value === id) return
  comparison.value = comparison.value.filter(row => row.task.task_id !== id)
  selected.value = selected.value.filter(value => value !== id)
}
function repeatEvaluation(): void {
  const settings = reEvaluation.value
  if (!settings) return
  closeComparison()
  void openWizard(settings)
}
function closeWizard(): void { if (!submitting.value) { inputRevision++; step.value = 0; error.value = '' } }

async function openWizard(prefill?: EvaluationPrefill): Promise<void> {
  wizardPrefill = prefill
  step.value = 1
  saveResultPackage.value = prefill?.saveResultPackage ?? true
  sourceId.value = ''; exportId.value = ''; name.value = ''
  score.value = prefill?.score ?? 0.25
  nms.value = prefill ? prefill.nms ?? '' : 0.7
  await loadWizardInputs()
}

async function loadWizardInputs(): Promise<void> {
  const project = props.projectId
  if (!project) return
  const prefill = wizardPrefill
  const revision = ++inputRevision
  inputLoading.value = true
  inputError.value = ''
  exportLabels.value = new Map()
  error.value = ''
  try {
    void listDatasetRecordPage('exports', { project_id: project, status: 'completed', limit: 100 }).then(page => {
      if (revision !== inputRevision) return
      exportLabels.value = new Map(page.items.flatMap(item => {
        if (!('dataset_export_id' in item) || !item.display_name) return []
        return [[item.dataset_export_id, item.version_number == null ? item.display_name : `${item.display_name} v${item.version_number}`]]
      }))
    }).catch(() => { /* 导出名称不可读取时显示已有的数据集标识。 */ })
    const [availableModels, availableExports] = await Promise.all([
      listDeploymentSourceModels(project, 'detection'),
      listProjectDatasetExports(project, 'detection', 'completed'),
    ])
    if (revision !== inputRevision) return
    models.value = availableModels; datasetExports.value = availableExports
    if (prefill) {
      const model = sources.value.find(item => item.version.model_version_id === prefill.modelId)
      const dataset = exports.value.find(item => item.dataset_export_id === prefill.exportId && (!prefill.split || item.split_names.includes(prefill.split)))
      if (model) sourceId.value = prefill.modelId
      if (dataset) { exportId.value = prefill.exportId; split.value = prefill.split ?? (dataset.split_names.includes('test') ? 'test' : 'val') }
      if (!model || (prefill.exportId && !dataset)) error.value = props.zh ? '原模型或数据不可用，请重新选择。' : 'The original model or data is unavailable. Choose a replacement.'
    }
  } catch (cause) {
    if (revision === inputRevision) inputError.value = cause instanceof Error ? cause.message : String(cause)
  } finally { if (revision === inputRevision) inputLoading.value = false }
}

async function load(): Promise<void> {
  if (!props.projectId) return
  loadRequest?.abort()
  const request = new AbortController()
  loadRequest = request
  loading.value = true
  error.value = ''
  try {
    const project = props.projectId
    const result = await listDetectionEvaluations(project, request.signal)
    if (!request.signal.aborted) {
      tasks.value = result
      if (filterDataset.value && !datasetFilters.value.some(option => option.value === filterDataset.value)) filterDataset.value = ''
      if (filterSplit.value && !splitFilters.value.some(option => option.value === filterSplit.value)) filterSplit.value = ''
      const available = new Set(result.filter(item => item.state === 'succeeded' && item.report_object_key).map(item => item.task_id))
      selected.value = selected.value.filter(id => available.has(id))
      const comparisonIds = route.query.evalCompare
      if (!compareOpen.value && Array.isArray(comparisonIds) && comparisonIds.length >= 2 && comparisonIds.length <= 4) {
        const restored = [...new Set(comparisonIds.filter((id): id is string => typeof id === 'string' && available.has(id)))]
        if (restored.length === comparisonIds.length) {
          selected.value = restored
          openComparison()
          if (typeof route.query.evalBaseline === 'string' && restored.includes(route.query.evalBaseline)) baseline.value = route.query.evalBaseline
        }
      }
      if (result.length) void loadTaskNames(project, result, request.signal)
    }
  } catch (cause) {
    if (!request.signal.aborted) error.value = cause instanceof Error ? cause.message : String(cause)
  } finally { if (!request.signal.aborted) loading.value = false }
}

async function loadTaskNames(projectId: string, rows: DetectionEvaluationTask[], signal: AbortSignal): Promise<void> {
  const limit = 100
  const missingVersions = new Set(rows.flatMap(row => row.dataset_version_id ? [row.dataset_version_id] : []))
  await Promise.allSettled([
    readCatalogVersionNames(projectId, 'detection', rows.map(row => row.model_version_id), signal).then(names => {
      if (!signal.aborted) taskModelNames.value = names
    }),
    (async () => {
      const names = new Map<string, string>()
      for (let offset = 0; missingVersions.size; offset += limit) {
        const page = await listDatasetVersionPage({ project_id: projectId, task_type: 'detection', offset, limit }, signal)
        if (signal.aborted) return
        for (const version of page.items) {
          if (missingVersions.delete(version.dataset_version_id)) names.set(version.dataset_version_id, `${version.display_name} · v${version.version_number}`)
        }
        if (!page.items.length || offset + limit >= page.total) break
      }
      taskDatasetNames.value = names
    })(),
  ])
}

async function advance(): Promise<void> {
  const body = evaluationInput()
  if (!body || !valid.value || submitting.value || !props.canWrite) return
  if (step.value < 3) { step.value++; return }
  if (!preview.value) return
  submitting.value = true
  error.value = ''
  const project = props.projectId
  try {
    const result = await createDetectionEvaluation(body)
    if (project === props.projectId) await router.push(`/models/detection/evaluation-tasks/${encodeURIComponent(result.task_id)}`)
  } catch (cause) { if (project === props.projectId) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { submitting.value = false }
}

function evaluationInput(): DetectionEvaluationInput | null {
  const model = source.value?.model
  if (!model || typeof score.value !== 'number' || score.value < 0 || score.value > 1) return null
  return {
    project_id: props.projectId, model_type: model.model_type, model_version_id: sourceId.value,
    dataset_export_id: exportId.value, score_threshold: score.value,
    nms_threshold: supportsNms.value && nms.value !== '' ? nms.value : undefined, extra_options: { split: split.value }, display_name: name.value,
    save_result_package: saveResultPackage.value,
  }
}

async function compare(): Promise<void> {
  compareRequest?.abort()
  const request = new AbortController()
  compareRequest = request
  comparisonLoading.value = true
  comparisonError.value = ''
  comparison.value = []
  try {
    const rows = tasks.value.filter(task => selected.value.includes(task.task_id) && task.state === 'succeeded' && task.report_object_key)
    if (rows.length < 2) throw new Error(props.zh ? '请选择至少两项可用的评估结果。' : 'Select at least two available evaluation results.')
    const reports = await Promise.all(rows.map(task => getDetectionEvaluationReport(task.task_id, request.signal)))
    if (request.signal.aborted) return
    if (reports.some(report => report.file_status !== 'ready')) throw new Error(props.zh ? '存在尚不可用的评估报告。' : 'One or more evaluation reports are unavailable.')
    const results = reports.map((report, index) => ({ task: rows[index], report: report.payload }))
    const exportIds = [...new Set(results.map(row => comparisonScope(row).exportId).filter((id): id is string => !!id))]
    const datasets = await Promise.all(exportIds.map(async id => {
      const info = await getDatasetExportDetail(id, request.signal).catch(() => null)
      if (!info || info.project_id !== props.projectId) return null
      if (info.display_name && info.version_number != null) return info
      const version = await getDatasetWorkspace(info.dataset_id, info.dataset_version_id, request.signal).catch(() => null)
      return version ? { ...info, display_name: version.dataset.display_name, version_number: version.version_number } : info
    }))
    if (request.signal.aborted) return
    comparisonDatasets.value = datasets.filter(dataset => dataset != null)
    comparison.value = results
    if (!rows.some(row => row.task_id === baseline.value)) baseline.value = rows[0]?.task_id || ''
  } catch (cause) { if (!request.signal.aborted) comparisonError.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (!request.signal.aborted) comparisonLoading.value = false }
}

watch([() => route.query.retry, () => props.projectId, () => props.canWrite], async ([id, projectId, canWrite], _, onCleanup) => {
  if (typeof id !== 'string' || !projectId || !canWrite) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  try {
    const data = await getDetectionEvaluation(id, controller.signal)
    if (controller.signal.aborted) return
    if (data.project_id !== projectId) {
      error.value = props.zh ? '无法恢复其他项目的评估设置。' : 'Evaluation settings belong to a different project.'
      return
    }
    const snapshot = data.state === 'succeeded' && data.report_object_key
      ? await getDetectionEvaluationReport(id, controller.signal).catch(() => null)
      : null
    if (controller.signal.aborted) return
    const savedReport = snapshot?.file_status === 'ready' ? snapshot.payload : {}
    const scope = comparisonScope({ task: data, report: savedReport })
    const splitName = savedReport.split_name || data.task_spec?.extra_options?.split || data.progress.split_name || scope.split
    const configuredSplit = splitName === 'val' || splitName === 'test' ? splitName : null
    if (!scope.exportId || (splitName && !configuredSplit)) {
      error.value = props.zh ? '无法恢复原评估的设置，请重新选择。' : 'The original settings are unavailable. Select new settings.'
      return
    }
    const yolo = ['yolov8', 'yolo11', 'yolo26'].includes(data.model_type)
    void openWizard({ modelId: data.model_version_id, exportId: scope.exportId, split: configuredSplit,
      score: scope.score ?? (yolo ? 0.001 : 0.01), nms: data.model_type === 'yolo26' ? null : scope.nms ?? (yolo ? 0.7 : 0.65),
      saveResultPackage: data.save_result_package })
  } catch (cause) {
    if (!controller.signal.aborted) error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (!controller.signal.aborted && route.query.retry === id) {
      const { retry: _retry, ...query } = route.query
      void router.replace({ query })
    }
  }
}, { immediate: true })
watch(compareOpen, open => { if (open) void compare(); else compareRequest?.abort() })
watch([step, retryPreview, () => props.projectId], async ([currentStep], _, onCleanup) => {
  preview.value = null
  previewError.value = ''
  previewLoading.value = false
  if (currentStep !== 3) return
  const body = evaluationInput()
  if (!body) return
  const request = new AbortController()
  onCleanup(() => request.abort())
  previewLoading.value = true
  error.value = ''
  try {
    const result = await previewDetectionEvaluation(body, request.signal)
    if (!request.signal.aborted) preview.value = result
  } catch (cause) { if (!request.signal.aborted) previewError.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (!request.signal.aborted) previewLoading.value = false }
})
watch(splits, options => { if (!options.some(item => item.value === split.value)) split.value = options[0]?.value === 'test' ? 'test' : 'val' })
watch(() => props.projectId, () => {
  inputRevision++
  tasks.value = []; selected.value = []; compareOpen.value = false; step.value = 0
  filterDataset.value = ''; filterSplit.value = ''; filterQuery.value = ''; taskOffset.value = 0
  taskDatasetNames.value = new Map(); taskModelNames.value = new Map()
  sourceId.value = ''; exportId.value = ''; models.value = []; datasetExports.value = []; void load()
}, { immediate: true })
watch([() => route.query.evaluationFrom, () => route.query.datasetFrom, () => props.projectId, () => props.canWrite],
  async ([modelId, datasetId, projectId, canWrite]) => {
    if (typeof modelId !== 'string' || !modelId || !projectId || !canWrite) return
    await openWizard({ modelId, exportId: typeof datasetId === 'string' ? datasetId : '', split: null, score: 0.25, nms: 0.7 })
    if (route.query.evaluationFrom === modelId && props.projectId === projectId) {
      const { evaluationFrom: _model, datasetFrom: _dataset, ...query } = route.query
      void router.replace({ query })
    }
  }, { immediate: true })
onBeforeUnmount(() => { inputRevision++; loadRequest?.abort(); compareRequest?.abort() })
</script>

<style scoped>
.evaluation-panel, .evaluation-form { display:grid; gap:14px; min-width:0; }
.evaluation-toolbar, .evaluation-toolbar > div { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.evaluation-toolbar { justify-content:space-between; }
.evaluation-toolbar h2,.evaluation-form :is(h3,p) { margin:0; }
.evaluation-toolbar__end { margin-inline-start:auto; }
.evaluation-list-tools,.evaluation-list-footer { display:grid; gap:12px; min-width:0; }
.evaluation-list-filters { display:grid; grid-template-columns: minmax(0,180px) minmax(0,320px) minmax(0,150px); gap:12px; }
.evaluation-list-filters .field { margin:0; min-width:0; }
.evaluation-list-search { display:flex; align-items:center; gap:8px; padding:0 12px; border:1px solid var(--am-border); border-radius:var(--am-radius-md); background:var(--am-surface); color:var(--am-text-muted); }
.evaluation-list-search input { width:100%; min-width:0; min-height:36px; border:0; background:none; color:var(--am-text); }
.evaluation-list-search:focus-within { outline:1px solid var(--am-brand-primary); }
.evaluation-selection { padding:10px 12px; border-radius:var(--am-radius-md); background:var(--am-success-surface); }
.evaluation-table { overflow:auto; }
.evaluation-table table { width:100%; table-layout:fixed; }
.evaluation-table :is(td,th) { overflow-wrap:anywhere; }
.evaluation-table td { padding-block:9px; }
.evaluation-table .evaluation-table__text { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.evaluation-table th:first-child { width:42px; }
.evaluation-table th:nth-child(2) { width:25%; }
.evaluation-table th:nth-child(3) { width:23%; }
.evaluation-table th:last-child { width:9%; }
.evaluation-table .is-selected { background:var(--am-success-surface); }
.evaluation-table input { accent-color:var(--am-brand-primary); }
.evaluation-table small { display:block; color:var(--am-text-muted); }
.evaluation-table a { color:var(--am-brand-primary); }
.evaluation-steps { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); margin:0; padding:0; list-style:none; }
.evaluation-steps li { display:flex; align-items:center; gap:10px; color:var(--am-text-muted); }
.evaluation-steps li:not(:last-child)::after { content:''; flex:1; height:1px; margin-inline-end:12px; background:var(--am-border); }
.evaluation-steps span { display:grid; place-items:center; flex:none; width:32px; height:32px; border:1px solid var(--am-border); border-radius:50%; }
.evaluation-steps .is-complete span { color:var(--am-brand-primary); border-color:currentColor; }
.evaluation-steps .is-complete:not(:last-child)::after { background:var(--am-brand-primary); }
.evaluation-steps [aria-current] { color:var(--am-text-strong); font-weight:600; }
.evaluation-steps [aria-current] span { background:var(--am-brand-primary); color:var(--am-brand-on-primary); }
.evaluation-form.resource-section { padding:0; border:0; background:transparent; }
.evaluation-form-card { display:grid; gap:10px; min-width:0; padding:12px 16px; border:1px solid var(--am-border); border-radius:8px; background:var(--am-surface); }
.evaluation-form-card h3 { font-size:var(--am-type-section); }
.evaluation-form .field { gap:5px; min-width:0; margin:0; }
.evaluation-model-fields, .evaluation-data-fields, .evaluation-rule-fields { display:grid; gap:12px; align-items:end; }
.evaluation-model-fields { grid-template-columns:minmax(0,1fr) minmax(0,1.65fr); }
.evaluation-model-fields > .field:only-child { grid-column:1 / -1; max-width:480px; }
.evaluation-data-fields { grid-template-columns:minmax(0,1.2fr) minmax(0,.6fr) minmax(0,1fr); }
.evaluation-rule-fields { grid-template-columns:repeat(2,minmax(0,1fr)); max-width:720px; }
.evaluation-model-facts, .evaluation-facts { display:grid; grid-auto-columns:minmax(0,1fr); grid-auto-flow:column; gap:10px; margin:0; }
.evaluation-model-facts dt, .evaluation-facts dt { color:var(--am-text-muted); margin-block-end:5px; }
.evaluation-model-facts dd, .evaluation-facts dd { margin:0; padding:7px 9px; border-radius:5px; background:var(--am-surface-muted); overflow-wrap:anywhere; }
.evaluation-scope { grid-template-columns:repeat(2,minmax(0,1.75fr)) repeat(2,minmax(0,1fr)); }
.evaluation-scope small { display:block; margin-block-start:4px; color:var(--am-text-muted); }
.evaluation-fact { padding:8px 10px; border-radius:5px; background:var(--am-surface-muted); color:var(--am-text-muted); overflow-wrap:anywhere; }
.evaluation-mapping { width:100%; border-collapse:collapse; table-layout:fixed; }
.evaluation-mapping :is(th, td) { padding:5px 9px; border-block-end:1px solid var(--am-border); text-align:start; overflow-wrap:anywhere; }
.evaluation-mapping th { background:var(--am-surface-muted); color:var(--am-text-muted); }
.evaluation-mapping th:first-child { width:13%; }
.evaluation-mapping tbody tr:last-child td { border:0; }
.evaluation-check { display:flex; align-items:center; gap:8px; }
.evaluation-check input { accent-color:var(--am-brand-primary); }
.evaluation-checks { display:grid; gap:7px; margin:0; padding:0; list-style:none; }
.evaluation-checks li { display:flex; align-items:flex-start; gap:8px; overflow-wrap:anywhere; }
.evaluation-checks svg { flex:none; color:var(--am-brand-primary); }
.evaluation-task-name { max-width:360px; scroll-margin-block-end:56px; }
.evaluation-form-actions { position:sticky; bottom:0; z-index:1; justify-content:flex-end; padding-block:8px; background:var(--am-page); }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }
.comparison-conflict__icon { display:inline-grid; vertical-align:middle; place-items:center; width:32px; height:32px; margin-inline-end:8px; border-radius:50%; background:var(--am-warning-surface); color:var(--am-warning-text); }
.comparison-conflict { display:grid; gap:14px; min-width:0; overflow-wrap:anywhere; }
.comparison-conflict__rows { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.comparison-conflict__rows > div { border:1px solid var(--am-border); border-radius:6px; overflow:hidden; }
.comparison-conflict__rows header { display:flex; align-items:center; gap:10px; padding:10px 12px; background:var(--am-surface-muted); }
.comparison-conflict__rows header b { display:grid; flex:none; place-items:center; width:24px; height:24px; border-radius:50%; background:var(--am-surface-soft); }
.comparison-conflict__rows > div > div { padding:12px; }
.comparison-conflict__rows dl { display:grid; grid-template-columns:auto minmax(0,1fr); gap:6px 12px; margin:8px 0 0; font-size:var(--am-type-caption); }
.comparison-conflict__rows dt { color:var(--am-text-muted); }
.comparison-conflict__rows dd { margin:0; }
.comparison-conflict__reasons { padding:12px; border:1px solid var(--am-warning-border); background:var(--am-warning-surface); border-radius:6px; }
.comparison-conflict__reasons > strong { color:var(--am-warning-text); }
.comparison-conflict__reasons ul { margin:6px 0 0; padding-inline-start:22px; }
@media (max-width:700px) {
  .evaluation-model-fields, .evaluation-data-fields, .comparison-conflict__rows { grid-template-columns:minmax(0,1fr); }
  .evaluation-facts { grid-template-columns:repeat(2,minmax(0,1fr)); grid-auto-flow:row; }
}
</style>
