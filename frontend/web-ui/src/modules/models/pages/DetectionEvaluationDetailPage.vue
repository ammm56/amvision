<template>
  <section class="page-stack evaluation-detail model-workspace">
    <DetectionEvaluationSampleViewer v-if="sample && report" :task-id="taskId" :sample="sample" :objects="activeExample ? sampleBoxes(sample, activeExample.issue) : sampleBoxes(sample)"
      :position="activeExample ? exampleRows.indexOf(activeExample) + 1 : sampleOffset + samples.findIndex(item => item.image_index === sample?.image_index) + 1"
      :total="activeExample ? exampleRows.length : sampleTotal"
      :split="report.split_name" :score-threshold="report.score_threshold" :diagnostics-available="!!activeExample || diagnosticsAvailable === true"
      :navigating="sampleLoading" :navigation-error="sampleError" :zh="zh" @close="closeSample" @navigate="navigateSample" />
    <template v-else>
    <DetectionEvaluationRunStatus v-if="task && (active || task.state === 'cancelled')" :key="task.task_id" :task="task" :zh="zh"
      :can-retry="canRetryEvaluation" :can-cancel="canWrite" :refreshing="loading" :error="cancelError || error" :dataset-version-name="datasetVersionName" @refresh="load" @cancel="confirmCancel = true" />
    <template v-else>
    <div class="evaluation-toolbar">
      <div><RouterLink :to="evaluationReturn">{{ route.query.evalCompare ? (zh ? '返回评估比较' : 'Back to comparison') : (zh ? '返回评估' : 'Back to evaluations') }}</RouterLink><h1>{{ task?.display_name || (zh ? '评估详情' : 'Evaluation details') }}</h1><StatusBadge v-if="partial" tone="warning" with-dot>{{ zh ? '部分失败' : 'Partially evaluated' }}</StatusBadge><TaskStateBadge v-else-if="task" :state="task.state" /></div>
      <div>
        <RouterLink v-if="(partial || failed) && canRetryEvaluation" class="evaluation-rerun" :to="{ path: '/models', query: { tab: 'evaluation', retry: taskId } }">
          {{ partial ? (zh ? '修复数据后重新评估' : 'Run again after fixing data') : (zh ? '使用原配置重新评估' : 'Re-evaluate with original settings') }}
        </RouterLink>
        <Button v-if="report" variant="primary" @click="downloadEvaluationJson(`${taskId}-report.json`, report)"><Download :size="16" />{{ partial ? (zh ? '下载部分报告' : 'Download partial report') : (zh ? '下载报告' : 'Download report') }}</Button>
        <Button :loading="loading" @click="load">{{ zh ? '刷新' : 'Refresh' }}</Button>
      </div>
    </div>
    <InlineError :message="error" />
    <template v-if="task">
      <div class="resource-section evaluation-summary">
        <dl>
          <div><dt>{{ zh ? '模型版本' : 'Model version' }}</dt><dd>{{ modelVersionName || task.model_type || '—' }}</dd></div>
          <div><dt>{{ zh ? '数据版本' : 'Dataset version' }}</dt><dd :title="task.dataset_version_id">{{ datasetVersionName || '—' }}</dd></div>
          <div><dt>{{ zh ? '评估划分' : 'Split' }}</dt><dd>{{ report?.split_name || task.report_summary.split_name || '—' }}<template v-if="report?.sample_count != null"> · {{ report.sample_count }} {{ zh ? '张' : 'images' }}</template></dd></div>
          <div v-if="report"><dt>{{ zh ? '运行时' : 'Runtime' }}</dt><dd>{{ evaluationRuntime({ task, report }) }}</dd></div>
        </dl>
        <p v-if="task.error_message" role="alert">{{ task.error_message }}</p>
      </div>
      <div v-if="partial && coverage" class="evaluation-coverage__notice" role="status">
          <TriangleAlert :size="20" aria-hidden="true" />
          <div><h2 id="evaluation-coverage-title">{{ zh ? '仅部分样本完成评估' : 'Only some samples were evaluated' }}</h2>
          <p>{{ zh ? `以下指标基于 ${coverage.requested} 张中的 ${coverage.succeeded} 张成功样本，不能与完整报告直接比较。` : `Metrics cover ${coverage.succeeded} of ${coverage.requested} images and cannot be compared directly with a full report.` }}</p></div>
      </div>
      <section v-if="partial && coverage" class="resource-section evaluation-coverage" :aria-label="zh ? '部分评估摘要' : 'Partial evaluation summary'">
        <div class="evaluation-metrics evaluation-metrics--subset">
          <div v-for="item in metrics.slice(0, 2)" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
        </div>
        <ol class="evaluation-coverage__steps">
          <li><CircleCheck :size="18" aria-hidden="true" /><strong>{{ zh ? '准备数据' : 'Prepare data' }}</strong><span>{{ zh ? `${coverage.requested} 张待评估` : `${coverage.requested} requested` }}</span></li>
          <li><CircleAlert :size="18" aria-hidden="true" /><strong>{{ zh ? '执行评估' : 'Evaluate' }}</strong><span class="evaluation-coverage__warning">{{ zh ? `${coverage.failed} 张失败` : `${coverage.failed} failed` }}</span></li>
          <li><CircleCheck :size="18" aria-hidden="true" /><strong>{{ zh ? '汇总报告' : 'Generate report' }}</strong><span>{{ zh ? '已完成' : 'Completed' }}</span></li>
        </ol>
        <dl class="evaluation-coverage__counts">
          <div><dt>{{ zh ? '成功' : 'Succeeded' }}</dt><dd class="evaluation-coverage__success">{{ coverage.succeeded }}</dd></div>
          <div><dt>{{ zh ? '失败' : 'Failed' }}</dt><dd class="evaluation-coverage__failed">{{ coverage.failed }}</dd></div>
          <div><dt>{{ zh ? '未处理' : 'Unprocessed' }}</dt><dd>{{ coverage.unprocessed }}</dd></div>
        </dl>
      </section>
      <div v-if="report" class="resource-section evaluation-report">
        <div v-if="!partial && tab !== 'conditions'" class="evaluation-metrics">
          <div v-for="item in metrics" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
        </div>
        <TabList v-model="tab" :tabs="tabs" :label="zh ? '评估报告' : 'Evaluation report'" />
        <section v-if="tab === 'failures' && partial" class="evaluation-section">
          <h2>{{ zh ? '失败样本' : 'Failed samples' }}</h2>
          <div class="resource-table evaluation-failures"><table>
            <thead><tr><th scope="col">{{ zh ? '序号' : 'No.' }}</th><th scope="col">{{ zh ? '文件名' : 'Filename' }}</th><th scope="col">{{ zh ? '类别' : 'Classes' }}</th><th scope="col">{{ zh ? '状态' : 'Status' }}</th><th scope="col">{{ zh ? '失败原因' : 'Failure reason' }}</th><th scope="col">{{ zh ? '操作' : 'Actions' }}</th></tr></thead>
            <tbody><tr v-for="row in report.failed_samples" :key="row.image_index">
              <td>{{ row.image_index + 1 }}</td><td>{{ row.name || '—' }}</td><td>{{ row.classes.join('、') || '—' }}</td>
              <td><StatusBadge tone="danger" with-dot>{{ zh ? '失败' : 'Failed' }}</StatusBadge></td><td>{{ failureLabel(row.reason) }}</td>
              <td><div class="evaluation-failure-actions"><Button size="sm" @click="selectedFailurePreview = row">{{ zh ? '查看样本' : 'View sample' }}</Button><Button size="sm" @click="selectedFailure = row">{{ zh ? '查看错误' : 'View error' }}</Button></div></td>
            </tr></tbody>
          </table></div>
          <p class="evaluation-failures__note">{{ zh ? '失败样本未计入评估指标。' : 'Failed images are excluded from the metrics.' }}</p>
        </section>
        <section v-else-if="tab === 'log'" class="evaluation-section">
          <h2>{{ zh ? '处理日志' : 'Processing log' }}</h2>
          <TaskEventTimeline v-if="evaluationEvents.length" :events="evaluationEvents" compact />
          <p v-else>{{ zh ? '暂无处理日志。' : 'No processing events were saved.' }}</p>
        </section>
        <section v-else-if="tab === 'overview'" class="evaluation-section">
          <h2>{{ zh ? '评估概览' : 'Evaluation overview' }}</h2>
          <div class="evaluation-overview">
            <section>
              <h3>{{ zh ? '样本与对象' : 'Samples and objects' }}</h3>
              <dl>
                <div><dt>{{ zh ? '样本数' : 'Samples' }}</dt><dd>{{ report.sample_count?.toLocaleString(locale) ?? '—' }}</dd></div>
                <div><dt>{{ zh ? '标注对象' : 'Ground truth' }}</dt><dd>{{ report.ground_truth_count?.toLocaleString(locale) ?? '—' }}</dd></div>
                <div><dt>{{ zh ? '预测对象' : 'Predictions' }}</dt><dd>{{ report.prediction_count?.toLocaleString(locale) ?? '—' }}</dd></div>
              </dl>
            </section>
            <section>
              <h3>{{ zh ? '问题样本' : 'Samples with errors' }}</h3>
              <dl>
                <div><dt>{{ zh ? '有漏检的样本' : 'Samples with missed objects' }}</dt><dd>{{ report.samples_with_false_negatives?.toLocaleString(locale) ?? '—' }}</dd></div>
                <div><dt>{{ zh ? '有误检的样本' : 'Samples with false positives' }}</dt><dd>{{ report.samples_with_false_positives?.toLocaleString(locale) ?? '—' }}</dd></div>
              </dl>
            </section>
          </div>
        </section>
        <section v-else-if="tab === 'class'" class="evaluation-section">
          <h2>{{ zh ? '按类别' : 'By class' }}</h2>
          <div class="resource-table evaluation-classes"><table>
            <thead><tr><th scope="col">{{ zh ? '类别' : 'Class' }}</th><th scope="col">{{ zh ? 'GT 对象数' : 'GT objects' }}</th><th scope="col">AP50–95</th></tr></thead>
            <tbody>
              <tr v-for="row in report.per_class_metrics" :key="row.class_id"><th scope="row">{{ row.class_name }}</th><td>{{ row.gt_count.toLocaleString(locale) }}</td><td>{{ row.gt_count > 0 ? metric(row.ap50_95) : '—' }}</td></tr>
              <tr v-if="!classTotals"><td colspan="3">{{ zh ? '报告没有类别指标' : 'The report has no per-class metrics' }}</td></tr>
            </tbody>
            <tfoot v-if="classTotals"><tr><th scope="row">{{ zh ? '合计 / 均值' : 'Total / mean' }}</th><td>{{ classTotals.gt.toLocaleString(locale) }}</td><td>{{ zh ? '均值' : 'Mean' }} {{ metric(classTotals.mean) }}</td></tr></tfoot>
          </table></div>
          <p v-if="classTotals" class="evaluation-sample-summary"><Info :size="15" aria-hidden="true" />{{ zh ? 'GT 对象数以标注对象为单位。AP 均值按包含标注对象的类别等权计算。' : 'GT counts annotated objects. Mean AP gives equal weight to classes with ground-truth objects.' }}</p>
          <section class="evaluation-examples">
            <div class="evaluation-toolbar">
              <h3>{{ zh ? '错误样本示例' : 'Sample error examples' }}</h3>
              <div class="evaluation-legend"><span><i class="is-truth" aria-hidden="true" />{{ zh ? 'GT（真实框）' : 'Ground truth' }}</span><span><i aria-hidden="true" />{{ zh ? '预测框' : 'Prediction' }}</span></div>
            </div>
            <div v-if="examplesError" class="evaluation-sample-error"><InlineError :message="examplesError" /><Button size="sm" @click="exampleRevision++">{{ zh ? '重试' : 'Retry' }}</Button></div>
            <p v-else-if="examplesLoading" role="status">{{ zh ? '正在读取示例…' : 'Loading examples…' }}</p>
            <p v-else-if="!exampleRows.length" role="status">{{ exampleDiagnostics ? (zh ? '本次评估没有记录漏检或误检样本。' : 'No missed or false detections were recorded.') : (zh ? '此报告未保存样本级错误记录。' : 'This report has no per-sample diagnostics.') }}</p>
            <div v-else ref="exampleList" class="evaluation-example-grid">
              <article v-for="(entry, index) in exampleRows" :key="entry.issue" class="evaluation-example">
                <StatusBadge :tone="entry.issue === 'false_negatives' ? 'danger' : entry.issue === 'false_positives' ? 'warning' : 'neutral'">{{ sampleErrorType(entry.issue) }}</StatusBadge>
                <div class="evaluation-example__body">
                  <DetectionSampleThumbnail :task-id="taskId" :index="entry.row.image_index" :boxes="sampleBoxes(entry.row, entry.issue)" />
                  <dl><dt>{{ zh ? '文件名' : 'File' }}</dt><dd :title="entry.row.name">{{ entry.row.name }}</dd>
                    <dt>{{ zh ? '类别' : 'Class' }}</dt><dd>{{ [...new Set(sampleBoxes(entry.row, entry.issue).map(({ box }) => box.class_name))].join(' / ') || '—' }}</dd>
                    <dt>GT / {{ zh ? '预测' : 'Predictions' }}</dt><dd>{{ entry.row.gt_count }} / {{ entry.row.pred_count }}</dd>
                    <template v-if="entry.row.localization_pair"><dt>IoU</dt><dd>{{ metric(entry.row.localization_pair.iou) }}</dd></template>
                  </dl>
                </div>
                <Button size="sm" :data-example-index="index" @click="openExample(index)">{{ zh ? '查看样本' : 'View sample' }}</Button>
              </article>
            </div>
          </section>
        </section>
        <section v-else-if="tab === 'curves'" class="evaluation-section">
          <DetectionEvaluationCurves v-if="report.curves" :data="report.curves" :task-id="taskId" :zh="zh" />
          <p v-else role="status">{{ zh ? '此报告没有曲线数据。重新评估可生成曲线和混淆矩阵。' : 'Run a new evaluation to generate curves and the confusion matrix.' }}</p>
        </section>
        <section v-else-if="tab === 'samples'" class="evaluation-section">
          <div class="evaluation-toolbar">
            <h2>{{ zh ? '错误样本' : 'Sample errors' }}</h2>
            <Button v-if="diagnosticsAvailable" size="sm" @click="resetFilters('errors')">{{ zh ? '查看全部问题样本' : 'Show all problem samples' }}</Button>
          </div>
          <div class="evaluation-filters">
            <label><span>{{ zh ? '文件名' : 'File name' }}</span><input v-model="searchText" type="search" maxlength="255" :placeholder="zh ? '搜索文件名' : 'Search by file name'" /></label>
            <div><span>{{ zh ? '类别' : 'Class' }}</span><Select v-model="className" :options="classOptions" :aria-label="zh ? '样本类别' : 'Sample class'" /></div>
            <div><span>{{ zh ? '错误类型' : 'Issue' }}</span><Select v-model="issue" :options="issueOptions" :aria-label="zh ? '样本筛选' : 'Sample filter'" /></div>
            <Button size="sm" @click="resetFilters(diagnosticsAvailable ? 'errors' : 'all')">{{ zh ? '清除筛选' : 'Clear filters' }}</Button>
          </div>
          <div class="evaluation-sample-summary">
            <span v-if="!sampleLoading && !sampleError" role="status">{{ zh ? `符合条件 ${sampleTotal} 张 / 评估 ${report.sample_count ?? '—'} 张` : `${sampleTotal} matching / ${report.sample_count ?? '—'} evaluated` }}</span>
            <span v-if="diagnosticsAvailable">{{ zh ? '匹配规则：同类别且 IoU ≥ 0.50' : 'Match: same class and IoU ≥ 0.50' }}<template v-if="report.score_threshold != null"> · {{ zh ? '置信度阈值' : 'Score threshold' }} {{ formatModelNumber(report.score_threshold, 4) }}</template></span>
            <span v-if="diagnosticsAvailable" class="evaluation-legend"><span><i class="is-truth" aria-hidden="true" />{{ zh ? 'GT（真实框）' : 'Ground truth' }}</span><span><i aria-hidden="true" />{{ zh ? '预测框' : 'Prediction' }}</span></span>
          </div>
          <p v-if="diagnosticsAvailable === false" class="evaluation-sample-summary">{{ zh ? '此报告未保存样本级错误记录，可查看原图和已有对象数量。' : 'This report has no per-sample diagnostics. Original images and available counts are still shown.' }}</p>
          <div v-if="sampleError" class="evaluation-sample-error"><InlineError :message="sampleError" /><Button size="sm" @click="loadSamplePage(failedSampleOffset)">{{ zh ? '重试读取样本' : 'Retry loading samples' }}</Button></div>
          <div class="evaluation-samples">
            <div :aria-busy="sampleLoading">
              <div v-if="samples.length" ref="sampleTable" class="resource-table evaluation-sample-table">
                <table>
                  <thead><tr><th scope="col">#</th><th scope="col">{{ zh ? '图像缩略图' : 'Thumbnail' }}</th><th scope="col">{{ zh ? '文件名' : 'File' }}</th><th scope="col">{{ zh ? '类别' : 'Class' }}</th><th scope="col">{{ zh ? '问题' : 'Issue' }}</th><th scope="col">{{ zh ? 'GT 数量' : 'GT count' }}</th><th scope="col">{{ zh ? '预测数量' : 'Prediction count' }}</th><th scope="col">{{ zh ? '操作' : 'Action' }}</th></tr></thead>
                  <tbody><tr v-for="(item, index) in samples" :key="item.image_index">
                    <td>{{ sampleOffset + index + 1 }}</td>
                    <td><DetectionSampleThumbnail :task-id="taskId" :index="item.image_index" :boxes="sampleBoxes(item)" /></td>
                    <th scope="row"><span :title="item.name">{{ item.name }}</span></th>
                    <td><span :title="sampleClasses(item)">{{ sampleClasses(item) }}</span></td>
                    <td>{{ sampleIssue(item) }}</td><td>{{ item.gt_count }}</td><td>{{ item.pred_count }}</td>
                    <td><Button size="sm" variant="ghost" class="ui-button--row-view" :data-sample-index="item.image_index" :aria-label="(zh ? '查看 ' : 'View ') + item.name" @click="sample = item">{{ zh ? '查看' : 'View' }}</Button></td>
                  </tr></tbody>
                </table>
              </div>
              <p v-if="!samples.length && !sampleError" role="status">{{ sampleLoading ? (zh ? '加载中' : 'Loading') : (zh ? '没有符合条件的样本' : 'No matching samples') }}</p>
              <div v-if="sampleTotal > pageSize" class="evaluation-pagination">
                <Button size="sm" :disabled="sampleOffset === 0 || sampleLoading" @click="loadSamplePage(sampleOffset - pageSize)">{{ zh ? '上一页' : 'Previous' }}</Button>
                <Button size="sm" :disabled="sampleOffset + pageSize >= sampleTotal || sampleLoading" @click="loadSamplePage(sampleOffset + pageSize)">{{ zh ? '下一页' : 'Next' }}</Button>
              </div>
            </div>
          </div>
        </section>
        <section v-else class="evaluation-section">
          <DetectionEvaluationConditions :task="task" :report="report" :can-retry="canRetryEvaluation" :zh="zh" :dataset-version-name="datasetVersionName" />
        </section>
      </div>
      <p v-else-if="task.state === 'succeeded' && !loading && !error" class="resource-section" role="status">
        {{ zh ? '评估报告暂不可读取。可刷新后重试。' : 'The evaluation report is unavailable. Refresh to check again.' }}
      </p>
      <details v-if="!partial && evaluationEvents.length" class="resource-section evaluation-log">
        <summary>
          <ListClock :size="18" aria-hidden="true" />
          <span>{{ zh ? '任务日志' : 'Task log' }}</span>
          <span class="evaluation-log__count">{{ zh ? `${evaluationEvents.length} 条` : `${evaluationEvents.length} events` }}</span>
          <ChevronDown :size="16" class="evaluation-log__chevron" aria-hidden="true" />
        </summary>
        <div class="evaluation-log__body"><TaskEventTimeline :events="evaluationEvents" compact /></div>
      </details>
    </template>
    </template>
    <DetectionEvaluationFailedSamplePreview v-if="selectedFailurePreview" :task-id="taskId" :dataset-export-id="task?.dataset_export_id" :sample="selectedFailurePreview" :reason="failureLabel(selectedFailurePreview.reason)" :advice="failureAdvice(selectedFailurePreview.reason)" :zh="zh" @close="selectedFailurePreview = null" @show-error="showPreviewError" />
    <ConfirmDialog v-if="selectedFailure" :title="zh ? '样本错误' : 'Sample error'" :message="failureLabel(selectedFailure.reason)" :details="selectedFailure.name" :show-confirm="false" confirm-label="" :cancel-label="zh ? '关闭' : 'Close'" @cancel="selectedFailure = null">
      <p class="evaluation-failures__note">{{ failureAdvice(selectedFailure.reason) }}</p>
    </ConfirmDialog>
    <ConfirmDialog
      v-if="confirmCancel && task && ['queued', 'running'].includes(task.state)"
      :title="zh ? '取消评估任务' : 'Cancel evaluation'"
      :message="zh ? '确认取消这次评估？' : 'Cancel this evaluation?'"
      :details="task.display_name"
      :cancel-label="zh ? '返回' : 'Back'"
      :confirm-label="zh ? '确认取消' : 'Confirm cancellation'"
      :busy="cancelling"
      @cancel="confirmCancel = false"
      @confirm="requestCancellation"
    />
    </template>
  </section>
</template>

<script setup lang="ts">
import { useCatalogVersionLabel } from '../composables/useCatalogVersionLabel'
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ChevronDown, CircleAlert, CircleCheck, TriangleAlert, Download, Info, ListClock } from '@lucide/vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Select from '@/shared/ui/components/Select.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import TaskEventTimeline from '@/modules/tasks/components/TaskEventTimeline.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import { cancelTask } from '@/modules/tasks/services/task.service'
import { useSessionStore } from '@/app/stores/session.store'
import DetectionEvaluationFailedSamplePreview from '../components/DetectionEvaluationFailedSamplePreview.vue'
import DetectionEvaluationConditions from '../components/DetectionEvaluationConditions.vue'
import DetectionEvaluationRunStatus from '../components/DetectionEvaluationRunStatus.vue'
import DetectionEvaluationSampleViewer from '../components/DetectionEvaluationSampleViewer.vue'
import DetectionSampleThumbnail from '../components/DetectionSampleThumbnail.vue'
import { formatModelNumber } from '../model-number-format'
import { evaluationClassMean, evaluationRuntime } from '../detection-evaluation-comparison'
import { readEvaluationDatasetVersionNames } from '../evaluation-dataset-exports'
import {
  detectionEvaluationSamplePageSize, downloadEvaluationJson, getDetectionEvaluation, getDetectionEvaluationReport, listDetectionEvaluationSamples,
  type DetectionEvaluationReport, type DetectionEvaluationSample, type DetectionEvaluationTask, type EvaluationBox, type EvaluationIssue, type FailedDetectionSample,
} from '../services/model-evaluation.service'

const DetectionEvaluationCurves = defineAsyncComponent(() => import('../components/DetectionEvaluationCurves.vue'))
const route = useRoute()
const { locale } = useI18n()
const session = useSessionStore()
const zh = computed(() => locale.value.startsWith('zh'))
const taskId = computed(() => String(route.params.taskId || ''))
const evaluationReturn = computed(() => ({
  path: '/models',
  query: { tab: 'evaluation', evalCompare: route.query.evalCompare, evalBaseline: route.query.evalBaseline },
}))
const task = ref<DetectionEvaluationTask | null>(null)
const datasetVersionName = ref('')
watch([() => task.value?.project_id, () => task.value?.dataset_version_id], async ([project, version], _, onCleanup) => {
  datasetVersionName.value = ''
  if (!project || !version || !session.hasScopes(['datasets:read'])) return
  const request = new AbortController()
  onCleanup(() => request.abort())
  try {
    const names = await readEvaluationDatasetVersionNames(project, 'detection', [version], request.signal)
    if (!request.signal.aborted) datasetVersionName.value = names.get(version) ?? ''
  } catch { /* 数据目录不可用时，保留任务保存的版本标识供查看。 */ }
})
const evaluationEventMessages: Record<string, string> = {
  'task created': '任务已创建',
  'task execution started': '开始执行任务',
  'detection evaluation started': '开始目标检测评估',
  'detection evaluation completed': '目标检测评估完成',
}
const evaluationEvents = computed(() => (task.value?.events ?? []).map(event => ({
  ...event,
  message: zh.value && Object.hasOwn(evaluationEventMessages, event.message) ? evaluationEventMessages[event.message] : event.message,
})))
const modelVersionName = useCatalogVersionLabel(() => [task.value?.project_id, 'detection', task.value?.model_version_id])
const report = ref<DetectionEvaluationReport['payload'] | null>(null)
const loading = ref(false)
const error = ref('')
const canWrite = computed(() => session.hasScopes(['tasks:write']))
const canRetryEvaluation = computed(() => Boolean(task.value?.dataset_export_id && task.value.model_version_id)
  && session.hasScopes(['models:read', 'tasks:read', 'tasks:write', 'datasets:read']))
const confirmCancel = ref(false)
const cancelError = ref('')
const selectedFailure = ref<FailedDetectionSample | null>(null)
const selectedFailurePreview = ref<FailedDetectionSample | null>(null)
async function showPreviewError() {
  const failure = selectedFailurePreview.value
  selectedFailurePreview.value = null
  await nextTick()
  selectedFailure.value = failure
}
const cancelling = ref(false)
const tab = ref('class')
const coverage = computed(() => report.value?.coverage ?? task.value?.report_summary.coverage)
const partial = computed(() => (coverage.value?.failed ?? 0) > 0)
const failed = computed(() => ['failed', 'timed_out'].includes(task.value?.state ?? ''))
function failureLabel(reason: FailedDetectionSample['reason']): string {
  return (zh.value ? { missing_image: '图片不存在', unreadable_image: '图片无法读取或解码', invalid_annotation: '标注的类别或边界框无效' }
    : { missing_image: 'Image is missing', unreadable_image: 'Image cannot be read or decoded', invalid_annotation: 'Annotation class or bounding box is invalid' })[reason] || reason
}
function failureAdvice(reason: FailedDetectionSample['reason']): string {
  return (zh.value ? { missing_image: '补齐数据集中的源图像并重新导出。', unreadable_image: '替换损坏的图像并重新导出。', invalid_annotation: '修正图像的类别或边界框标注并重新导出。' }
    : { missing_image: 'Restore the source image and export the dataset again.', unreadable_image: 'Replace the damaged image and export the dataset again.', invalid_annotation: 'Fix the class or bounding box annotation and export the dataset again.' })[reason]
}
const tabs = computed(() => [
  ...(partial.value ? [
    { label: (zh.value ? '失败样本' : 'Failed samples') + ' (' + coverage.value?.failed + ')', id: 'failures' },
    { label: zh.value ? '处理日志' : 'Processing log', id: 'log' },
  ] : []),
  { label: zh.value ? '概览' : 'Overview', id: 'overview' },
  { label: zh.value ? '按类别' : 'By class', id: 'class' },
  { label: zh.value ? '曲线与矩阵' : 'Curves and matrix', id: 'curves' },
  { label: zh.value ? '错误样本' : 'Sample errors', id: 'samples' },
  { label: zh.value ? '执行条件' : 'Conditions', id: 'conditions' },
])
const active = computed(() => ['queued', 'running', 'cancelling'].includes(task.value?.state || ''))
const metrics = computed(() => [
  { label: 'mAP50–95', value: metric(report.value?.map50_95) },
  { label: 'mAP50', value: metric(report.value?.map50) },
  { label: 'Precision', value: metric(report.value?.mean_precision) },
  { label: 'Recall', value: metric(report.value?.mean_recall) },
])
const classTotals = computed(() => {
  const classes = report.value?.per_class_metrics
  if (!classes?.length || !report.value || !task.value) return null
  return {
    gt: classes.reduce((total, row) => total + row.gt_count, 0),
    mean: evaluationClassMean({ task: task.value, report: report.value }),
  }
})
const issue = ref<EvaluationIssue>('errors')
const searchText = ref('')
const search = ref('')
const className = ref('')
const diagnosticsAvailable = ref<boolean | null>(null)
const showIssueFilters = computed(() => diagnosticsAvailable.value !== false)
const classOptions = computed(() => [
  { value: '', label: zh.value ? '全部类别' : 'All classes' },
  ...Array.from(new Set(report.value?.per_class_metrics?.map(row => row.class_name))).map(name => ({ value: name, label: name })),
])
const issueOptions = computed(() => [
  { value: 'all', label: zh.value ? '全部样本' : 'All samples' },
  ...(showIssueFilters.value ? [
    { value: 'errors', label: zh.value ? '全部问题' : 'All issues' },
    { value: 'false_negatives', label: zh.value ? '有漏检' : 'Missed objects' },
    { value: 'false_positives', label: zh.value ? '有误检' : 'False positives' },
    { value: 'localization', label: zh.value ? '定位偏差' : 'Localization errors' },
  ] : []),
])
const sample = ref<DetectionEvaluationSample | null>(null)
const samples = ref<DetectionEvaluationSample[]>([])
const pageSize = detectionEvaluationSamplePageSize
const sampleTotal = ref(0)
const sampleOffset = ref(0)
const sampleLoading = ref(false)
const sampleError = ref('')
const failedSampleOffset = ref(0)
const sampleTable = ref<HTMLElement | null>(null)
const exampleList = ref<HTMLElement | null>(null)
type ExampleIssue = 'false_negatives' | 'false_positives' | 'localization'
const exampleRows = ref<Array<{ issue: ExampleIssue; row: DetectionEvaluationSample }>>([])
const exampleIndex = ref(-1)
const exampleRevision = ref(0)
const examplesLoading = ref(false)
const examplesError = ref('')
const exampleDiagnostics = ref(false)
const activeExample = computed(() => exampleRows.value[exampleIndex.value])
function openExample(index: number): void {
  const example = exampleRows.value[index]
  if (!example) return
  exampleIndex.value = index
  sample.value = example.row
}
watch([tab, taskId, report, exampleRevision], async ([section, id, currentReport], _, onCleanup) => {
  exampleRows.value = []; examplesError.value = ''; examplesLoading.value = false; exampleIndex.value = -1
  if (section !== 'class' || !id || !currentReport) return
  const request = new AbortController()
  onCleanup(() => request.abort())
  examplesLoading.value = true
  const scopes = ['false_negatives', 'false_positives', 'localization'] as const
  try {
    const pages = await Promise.all(scopes.map(issue => listDetectionEvaluationSamples(id, { issue, offset: 0, limit: 2, q: '', class_name: '' }, request.signal)))
    if (request.signal.aborted) return
    exampleDiagnostics.value = pages.every(page => page.diagnostics_available)
    if (!exampleDiagnostics.value) return
    const used = new Set<number>()
    exampleRows.value = scopes.flatMap((issue, index) => {
      const items = pages[index].items
      const row = items.find(item => !used.has(item.image_index)) ?? items[0]
      if (!row) return []
      used.add(row.image_index)
      return [{ issue, row }]
    })
  } catch (cause) {
    if (!request.signal.aborted) examplesError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (!request.signal.aborted) examplesLoading.value = false
  }
})
let sampleRequest: AbortController | undefined
function sampleErrorType(scope: ExampleIssue): string {
  if (scope === 'localization') return zh.value ? '定位偏差' : 'Localization error'
  if (scope === 'false_negatives') return zh.value ? 'FN · 漏检' : 'FN · Missed objects'
  return zh.value ? 'FP · 误检' : 'FP · False positives'
}
function sampleBoxes(item: DetectionEvaluationSample, exampleIssue?: EvaluationIssue) {
  const scope = exampleIssue ?? issue.value
  if (scope === 'localization' && item.localization_pair) {
    const truth = item.ground_truth?.[item.localization_pair.ground_truth_index]
    const prediction = item.predictions?.[item.localization_pair.prediction_index]
    return [
      ...(truth ? [{ box: truth, kind: 'ground-truth' as const }] : []),
      ...(prediction ? [{ box: prediction, kind: 'prediction' as const }] : []),
    ]
  }
  const category = exampleIssue ? '' : className.value
  const matchesFilter = (box: EvaluationBox) => (!category || box.class_name === category) && (scope === 'all' || box.matched === false)
  return [
    ...(scope !== 'false_positives' ? item.ground_truth ?? [] : []).filter(matchesFilter).map(box => ({ box, kind: 'ground-truth' as const })),
    ...(scope !== 'false_negatives' ? item.predictions ?? [] : []).filter(matchesFilter).map(box => ({ box, kind: 'prediction' as const })),
  ]
}
function sampleClasses(item: DetectionEvaluationSample): string {
  return [...new Set(sampleBoxes(item).map(({ box }) => box.class_name))].join(', ') || '—'
}
function sampleIssue(item: DetectionEvaluationSample): string {
  if (item.localization_pair) return `${sampleErrorType('localization')} · IoU ${metric(item.localization_pair.iou)}`
  if (item.false_negatives === undefined && item.false_positives === undefined) return '—'
  const types = []
  const selected = className.value ? sampleBoxes(item).filter(({ box }) => box.matched === false) : undefined
  if (issue.value !== 'false_positives' && (selected ? selected.some(({ kind }) => kind === 'ground-truth') : item.false_negatives)) types.push(zh.value ? '漏检' : 'FN')
  if (issue.value !== 'false_negatives' && (selected ? selected.some(({ kind }) => kind === 'prediction') : item.false_positives)) types.push(zh.value ? '误检' : 'FP')
  return types.join(' / ') || '—'
}
async function closeSample(): Promise<void> {
  const index = sample.value?.image_index
  const previousExample = exampleIndex.value
  sampleRequest?.abort()
  sampleLoading.value = false
  sampleError.value = ''
  sample.value = null
  exampleIndex.value = -1
  await nextTick()
  if (previousExample >= 0) exampleList.value?.querySelector<HTMLButtonElement>(`[data-example-index="${previousExample}"]`)?.focus()
  else sampleTable.value?.querySelector<HTMLButtonElement>(`[data-sample-index="${index}"]`)?.focus()
}

function navigateSample(direction: -1 | 1): void {
  if (!sample.value || sampleLoading.value) return
  if (activeExample.value) { openExample(exampleIndex.value + direction); return }
  sampleError.value = ''
  const index = samples.value.findIndex(item => item.image_index === sample.value?.image_index) + direction
  const position = sampleOffset.value + index
  if (position < 0 || position >= sampleTotal.value) return
  const sibling = samples.value[index]
  if (sibling) sample.value = sibling
  else void loadSamplePage(sampleOffset.value + direction * pageSize, direction)
}
let request: AbortController | undefined
let timer: ReturnType<typeof setTimeout>

function metric(value?: number): string { return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(3) : '—' }
function resetFilters(scope: EvaluationIssue): void {
  const filtersChanged = Boolean(search.value || className.value || issue.value !== scope)
  searchText.value = ''; search.value = ''; className.value = ''; issue.value = scope
  if (!filtersChanged && tab.value === 'samples' && sampleOffset.value > 0) void loadSamplePage(0)
}
watch(searchText, (value, _, onCleanup) => {
  const delay = setTimeout(() => { search.value = value.trim() }, 250)
  onCleanup(() => clearTimeout(delay))
})

async function load(): Promise<void> {
  if (!taskId.value) return
  request?.abort()
  clearTimeout(timer)
  const current = new AbortController()
  request = current
  const id = taskId.value
  loading.value = true
  error.value = ''
  try {
    const data = await getDetectionEvaluation(id, current.signal)
    if (current.signal.aborted) return
    task.value = data
    if (data.state === 'cancelled') {
      report.value = null
      sample.value = null
      sampleRequest?.abort()
    } else if (!active.value && data.report_object_key) {
      const response = await getDetectionEvaluationReport(id, current.signal)
      if (!current.signal.aborted) {
        const hadReport = !!report.value
        report.value = response.file_status === 'ready' ? response.payload : null
        if (!hadReport && report.value && partial.value) tab.value = 'failures'
      }
    } else {
      report.value = null
    }
  } catch (cause) { if (!current.signal.aborted) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally {
    if (!current.signal.aborted) {
      loading.value = false
      if (active.value) timer = setTimeout(() => void load(), 2200)
    }
  }
}

async function requestCancellation(): Promise<void> {
  const id = taskId.value
  if (!canWrite.value || !id || cancelling.value) return
  cancelling.value = true
  cancelError.value = ''
  try {
    await cancelTask(id)
    if (id === taskId.value) { confirmCancel.value = false; await load() }
  } catch (cause) {
    if (id === taskId.value) {
      confirmCancel.value = false
      cancelError.value = cause instanceof Error ? cause.message : String(cause)
    }
  } finally { cancelling.value = false }
}

watch(taskId, () => { task.value = null; report.value = null; selectedFailure.value = null; selectedFailurePreview.value = null; tab.value = route.query.tab === 'samples' ? 'samples' : 'class'; diagnosticsAvailable.value = null; resetFilters('errors'); confirmCancel.value = false; cancelError.value = ''; void load() }, { immediate: true })
watch([tab, taskId, issue, search, className], () => {
  sampleRequest?.abort()
  sample.value = null; samples.value = []; sampleError.value = ''; sampleTotal.value = 0; sampleOffset.value = 0; sampleLoading.value = false
  if (tab.value === 'samples' && taskId.value) void loadSamplePage(0)
}, { immediate: true })

async function loadSamplePage(offset: number, direction?: -1 | 1): Promise<void> {
  sampleRequest?.abort()
  const scope = sampleRequest = new AbortController()
  sampleLoading.value = true
  sampleError.value = ''
  const filter = issue.value
  try {
    const result = await listDetectionEvaluationSamples(taskId.value, { issue: filter, offset, q: search.value, class_name: className.value }, scope.signal)
    if (scope.signal.aborted) return
    diagnosticsAvailable.value = result.diagnostics_available
    if (!result.diagnostics_available && filter !== 'all') { issue.value = 'all'; return }
    if (direction && !result.items.length) {
      sampleError.value = zh.value ? '此页样本已不可用。' : 'The samples on this page are unavailable.'
      return
    }
    samples.value = result.items; sampleTotal.value = result.total
    sampleOffset.value = offset
    if (direction) sample.value = result.items[direction === 1 ? 0 : result.items.length - 1]
  } catch (cause) {
    if (scope.signal.aborted) return
    failedSampleOffset.value = offset
    sampleError.value = cause instanceof Error ? cause.message : String(cause)
  }
  finally { if (!scope.signal.aborted) sampleLoading.value = false }
}

onBeforeUnmount(() => { request?.abort(); sampleRequest?.abort(); clearTimeout(timer) })
</script>

<style scoped>
.evaluation-rerun { display:inline-flex; align-items:center; min-height:36px; padding:0 12px; border:1px solid var(--am-border); border-radius:6px; color:var(--am-text-primary); text-decoration:none; }
.evaluation-coverage { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.65fr) minmax(0,1fr); align-items:center; padding-block:16px; }
.evaluation-coverage > :not(:first-child) { border-inline-start:1px solid var(--am-border); padding-inline:16px; }
.evaluation-coverage .evaluation-metrics--subset { grid-template-columns:repeat(2,minmax(0,1fr)); }
.evaluation-coverage .evaluation-metrics--subset > div { border:0; padding-inline:4px; }
.evaluation-coverage__steps li { position:relative; text-align:center; font-size:12px; }
.evaluation-coverage__steps li + li::before { content:''; position:absolute; inset-inline-end:calc(50% + 12px); inset-block-start:9px; width:calc(100% - 12px); border-block-start:1px solid var(--am-border); }
.evaluation-coverage__steps svg { margin-inline:auto; color:var(--am-success-icon); }
.evaluation-coverage__steps li:nth-child(2) svg { color:var(--am-warning-icon); }
.evaluation-coverage__counts { text-align:center; }
.evaluation-coverage__success { color:var(--am-success-text); }
.evaluation-coverage__failed { color:var(--am-danger-text); }
.evaluation-failures__note { margin:12px 0 0; color:var(--am-text-secondary); overflow-wrap:anywhere; }
@media (max-width:760px) {
  .evaluation-coverage { grid-template-columns:1fr; gap:12px; }
  .evaluation-coverage > :not(:first-child) { border-inline-start:0; border-block-start:1px solid var(--am-border); padding-block-start:12px; }
}
.evaluation-coverage__notice { display:flex; align-items:flex-start; gap:10px; padding:12px; border-radius:6px; border:1px solid var(--am-warning-border); background:var(--am-warning-surface); color:var(--am-warning-text); }
.evaluation-coverage__notice svg { flex:none; }
.evaluation-coverage__notice h2,.evaluation-coverage__notice p { margin:0; }
.evaluation-coverage__notice p { margin-top:4px; }
.evaluation-coverage__steps,.evaluation-coverage__counts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:0; padding:0; list-style:none; }
.evaluation-coverage__steps li,.evaluation-coverage__counts div { display:grid; gap:4px; min-width:0; }
.evaluation-coverage__steps span,.evaluation-coverage__counts dt { color:var(--am-text-secondary); }
.evaluation-coverage__counts dd { margin:0; font-size:18px; font-weight:600; }
.evaluation-coverage .evaluation-coverage__warning { color:var(--am-warning-text); }
.evaluation-failures td { overflow-wrap:anywhere; white-space:normal; }
.evaluation-failures :is(th,td):first-child { width:9%; }
.evaluation-failures :is(th,td):nth-child(3),.evaluation-failures :is(th,td):nth-child(4) { width:14%; }
.evaluation-failures :is(th,td):last-child { width:22%; }
.evaluation-failure-actions { display:flex; flex-wrap:wrap; gap:4px 6px; }

.evaluation-toolbar, .evaluation-toolbar > div { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
.evaluation-toolbar { justify-content:space-between; }
.evaluation-toolbar h1, .evaluation-section h2, .evaluation-summary p { margin:0; }
.evaluation-toolbar a { color:var(--am-brand-primary); }
.evaluation-summary, .evaluation-report, .evaluation-section { display:grid; gap:14px; min-width:0; }
.evaluation-summary { padding-block:14px; gap:10px; }
.evaluation-summary dl { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(0,1.5fr) minmax(0,.8fr) minmax(0,.65fr); gap:12px 20px; margin:0; }
.evaluation-summary dl > div { display:grid; align-content:start; gap:4px; min-width:0; }
.evaluation-summary dt { font-size:var(--am-type-caption); }
@media (max-width:760px) { .evaluation-summary dl { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.evaluation-summary dd { margin:0; overflow-wrap:anywhere; }
.evaluation-summary dt { color:var(--am-text-muted); }
.evaluation-overview { display:grid; grid-template-columns:minmax(0,3fr) minmax(0,2fr); gap:12px; }
.evaluation-overview section { min-width:0; border:1px solid var(--am-border); border-radius:var(--am-radius-md); }
.evaluation-overview h3 { margin:0; padding:10px 14px; border-block-end:1px solid var(--am-border); font-size:inherit; font-weight:600; }
.evaluation-overview dl { display:grid; grid-auto-flow:column; grid-auto-columns:minmax(0,1fr); margin:0; padding-block:12px; }
.evaluation-overview dl > div { display:grid; align-content:start; gap:5px; min-width:0; padding-inline:14px; }
.evaluation-overview dl > div + div { border-inline-start:1px solid var(--am-border); }
.evaluation-overview dt { color:var(--am-text-muted); overflow-wrap:anywhere; }
.evaluation-overview dd { margin:0; color:var(--am-text); font-size:20px; font-weight:600; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
.evaluation-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); padding-block:6px; }
.evaluation-metrics > div { display:grid; gap:4px; padding:4px 12px; text-align:center; }
.evaluation-metrics > div + div { border-inline-start:1px solid var(--am-border); }
.evaluation-metrics span,.evaluation-samples__list small { color:var(--am-text-muted); }
.evaluation-metrics strong { font-size:24px; font-variant-numeric:tabular-nums; }
.evaluation-classes { overflow:auto; }
.evaluation-classes table { width:100%; min-width:0; table-layout:fixed; }
.evaluation-classes :is(th,td) { overflow-wrap:anywhere; }
.evaluation-classes th:first-child { width:42%; }
.evaluation-classes tfoot :is(th,td) { border-block-start:1px solid var(--am-border); border-block-end:0; background:var(--am-surface); color:var(--am-text); font-weight:600; }
.evaluation-classes tfoot th { font-size:inherit; }
.evaluation-examples { display:grid; gap:12px; margin-block-start:8px; padding-block-start:14px; border-top:1px solid var(--am-border); min-width:0; }
.evaluation-examples h3,.evaluation-examples p { margin:0; }
.evaluation-example-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr)); gap:12px; }
.evaluation-example { min-width:0; padding:12px; display:grid; justify-items:start; gap:8px; border:1px solid var(--am-border); border-radius:var(--am-radius-md); background:var(--am-surface-raised); }
.evaluation-example:focus-within { border-color:var(--am-brand-primary); }
.evaluation-example__body { width:100%; min-width:0; display:grid; align-items:center; grid-template-columns:minmax(64px,110px) minmax(0,1fr); gap:10px; }
.evaluation-example dl { display:grid; grid-template-columns:max-content minmax(0,1fr); align-items:baseline; gap:5px 8px; min-width:0; margin:0; font-size:var(--am-font-size-small,13px); }
.evaluation-example dt { color:var(--am-text-muted); }
.evaluation-example dd { margin:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.evaluation-report :deep(.local-tabs__tab) { border-block-end:2px solid transparent; border-radius:0; }
.evaluation-report :deep(.local-tabs__tab.is-active) { background:transparent; border-block-end-color:var(--am-brand-primary); }
.evaluation-filters { display:flex; flex-wrap:wrap; align-items:end; gap:10px 12px; }
.evaluation-filters > :is(label,div) { display:grid; gap:4px; min-width:142px; }
.evaluation-filters > label { flex:1; min-width:180px; }
.evaluation-filters :is(span,input), .evaluation-sample-summary { font-size:var(--am-font-size-small, 13px); }
.evaluation-filters input { width:100%; min-width:0; height:34px; padding:0 10px; border:1px solid var(--am-border); border-radius:6px; background:var(--am-surface-raised); color:var(--am-text); }
.evaluation-sample-summary,.evaluation-filters > :is(label,div) > span { color:var(--am-text-muted); }
.evaluation-sample-summary,.evaluation-sample-error { display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; margin:0; }
.evaluation-samples { display:grid; min-width:0; gap:16px; }
.evaluation-sample-table table { width:100%; table-layout:fixed; }
.evaluation-sample-table :is(th,td) { padding:8px; overflow-wrap:anywhere; }
.evaluation-sample-table tbody th { text-align:left; font-weight:500; }
.evaluation-sample-table th:nth-child(1) { width:5%; }
.evaluation-sample-table th:nth-child(2) { width:19%; }
.evaluation-sample-table th:nth-child(3) { width:21%; }
.evaluation-sample-table :is(th,td):nth-child(n+6) { text-align:center; }
.evaluation-sample-table th:nth-child(n+6) { width:9%; }
.evaluation-sample-table :is(th,td):nth-child(8) { width:12%; }
.evaluation-sample-table .ui-button { max-width:100%; padding-inline:6px; }
.evaluation-pagination { display:flex; gap:8px; justify-content:flex-end; margin-top:10px; }
.evaluation-legend, .evaluation-legend > span { display:inline-flex; flex-wrap:wrap; align-items:center; gap:6px; }
.evaluation-legend { gap:12px; }
.evaluation-legend i { width:20px; height:12px; border:2px dashed #f79235; }
.evaluation-legend .is-truth { border:2px solid var(--am-brand-primary); }
.evaluation-log.resource-section { display:block; padding:0; }
.evaluation-log summary { display:flex; align-items:center; gap:10px; min-height:44px; padding:10px 16px; border-radius:inherit; list-style:none; cursor:pointer; font-weight:600; }
.evaluation-log summary::-webkit-details-marker { display:none; }
.evaluation-log summary:focus-visible { outline-offset:-3px; }
.evaluation-log[open] summary { border-end-start-radius:0; border-end-end-radius:0; background:var(--am-surface); }
.evaluation-log summary:hover { background:var(--am-hover-surface); }
.evaluation-log__count { margin-inline-start:auto; padding:1px 8px; border:1px solid var(--am-border); border-radius:var(--am-radius-pill); background:var(--am-surface); color:var(--am-text-muted); font-size:var(--am-type-caption); font-weight:400; }
.evaluation-log__chevron { color:var(--am-text-muted); }
.evaluation-log[open] .evaluation-log__chevron { transform:rotate(180deg); }
.evaluation-log__body { border-block-start:1px solid var(--am-border); padding:6px 16px; }
@media (max-width:560px) {
  .evaluation-overview { grid-template-columns:minmax(0,1fr); }
  .evaluation-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); row-gap:10px; }
  .evaluation-metrics > div:nth-child(3) { border-inline-start:0; }
}
</style>
