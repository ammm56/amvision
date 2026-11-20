<template>
  <section class="page-stack conversion-detail model-workspace">
    <PageHeader :title="task?.display_name || taskId">
      <template #heading>
        <ButtonLink class="conversion-terminal-back" variant="ghost" size="sm" :to="modelTaskListLocation('conversion', taskType || undefined, route.query)">
          <ArrowLeft :size="16" />{{ label('返回转换与导入', 'Back to conversion and import') }}
        </ButtonLink>
        <div class="conversion-terminal-title">
          <h1>{{ wasCancelled ? label('转换详情', 'Conversion details') : task?.display_name || taskId }}</h1>
          <StatusBadge v-if="failureDetails" tone="danger">{{ label('校验失败', 'Validation failed') }}</StatusBadge>
          <StatusBadge v-else-if="task?.state === 'running'" tone="success" class="conversion-running-badge"><LoaderCircle :size="14" />{{ label('运行中', 'Running') }}</StatusBadge>
          <TaskStateBadge v-else-if="task" :state="task.state" />
        </div>
      </template>
      <template #actions>
        <Button v-if="canCancel" class="conversion-cancel" variant="secondary" @click="cancelDialogOpen = true"><X :size="16" />{{ label('取消转换', 'Cancel conversion') }}</Button>
        <Button v-if="task && (conversionFailed || wasCancelled)" @click="showLog"><FileText :size="16" />{{ label('查看日志', 'View log') }}</Button>
        <Button v-if="activeTask && task?.events.length" @click="downloadLog"><Download :size="16" />{{ label('下载日志', 'Download log') }}</Button>
        <Button v-if="failureDetails || (task?.state === 'succeeded' && task.result.report_object_key)" :disabled="loading || reportDownloading" :loading="reportDownloading" @click="downloadReport">
          <Download :size="16" />{{ failureDetails ? (locale.startsWith('zh') ? '下载校验诊断' : 'Download diagnostics') : (locale.startsWith('zh') ? '下载报告' : 'Download report') }}
        </Button>
        <Button
          v-if="deploymentBuild && canDeploy"
          variant="primary"
          :disabled="deploying"
          :loading="deploying"
          @click="openDeployment(deploymentBuild)"
        >
          <Box :size="16" />{{ label('创建部署', 'Create deployment') }}
        </Button>
        <Button v-if="!task" variant="secondary" :disabled="loading" :loading="loading" @click="loadDetail()">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
        <ButtonLink v-if="conversionCopyLocation" variant="primary" :to="conversionCopyLocation">
          {{ wasCancelled ? label('按此配置新建转换', 'Create conversion with this configuration') : label('调整参数重新转换', 'Adjust settings and convert again') }}
        </ButtonLink>
        <ResourceMenu v-if="task" :label="label('更多操作', 'More actions')" :items="terminalActions" @action="runTerminalAction" />
      </template>
    </PageHeader>

    <InlineError v-if="!failureDetails" :message="reportError" />
    <InlineError :message="errorMessage" />
    <p v-if="!task && loading" class="conversion-muted" role="status">{{ label('正在加载转换详情…', 'Loading conversion details…') }}</p>

    <dl v-if="task" class="conversion-terminal-summary">
      <div><dt>{{ label('来源模型', 'Source model') }}</dt><dd><Box :size="16" />{{ terminalSourceName }}</dd></div>
      <div v-if="failureDetails"><dt>{{ label('参考运行时', 'Reference runtime') }}</dt><dd>{{ failureDetails.source_runtime }}</dd></div>
      <div v-else><dt>{{ label('任务类型', 'Task type') }}</dt><dd>{{ taskType }}</dd></div>
      <div><dt>{{ label('目标格式', 'Target format') }}</dt><dd><FileCode :size="16" />{{ targetFormat }}</dd></div>
      <div v-if="conversionPrecision"><dt>{{ label('精度', 'Precision') }}</dt><dd>{{ conversionPrecision }}</dd></div>
      <div v-if="inputShape"><dt>{{ label('输入尺寸', 'Input dimensions') }}</dt><dd>{{ inputShape }}</dd></div>
      <div v-if="task.started_at"><dt>{{ activeTask ? label('已用时间', 'Elapsed time') : label('总用时', 'Total duration') }}</dt><dd>{{ elapsedTime }}</dd></div>
    </dl>

    <section v-if="task && terminalStages.length" class="resource-section conversion-terminal-progress">
      <h2>{{ label('转换阶段', 'Conversion stages') }}</h2>
      <p v-if="task.state === 'running' && terminalStages.every(step => step.state === 'unknown')" class="conversion-muted" role="status">
        {{ label('Worker 正在处理，等待阶段记录。', 'The worker is processing the task. Stage details are pending.') }}
      </p>
      <ol class="conversion-stage-timeline">
        <li v-for="(step, index) in terminalStages" :key="`${step.kind}-${index}`" :class="`is-${step.state}`">
          <span class="conversion-stage-timeline__mark" aria-hidden="true">
            <Check v-if="step.state === 'done'" :size="17" />
            <X v-else-if="step.state === 'failed' || step.state === 'cancelled'" :size="17" />
            <LoaderCircle v-else-if="step.state === 'running'" :size="17" />
            <template v-else>{{ index + 1 }}</template>
          </span>
          <strong>{{ stageLabel(step.kind) }}</strong>
          <span>{{ terminalStageLabels[step.state] }}<template v-if="step.startedAt && (step.endedAt || step.state === 'running')">
            · {{ conversionElapsedTime(step.startedAt, step.endedAt ?? observedAt, locale) }}</template></span>
        </li>
      </ol>
    </section>

    <ConversionValidationFailure v-if="failureDetails && task" :key="task.task_id" :details="failureDetails"
      :downloading="reportDownloading" :download-error="reportError" @download="downloadReport" />

    <section v-if="task && wasCancelled" class="resource-section conversion-cancelled-result">
      <h2>{{ label('转换结果', 'Conversion result') }}</h2>
      <div class="conversion-cancelled-note" role="status"><X :size="21" aria-hidden="true" /><div>
        <strong>{{ label('转换已取消', 'Conversion cancelled') }}</strong>
        <p v-if="!task.builds.length">{{ label('本次任务没有新增可用产物。', 'This task registered no new artifacts.') }}</p>
      </div></div>
      <h3>{{ label('产物', 'Artifacts') }}</h3>
      <p v-if="!task.builds.length" class="conversion-empty-artifacts"><Box :size="16" aria-hidden="true" />{{ label('没有新增可用产物', 'No new artifacts available') }}</p>
      <h3>{{ label('转换配置', 'Conversion configuration') }}</h3>
      <dl class="conversion-cancelled-config">
        <div v-for="row in conversionConfiguration" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div>
      </dl>
    </section>

    <section v-if="task && (!specialResult || task.builds.length)" class="resource-section conversion-output">
      <TabList v-model="outputTab" :tabs="outputTabs" :label="label('转换详情', 'Conversion details')" />
      <template v-if="outputTab === 'files'">
      <div v-if="activeTask" class="conversion-output-pending">
        <FileCode :size="38" aria-hidden="true" />
        <h2>{{ label('转换完成后显示产物', 'Artifacts appear after conversion') }}</h2>
        <p>{{ label('转换和校验完成后，可在此查看已登记的文件。', 'Registered files will appear here after conversion and validation.') }}</p>
      </div>
      <EmptyState v-else-if="task.builds.length === 0" :title="t('conversionDetail.emptyBuildsTitle')" :description="t('conversionDetail.emptyBuildsDescription')" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('conversionDetail.columns.file') }}</th>
              <th>{{ t('conversionDetail.columns.format') }}</th>
              <th>{{ label('说明', 'Description') }}</th>
              <th>{{ locale.startsWith('zh') ? '操作' : 'Actions' }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="build in task.builds" :key="build.model_build_id">
              <td>
                <span class="conversion-file-name"><FileCode :size="15" aria-hidden="true" />{{ build.build_file_uri?.split(/[\\/]/).pop() || build.build_file_id || '—' }}</span>
              </td>
              <td>{{ build.build_format || '-' }}</td>
              <td>{{ [build.runtime_backend, build.runtime_precision?.toUpperCase()].filter(Boolean).join(' · ') || '—' }}</td>
              <td class="conversion-build-actions">
                <Button size="sm" variant="ghost" :disabled="!build.build_file_uri || !!buildDownloading" @click="downloadBuild(build, 'primary')">{{ locale.startsWith('zh') ? '下载' : 'Download' }}</Button>
                <Button v-if="weightsUri(build)" size="sm" variant="ghost" :disabled="!!buildDownloading" @click="downloadBuild(build, 'weights')">{{ locale.startsWith('zh') ? '下载权重' : 'Download weights' }}</Button>
              </td>
            </tr>
            <tr v-if="task.state === 'succeeded' && task.result.report_object_key">
              <td><span class="conversion-file-name"><FileText :size="15" aria-hidden="true" />{{ reportFilename }}</span></td>
              <td>JSON</td>
              <td>{{ label('转换报告', 'Conversion report') }}</td>
              <td class="conversion-build-actions"><Button size="sm" variant="ghost" :disabled="reportDownloading" @click="downloadReport">{{ label('下载', 'Download') }}</Button></td>
            </tr>
          </tbody>
        </table>
      </div>
      </template>
      <div v-else-if="outputTab === 'error'" class="conversion-failure">
        <div><CircleAlert :size="22" aria-hidden="true" /><h2>{{ task.state === 'timed_out' ? label('转换超时', 'Conversion timed out') : label('转换失败', 'Conversion failed') }}</h2></div>
        <p>{{ task.error_message || label('任务没有记录错误说明。', 'The task did not record an error message.') }}</p>
        <details v-if="errorDetails" class="conversion-raw-detail">
          <summary>{{ label('错误详情', 'Error details') }}</summary>
          <div class="conversion-error-copy">
            <Button size="sm" variant="ghost" @click="copyErrorDetails"><Copy :size="15" />{{ label('复制错误详情', 'Copy error details') }}</Button>
            <span v-if="copyStatus" role="status">{{ copyStatus }}</span>
          </div>
          <pre class="json-view">{{ errorDetails }}</pre>
        </details>
      </div>
      <template v-else-if="outputTab === 'logs'">
        <Button v-if="task.events.length" size="sm" variant="secondary" class="conversion-log-download" @click="downloadLog">
          <Download :size="16" />{{ label('下载日志', 'Download log') }}
        </Button>
        <ol v-if="task.events.length" class="conversion-event-log">
          <li v-for="event in task.events" :key="event.event_id"><time :datetime="event.created_at">{{ formatSystemDateTime(event.created_at) }}</time><span>{{ event.message || event.event_type }}</span></li>
        </ol>
        <EmptyState v-else :title="label('暂无转换事件', 'No conversion events recorded')" />
      </template>
      <template v-else-if="outputTab === 'environment'">
        <dl v-if="environmentFields.length" class="conversion-detailed-fields">
          <div v-for="row in environmentFields" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div>
        </dl>
        <EmptyState v-else :title="label('暂无环境记录', 'No environment details recorded')" />
        <Button class="conversion-log-download" size="sm" @click="environmentOpen = true">{{ label('查看执行环境', 'View execution environment') }}</Button>
      </template>
      <template v-else>
        <dl class="conversion-detailed-fields">
          <div v-for="row in conversionConfiguration" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div>
          <div><dt>{{ t('conversionDetail.fields.createdAt') }}</dt><dd>{{ formatSystemDateTime(task.created_at) }}</dd></div>
          <div v-if="task.started_at"><dt>{{ label('开始时间', 'Started at') }}</dt><dd>{{ formatSystemDateTime(task.started_at) }}</dd></div>
          <div v-if="task.finished_at"><dt>{{ label('结束时间', 'Finished at') }}</dt><dd>{{ formatSystemDateTime(task.finished_at) }}</dd></div>
        </dl>
        <details class="conversion-raw-detail"><summary>{{ t('conversionDetail.specTitle') }}</summary><pre class="json-view">{{ taskSpecJson }}</pre></details>
        <details v-if="task.state === 'succeeded'" class="conversion-raw-detail"><summary>{{ t('conversionDetail.resultTitle') }}</summary><pre class="json-view">{{ resultJson }}</pre></details>
      </template>
    </section>

    <section v-if="task?.state === 'succeeded' && int8Validation" class="resource-section conversion-validation">
      <h2>{{ int8Validation.target }} {{ label('INT8 校验', 'INT8 validation') }}</h2>
      <dl>
        <div><dt>{{ locale.startsWith('zh') ? '校准样本（train）' : 'Calibration samples (train)' }}</dt><dd>{{ int8Validation.calibrationCount }}</dd></div>
        <div><dt>{{ locale.startsWith('zh') ? '校验样本（val）' : 'Validation samples (val)' }}</dt><dd>{{ int8Validation.validationCount }}</dd></div>
        <div><dt>{{ int8Validation.p99 ? label('P99 误差上限', 'P99 error limit') : label('最大误差上限', 'Maximum error limit') }}</dt><dd>{{ int8Validation.maxLimit }}</dd></div>
        <div><dt>{{ locale.startsWith('zh') ? '平均误差上限' : 'Mean error limit' }}</dt><dd>{{ int8Validation.meanLimit }}</dd></div>
      </dl>
      <div class="resource-table conversion-int8-table">
        <table>
          <thead><tr>
            <th>Profile</th><th>NCHW</th>
            <th>{{ int8Validation.p99 ? label('最高 P99 误差', 'Highest P99 error') : label('最大误差', 'Maximum error') }}</th>
            <th>{{ locale.startsWith('zh') ? '平均误差' : 'Mean error' }}</th>
          </tr></thead>
          <tbody><tr v-for="row in int8Validation.profiles" :key="row.name"><td>{{ row.name }}</td><td>{{ row.shape }}</td><td>{{ row.maximum }}</td><td>{{ row.mean }}</td></tr></tbody>
        </table>
      </div>
      <p>{{ locale.startsWith('zh') ? '参考输出来自 ONNX Runtime。坐标按输入宽高归一化，类别分数直接比较。' : 'Reference outputs come from ONNX Runtime. Box coordinates are normalized by input size and class scores are compared directly.' }}</p>
      <Button class="conversion-log-download" size="sm" @click="environmentOpen = true">{{ label('查看环境', 'View environment') }}</Button>
    </section>
    <section v-else-if="task?.state === 'succeeded' && validationSummary" class="resource-section conversion-validation">
      <h2>{{ locale.startsWith('zh') ? '数值校验摘要' : 'Numerical validation' }}</h2>
      <dl>
        <div v-if="validationSummary.scope"><dt>{{ label('校验输入', 'Validation input') }}</dt><dd>{{ validationSummary.scope }}</dd></div>
        <div v-else-if="validationSummary.stage"><dt>{{ label('校验阶段', 'Stage') }}</dt><dd>{{ stageLabel(validationSummary.stage) }}</dd></div>
        <div><dt>{{ locale.startsWith('zh') ? '最大绝对误差' : 'Maximum absolute difference' }}</dt><dd>{{ validationSummary.maxDifference }}</dd></div>
        <div><dt>{{ locale.startsWith('zh') ? '绝对容差' : 'Absolute tolerance' }}</dt><dd>{{ validationSummary.tolerance }}</dd></div>
        <div><dt>{{ locale.startsWith('zh') ? '相对容差' : 'Relative tolerance' }}</dt><dd>{{ validationSummary.relativeTolerance }}</dd></div>
        <div><dt>{{ locale.startsWith('zh') ? '结果' : 'Result' }}</dt><dd>{{ validationSummary.result }}</dd></div>
        <div v-if="validationSummary.targetRuntime"><dt>{{ label('目标环境', 'Target environment') }}</dt><dd>{{ validationSummary.targetRuntime }} <Button size="sm" variant="ghost" @click="environmentOpen = true">{{ label('查看环境', 'View environment') }}</Button></dd></div>
      </dl>
      <p>{{ locale.startsWith('zh') ? '结果来自转换任务报告，仅反映报告中的校验范围。比较可同时使用绝对容差和相对容差。' : 'These values apply only to the reported validation scope. Comparison can use both absolute and relative tolerance.' }}</p>
    </section>

    <SideDrawer :open="eventDrawerOpen" :title="label('转换日志', 'Conversion log')" :close-label="t('common.close')" @close="eventDrawerOpen = false">
      <ol v-if="task?.events.length" class="conversion-event-log">
        <li v-for="event in task.events" :key="event.event_id"><time :datetime="event.created_at">{{ formatSystemDateTime(event.created_at) }}</time><span>{{ event.message || event.event_type }}</span></li>
      </ol>
      <EmptyState v-else :title="label('暂无转换事件', 'No conversion events recorded')" />
      <template #footer><Button :disabled="!task?.events.length" size="sm" @click="downloadLog"><Download :size="16" />{{ label('下载日志', 'Download log') }}</Button></template>
    </SideDrawer>

    <SideDrawer :open="environmentOpen" :title="label('执行环境', 'Execution environment')" :close-label="t('common.close')" size="compact" @close="environmentOpen = false">
      <div class="conversion-environment">
        <div v-if="environmentValidated" class="conversion-environment__checked" role="status">
          <Check :size="20" aria-hidden="true" /><div><strong>{{ label('运行时校验通过', 'Runtime validation passed') }}</strong>
          <p>{{ label('基于此转换任务记录的执行环境。', 'Based on the execution environment recorded by this conversion.') }}</p></div>
        </div>
        <section v-if="deviceFields.length" class="conversion-environment__group">
          <h2>{{ label('硬件环境', 'Hardware') }}</h2>
          <dl><div v-for="row in deviceFields" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl>
        </section>
        <section v-if="environmentFields.length" class="conversion-environment__group">
          <h2>{{ label('软件环境', 'Software') }}</h2>
          <dl><div v-for="row in environmentFields" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl>
        </section>
        <EmptyState v-else :title="label('暂无环境记录', 'No environment details recorded')" />
        <section v-if="task?.target_formats.includes('tensorrt-engine')" class="conversion-environment__group">
          <h2>{{ label('目标约束', 'Target requirements') }}</h2>
          <p>{{ label('部署设备需要与引擎兼容的 GPU、CUDA 和 TensorRT 运行时。', 'The deployment target requires a GPU, CUDA and TensorRT runtime compatible with the engine.') }}</p>
        </section>
        <InlineError :message="reportError" />
      </div>
      <template #footer>
        <Button v-if="task?.state === 'succeeded' && task.result.report_object_key" :disabled="reportDownloading" :loading="reportDownloading" @click="downloadReport">
          <Download :size="16" />{{ label('下载转换报告', 'Download conversion report') }}
        </Button>
        <Button variant="primary" @click="environmentOpen = false">{{ t('common.close') }}</Button>
      </template>
    </SideDrawer>

    <ConfirmDialog v-if="cancelDialogOpen"
      :title="label('取消转换', 'Cancel conversion')"
      :message="label('取消后将停止本次转换，已登记的来源版本和产物会保留。', 'Cancelling stops this conversion. The source version and its existing artifacts are retained.')"
      :confirm-label="label('确认取消', 'Confirm cancellation')" :cancel-label="label('继续转换', 'Continue conversion')"
      confirm-variant="danger" :busy="cancelling" :confirm-disabled="!canCancel"
      @cancel="cancelDialogOpen = false" @confirm="cancelConversion">
      <InlineError :message="cancelError" />
    </ConfirmDialog>

    <ConfirmDialog
      v-if="task && deleteDialogOpen"
      :title="t('conversionDetail.deleteDialog.title')"
      :message="t('conversionDetail.messages.confirmDelete')"
      :confirm-label="t('conversionDetail.deleteDialog.confirm')"
      :cancel-label="t('common.cancel')"
      :busy="deleting"
      :confirm-disabled="loading || !canWriteTasks || !canDeleteCurrentTask"
      confirm-variant="danger"
      size="medium"
      scroll-body
      @cancel="deleteDialogOpen = false"
      @confirm="deleteCurrentTask"
    >
      <div class="conversion-delete-scope">
        <dl>
          <dt>{{ t('conversionDetail.deleteDialog.task') }}</dt><dd>{{ task.display_name || task.task_id }}</dd>
          <dt>{{ t('conversionDetail.fields.targetFormats') }}</dt><dd>{{ task.target_formats.join(' / ') || '—' }}</dd>
          <dt>{{ t('conversionDetail.deleteDialog.precision') }}</dt><dd>{{ deletePrecisions }}</dd>
          <dt>{{ t('conversionDetail.deleteDialog.status') }}</dt><dd><TaskStateBadge :state="task.state" /></dd>
          <dt>{{ t('conversionDetail.fields.createdAt') }}</dt><dd>{{ formatSystemDateTime(task.created_at) }}</dd>
        </dl>
        <section class="conversion-delete-scope__impact conversion-delete-scope__impact--remove">
          <Trash2 :size="20" aria-hidden="true" />
          <div><strong>{{ t('conversionDetail.deleteDialog.remove') }}</strong><ul><li v-for="item in ['record', 'logs', 'temporary']" :key="item">{{ t('conversionDetail.deleteDialog.' + item) }}</li></ul></div>
        </section>
        <section class="conversion-delete-scope__impact conversion-delete-scope__impact--keep">
          <Database :size="20" aria-hidden="true" />
          <div><strong>{{ t('conversionDetail.deleteDialog.keep') }}</strong><ul><li v-for="item in ['version', 'artifacts', 'references']" :key="item">{{ t('conversionDetail.deleteDialog.' + item) }}</li></ul></div>
        </section>
        <InlineError :message="deleteError" />
      </div>
    </ConfirmDialog>
  </section>
</template>

<script setup lang="ts">
import { useCatalogVersionLabel } from '../composables/useCatalogVersionLabel'
import { computed, ref, watch } from 'vue'
import { Activity, ArrowLeft, Box, Check, CircleAlert, Copy, Database, Download, FileCode, FileText, LoaderCircle, RefreshCw, Trash2, X } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { modelTaskListLocation } from '../model-task-navigation'
import { useI18n } from 'vue-i18n'

import {
  deleteModelConversionTask,
  downloadModelConversionBuildFile,
  downloadModelConversionReport,
  getModelConversionTaskDetail,
  listDeploymentSourceModels,
  type ModelConversionTaskDetail,
  type ModelConversionBuildSummary,
  type ModelTaskType,
} from '../services/model.service'
import { useSessionStore } from '@/app/stores/session.store'
import { canAccessPage } from '@/platform/auth/page-access'
import { cancelTask } from '@/modules/tasks/services/task.service'
import { useModelTaskScope, type ModelTaskTarget } from '../composables/useModelTaskScope'
import Button from '@/shared/ui/components/Button.vue'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import ResourceMenu from '@/shared/ui/components/ResourceMenu.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'
import PageHeader from '@/shared/ui/layout/PageHeader.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import { formatSmallModelNumber } from '../model-number-format'
import ConversionValidationFailure from '../components/ConversionValidationFailure.vue'
import { readConversionValidationFailure } from '../conversion-validation-failure'
import { conversionElapsedTime, conversionRecord, conversionTargetLabel, readConversionStages } from '../conversion-task-presentation'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const { t, locale } = useI18n()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en

const task = ref<ModelConversionTaskDetail | null>(null)
const sourceVersionName = useCatalogVersionLabel(() => [task.value?.project_id, String(route.params.taskType ?? ''), task.value?.source_model_version_id])
const failureDetails = computed(() => task.value?.state === 'failed' ? readConversionValidationFailure(task.value.result.error_details) : null)
const wasCancelled = computed(() => task.value?.state === 'cancelled')
const conversionFailed = computed(() => task.value?.state === 'failed' || task.value?.state === 'timed_out')
const specialResult = computed(() => Boolean(wasCancelled.value || failureDetails.value))
const activeTask = computed(() => !!task.value && !isTerminalTask(task.value.state))
const failedValidation = computed(() => {
  const runtime = failureDetails.value?.target_runtime
  if (runtime?.startsWith('OpenVINO')) return 'validate-openvino'
  if (runtime?.startsWith('TensorRT')) return 'validate-tensorrt'
})
const terminalStages = computed(() => task.value ? readConversionStages(task.value,
  failedValidation.value) : [])
const terminalStageLabels = computed(() => ({ done: label('已完成', 'Completed'), failed: failureDetails.value ? label('校验失败', 'Validation failed') : label('失败', 'Failed'),
  cancelled: label('已取消', 'Cancelled'), skipped: label('未执行', 'Not started'), unknown: label('缺少阶段记录', 'Stage not recorded'),
  running: label('运行中', 'Running'), waiting: label('待开始', 'Waiting') }))
const terminalSourceName = computed(() => {
  const name = task.value?.report_summary.model_name ?? task.value?.metadata.source_model_name
  return sourceVersionName.value || (typeof name === 'string' && name ? name : '—')
})
const targetLabel = computed(() => task.value ? failureDetails.value?.target_runtime ?? conversionTargetLabel(task.value, locale.value.startsWith('zh')) : '—')
const observedAt = ref(new Date().toISOString())
const elapsedTime = computed(() => conversionElapsedTime(task.value?.started_at,
  task.value?.finished_at ?? (activeTask.value ? observedAt.value : null), locale.value))
const targetBuild = computed(() => task.value?.builds.find(build => task.value?.target_formats.includes(build.build_format)))
const conversionOptions = computed(() => ({ ...conversionRecord(task.value?.report_summary.conversion_options),
  ...conversionRecord(task.value?.task_spec?.extra_options) }))
const conversionPrecision = computed(() => {
  const precision = targetBuild.value?.runtime_precision ?? conversionOptions.value.tensorrt_engine_precision ?? conversionOptions.value.openvino_ir_precision
  return typeof precision === 'string' ? precision.toUpperCase() : ''
})
const targetFormat = computed(() => {
  const precision = ` ${conversionPrecision.value}`
  return conversionPrecision.value && targetLabel.value.endsWith(precision)
    ? targetLabel.value.slice(0, -precision.length) : targetLabel.value
})
const inputShape = computed(() => {
  const options = conversionOptions.value
  const profile = conversionRecord(options.input_profile)
  if (Array.isArray(profile.min) && Array.isArray(profile.max)) {
    return `${profile.min.join(' × ')} – ${profile.max.join(' × ')}`
  }
  const shape = targetBuild.value?.metadata?.input_shape ?? conversionRecord(targetBuild.value?.metadata?.input_tensor).shape
  if (Array.isArray(shape)) return shape.join(' × ')
  const size = conversionRecord(task.value?.report_summary.input_size ?? task.value?.metadata.source_input_size)
  return typeof size.width === 'number' && typeof size.height === 'number' ? `${size.height} × ${size.width}` : ''
})
const conversionConfiguration = computed(() => {
  const options = conversionOptions.value
  const opset = options.onnx_opset_version
  return [
    { label: label('来源模型版本', 'Source model version'), value: terminalSourceName.value },
    { label: label('目标格式', 'Target format'), value: targetLabel.value },
    { label: 'ONNX Opset', value: typeof opset === 'number' ? opset : null },
    { label: label('输入方式', 'Input mode'), value: options.input_shape_mode === 'dynamic-batch' ? label('动态批次', 'Dynamic batch')
      : options.input_shape_mode === 'dynamic' ? label('动态尺寸', 'Dynamic dimensions')
        : options.input_shape_mode === 'static' ? label('固定尺寸', 'Fixed dimensions') : null },
    { label: label('输入尺寸', 'Input dimensions'), value: inputShape.value || null },
    { label: label('精度', 'Precision'), value: conversionPrecision.value || null },
    { label: label('运行配置', 'Runtime profile'), value: task.value?.runtime_profile_id || null },
  ].filter(row => row.value !== null)
})
const eventDrawerOpen = ref(false)
const environmentOpen = ref(false)
const outputTab = ref('files')
const outputTabs = computed(() => [
  ...(conversionFailed.value ? [{ id: 'error', label: label('错误信息', 'Error information') }] : []),
  { id: 'files', label: label('输出文件', 'Output files') },
  { id: 'logs', label: label('运行日志', 'Run logs') },
  { id: 'parameters', label: label('参数配置', 'Parameters') },
  { id: 'environment', label: label('环境信息', 'Environment') },
])
const errorDetails = computed(() => task.value?.result.error_details ? JSON.stringify(task.value.result.error_details, null, 2) : '')
const copyStatus = ref('')
const reportFilename = computed(() => typeof task.value?.result.report_object_key === 'string'
  ? task.value.result.report_object_key.split('/').pop() || 'conversion-report.json' : 'conversion-report.json')
const runtimeValidation = computed(() => conversionRecord(targetBuild.value?.metadata?.runtime_smoke ?? task.value?.report_summary.validation_summary))
const validationSummary = computed(() => {
  const value = runtimeValidation.value
  if (!Object.keys(value).length) return null
  const result = typeof value.passed === 'boolean' ? value.passed : value.allclose
  const format = (item: unknown) => typeof item === 'number' ? formatSmallModelNumber(item) : '—'
  return {
    stage: typeof value.stage === 'string' ? value.stage : '',
    maxDifference: format(value.max_abs_diff),
    tolerance: format(value.absolute_tolerance),
    relativeTolerance: format(value.relative_tolerance),
    result: typeof result === 'boolean' ? (result ? (locale.value.startsWith('zh') ? '通过' : 'Passed') : (locale.value.startsWith('zh') ? '未通过' : 'Failed')) : '—',
    targetRuntime: typeof value.target_runtime === 'string' ? value.target_runtime : '',
    scope: Array.isArray(value.input_shape) ? value.input_shape.join(' × ') : '',
  }
})
const environmentFields = computed(() => [
  { label: label('Worker 池', 'Worker pool'), value: task.value?.worker_pool },
  { label: label('运行配置', 'Runtime profile'), value: task.value?.runtime_profile_id },
  { label: label('来源运行时', 'Reference runtime'), value: runtimeValidation.value.source_runtime },
  { label: label('目标运行时', 'Target runtime'), value: runtimeValidation.value.target_runtime ?? targetBuild.value?.runtime_backend },
  { label: label('执行方式', 'Execution mode'), value: targetBuild.value?.metadata?.execution_mode },
  { label: label('TensorRT 版本', 'TensorRT version'), value: targetBuild.value?.metadata?.tensorrt_version },
].filter(row => typeof row.value === 'string' && row.value))
const environmentValidated = computed(() => runtimeValidation.value.passed === true || runtimeValidation.value.allclose === true
  || runtimeValidation.value.status === 'passed')
const deviceFields = computed(() => {
  const device = conversionRecord(task.value?.report_summary.device_lease ?? targetBuild.value?.metadata?.device_lease)
  return [
    { label: 'GPU', value: device.resolved_device ?? device.device_name },
    { label: 'CUDA', value: typeof device.cuda_index === 'number' ? label(`设备 ${device.cuda_index}`, `Device ${device.cuda_index}`) : null },
  ].filter(row => typeof row.value === 'string' && row.value)
})
const int8Validation = computed(() => {
  const build = task.value?.builds.find(row => ['tensorrt-engine', 'openvino-ir'].includes(row.build_format) && row.runtime_precision === 'int8')
  const runtime = build?.metadata.runtime_smoke as {
    status?: string
    validation_sample_count?: number
    max_error_limit?: number
    mean_error_limit?: number
    peak_rule?: string
    profiles?: Record<string, { input_shape: number[]; max_error: number; mean_error: number }>
  } | undefined
  if (runtime?.status !== 'passed' || !runtime.profiles) return null
  const calibration = build?.metadata.calibration as { sample_count?: number } | undefined
  return {
    target: build?.build_format === 'openvino-ir' ? 'OpenVINO' : 'TensorRT',
    p99: runtime.peak_rule === 'p99',
    calibrationCount: calibration?.sample_count,
    validationCount: runtime.validation_sample_count,
    maxLimit: formatSmallModelNumber(runtime.max_error_limit ?? NaN),
    meanLimit: formatSmallModelNumber(runtime.mean_error_limit ?? NaN),
    profiles: ['static', 'min', 'opt', 'max'].flatMap(name => {
      const row = runtime.profiles?.[name]
      return row ? [{ name, shape: row.input_shape.join(' × '), maximum: formatSmallModelNumber(row.max_error), mean: formatSmallModelNumber(row.mean_error) }] : []
    }),
  }
})
function stageLabel(kind: string): string {
  const labels: Record<string, [string, string]> = {
    'prepare-conversion': ['准备转换', 'Prepare conversion'],
    'export-onnx': ['导出 ONNX', 'Export ONNX'],
    'validate-onnx': ['校验 ONNX', 'Validate ONNX'],
    'optimize-onnx': ['优化 ONNX', 'Optimize ONNX'],
    'build-openvino-ir': ['构建 OpenVINO', 'Build OpenVINO'],
    'build-tensorrt-engine': ['构建 TensorRT', 'Build TensorRT'],
    'validate-openvino': ['校验 OpenVINO', 'Validate OpenVINO'],
    'validate-tensorrt': ['数值校验', 'Numerical validation'],
    'register-artifact': ['登记产物', 'Register artifacts'],
  }
  return labels[kind]?.[locale.value.startsWith('zh') ? 0 : 1] ?? (kind || '—')
}
const loading = ref(false)
const deleting = ref(false)
const deploying = ref(false)
const cancelling = ref(false)
const cancelDialogOpen = ref(false)
const cancelError = ref<string | null>(null)
let detailPending: ReturnType<typeof taskScope.startRead> = null
const reportDownloading = ref(false)
const reportError = ref<string | null>(null)
const buildDownloading = ref('')
const deleteDialogOpen = ref(false)
const errorMessage = ref<string | null>(null)
const deleteError = ref<string | null>(null)

const taskId = computed(() => String(route.params.taskId ?? ''))
const taskType = computed<ModelTaskType | null>(() => {
  const value = String(route.params.taskType ?? '')
  return ['detection', 'classification', 'segmentation', 'pose', 'obb'].includes(value)
    ? value as ModelTaskType
    : null
})
const taskScope = useModelTaskScope(() => taskType.value, () => taskId.value)
let deleteTarget: ModelTaskTarget | null = null
const canWriteTasks = computed(() => sessionStore.hasScopes(['models:write', 'tasks:write']))
const canCancel = computed(() => sessionStore.hasScopes(['tasks:write'])
  && ['queued', 'running', 'pending'].includes(task.value?.state || ''))
const canDeploy = computed(() => sessionStore.hasScopes(['models:write']) && canAccessPage(sessionStore.currentUser, 'deployments'))
const deploymentBuild = computed(() => task.value?.state === 'succeeded' && targetBuild.value?.build_file_uri ? targetBuild.value : null)
const conversionCopyLocation = computed(() => {
  if ((!conversionFailed.value && !wasCancelled.value) || !task.value || !taskType.value || !canWriteTasks.value || !sessionStore.hasScopes(['models:read', 'tasks:read'])) return null
  const location = modelTaskListLocation('conversion', taskType.value, route.query)
  return { ...location, query: { ...location.query, conversionFrom: task.value.task_id } }
})
const canDeleteCurrentTask = computed(() => task.value ? isTerminalTask(task.value.state) : false)
const terminalActions = computed(() => [
  { id: 'task', label: t('conversionDetail.actions.taskStatus'), icon: Activity },
  { id: 'refresh', label: t('common.refresh'), icon: RefreshCw, disabled: loading.value },
  ...(canWriteTasks.value ? [{ id: 'delete', label: t('conversionDetail.actions.delete'), icon: Trash2,
    disabled: loading.value || deleting.value || !canDeleteCurrentTask.value, danger: true }] : []),
])
function runTerminalAction(action: string): void {
  if (action === 'task' && task.value) void router.push(`/tasks/${encodeURIComponent(task.value.task_id)}`)
  if (action === 'refresh') void loadDetail()
  if (action === 'delete') openDeleteDialog()
}
function showLog(): void {
  if (specialResult.value) eventDrawerOpen.value = true
  else outputTab.value = 'logs'
}
const resultJson = computed(() => JSON.stringify(task.value?.result ?? {}, null, 2))
const taskSpecJson = computed(() => JSON.stringify(task.value?.task_spec ?? {}, null, 2))
const deletePrecisions = computed(() => [...new Set(task.value?.builds.map(build => build.runtime_precision).filter(Boolean))].join(' / ') || '—')

watch([() => route.params.taskType, () => route.params.taskId], () => {
  taskScope.invalidate()
  detailPending = null
  eventDrawerOpen.value = false
  environmentOpen.value = false
  outputTab.value = 'files'
  deploying.value = false
  cancelling.value = false
  cancelDialogOpen.value = false
  cancelError.value = null
  copyStatus.value = ''
  reportError.value = null
  task.value = null
  loading.value = false
  deleting.value = false
  reportDownloading.value = false
  buildDownloading.value = ''
  deleteDialogOpen.value = false
  deleteTarget = null
  errorMessage.value = null
  void loadDetail()
}, { immediate: true, flush: 'sync' })

watch(activeTask, (active, _, onCleanup) => {
  if (!active) return
  const timer = window.setInterval(() => {
    observedAt.value = new Date().toISOString()
    if (!detailPending && !cancelling.value) void loadDetail(true)
  }, 3000)
  onCleanup(() => window.clearInterval(timer))
})

function isTerminalTask(state: string): boolean {
  return ['succeeded', 'failed', 'cancelled', 'timed_out'].includes(state)
}

async function copyErrorDetails(): Promise<void> {
  const target = taskScope.capture()
  if (!target || !errorDetails.value) return
  try {
    await navigator.clipboard.writeText(errorDetails.value)
    if (target.isCurrent()) copyStatus.value = label('已复制', 'Copied')
  } catch {
    if (target.isCurrent()) copyStatus.value = label('复制失败，可手动选择错误详情。', 'Copy failed. The error details can be selected manually.')
  }
}

async function loadDetail(background = false): Promise<void> {
  const request = taskScope.startRead('detail')
  if (!request) {
    if (taskType.value && taskId.value) return
    errorMessage.value = t('conversionDetail.messages.taskTypeRequired')
    return
  }
  detailPending = request
  if (!background) {
    loading.value = true
    errorMessage.value = null
  }
  try {
    const detail = await getModelConversionTaskDetail(request.taskType, request.taskId, request.signal)
    if (!request.isCurrent()) return
    if (task.value?.state !== detail.state && ['failed', 'timed_out'].includes(detail.state)) outputTab.value = 'error'
    if (isTerminalTask(detail.state) && !cancelling.value) cancelDialogOpen.value = false
    observedAt.value = new Date().toISOString()
    task.value = detail
  } catch (error) {
    if (request.isCurrent() && !background) errorMessage.value = error instanceof Error ? error.message : t('conversionDetail.messages.loadFailed')
  } finally {
    if (detailPending === request) detailPending = null
    if (request.isCurrent()) loading.value = false
  }
}

async function cancelConversion(): Promise<void> {
  const target = taskScope.capture()
  if (!target || !canCancel.value || cancelling.value) return
  taskScope.cancelRead('detail')
  loading.value = false
  cancelling.value = true
  cancelError.value = null
  try {
    const cancelled = await cancelTask(target.taskId)
    if (target.isCurrent()) {
      if (cancelled.state === 'cancelled' && task.value) {
        task.value = { ...task.value, state: 'cancelled',
          finished_at: typeof cancelled.finished_at === 'string' ? cancelled.finished_at : task.value.finished_at }
      }
      cancelDialogOpen.value = false
      await loadDetail()
    }
  } catch (error) {
    if (target.isCurrent()) cancelError.value = error instanceof Error ? error.message : label('取消转换失败', 'Could not cancel the conversion')
  } finally {
    if (target.isCurrent()) cancelling.value = false
  }
}

async function openDeployment(build: ModelConversionBuildSummary): Promise<void> {
  const request = taskScope.startRead('deployment-source')
  const projectId = task.value?.project_id
  const versionId = task.value?.source_model_version_id
  if (!request || !projectId || !versionId || !canDeploy.value) return
  deploying.value = true
  errorMessage.value = null
  try {
    const models = await listDeploymentSourceModels(projectId, request.taskType, request.signal)
    if (!request.isCurrent()) return
    const model = models.find(item => item.project_id === projectId && item.scope_kind === 'project'
      && item.available_versions.some(version => version.model_version_id === versionId))
    if (!model) throw new Error(label('无法读取产物所属的模型版本。', 'Could not resolve the artifact’s model version.'))
    await router.push({ path: '/deployments', query: { sourceProject: projectId, sourceModel: model.model_id, sourceVersion: versionId,
      sourceTask: request.taskType, sourceBuild: build.model_build_id } })
  } catch (error) {
    if (request.isCurrent()) errorMessage.value = error instanceof Error ? error.message : label('无法创建部署草稿。', 'Could not open the deployment draft.')
  } finally {
    if (request.isCurrent()) deploying.value = false
  }
}

function downloadLog(): void {
  if (!task.value?.events.length) return
  const body = task.value.events.map(event => `${event.created_at} [${event.event_type}] ${event.message}`).join('\n')
  saveDownload(new Blob([body + '\n'], { type: 'text/plain;charset=utf-8' }), `conversion-${task.value.task_id}.log`)
}

function saveDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function downloadReport(): Promise<void> {
  if (reportDownloading.value || !task.value || task.value.task_id !== taskId.value) return
  const request = taskScope.startRead('report-download')
  if (!request) return
  reportDownloading.value = true
  reportError.value = null
  try {
    const blob = await downloadModelConversionReport(request.taskType, request.taskId, request.signal)
    if (!request.isCurrent()) return
    saveDownload(blob, failureDetails.value ? 'conversion-diagnostic.json' : reportFilename.value)
  } catch (error) {
    if (request.isCurrent()) reportError.value = error instanceof Error ? error.message : (locale.value.startsWith('zh') ? '报告下载失败' : 'Report download failed')
  } finally {
    if (request.isCurrent()) reportDownloading.value = false
  }
}

function weightsUri(build: ModelConversionBuildSummary): string {
  const value = build.metadata?.weights_object_uri
  return typeof value === 'string' ? value : ''
}

async function downloadBuild(build: ModelConversionBuildSummary, part: 'primary' | 'weights'): Promise<void> {
  const uri = part === 'primary' ? build.build_file_uri : weightsUri(build)
  if (buildDownloading.value || !uri || !task.value || task.value.task_id !== taskId.value) return
  const request = taskScope.startRead('build-download')
  if (!request) return
  buildDownloading.value = `${build.model_build_id}:${part}`
  errorMessage.value = null
  try {
    const blob = await downloadModelConversionBuildFile(request.taskType, request.taskId, build.model_build_id, part, request.signal)
    if (!request.isCurrent()) return
    saveDownload(blob, (uri.split(/[\\/]/).pop() || 'conversion-output').replace(/[\\/:*?"<>|\x00-\x1f]/g, '_'))
  } catch (error) {
    if (request.isCurrent()) errorMessage.value = error instanceof Error ? error.message : (locale.value.startsWith('zh') ? '文件下载失败' : 'File download failed')
  } finally {
    if (request.isCurrent()) buildDownloading.value = ''
  }
}

function openDeleteDialog(): void {
  const target = taskScope.capture()
  if (!target || task.value?.task_id !== target.taskId || loading.value || deleting.value || !canWriteTasks.value || !canDeleteCurrentTask.value) return
  deleteTarget = target
  deleteError.value = null
  deleteDialogOpen.value = true
}

async function deleteCurrentTask(): Promise<void> {
  const target = deleteTarget
  if (!deleteDialogOpen.value || !target?.isCurrent() || task.value?.task_id !== target.taskId || loading.value || deleting.value || !canWriteTasks.value || !canDeleteCurrentTask.value) return

  deleting.value = true
  errorMessage.value = null
  try {
    await deleteModelConversionTask(target.taskType, target.taskId)
    if (target.isCurrent()) {
      deleteDialogOpen.value = false
      deleteTarget = null
      await router.replace(modelTaskListLocation('conversion', target.taskType, route.query))
    }
  } catch (error) {
    if (target.isCurrent()) deleteError.value = error instanceof Error ? error.message : t('conversionDetail.messages.deleteFailed')
  } finally {
    if (target.isCurrent()) deleting.value = false
  }
}
</script>

<style scoped>
.conversion-delete-scope { display:grid; gap:12px; }
.conversion-delete-scope dl { display:grid; grid-template-columns:minmax(78px, auto) minmax(0, 1fr); gap:8px 18px; margin:0; padding:14px 16px; border-radius:6px; background:var(--am-surface-soft); }
.conversion-delete-scope dt { color:var(--am-text-muted); }
.conversion-delete-scope dd { margin:0; overflow-wrap:anywhere; }
.conversion-delete-scope__impact { display:flex; align-items:flex-start; gap:14px; padding:12px 16px; border-radius:6px; }
.conversion-delete-scope__impact svg { flex:none; margin-top:2px; }
.conversion-delete-scope__impact ul { margin:4px 0 0; padding-inline-start:19px; color:var(--am-text); }
.conversion-delete-scope__impact--remove { color:var(--am-danger-text); background:var(--am-danger-surface); }
.conversion-delete-scope__impact--keep { color:var(--am-success-text); background:var(--am-success-surface); }
.conversion-detail :deep(.page-header h1) { display: block; }
.conversion-detail { gap:14px; }
.conversion-terminal-back { justify-self:start; }
.conversion-detail :deep(.page-actions > .ui-button--icon-only) { order:15; }
.conversion-cancel { color:var(--am-danger-text); border-color:var(--am-danger-border,var(--am-danger-text)); }
.conversion-cancel:hover { color:var(--am-danger-text); background:var(--am-danger-surface); }
.conversion-running-badge { gap:5px; }
.conversion-running-badge svg { animation:conversion-spinner 1.1s linear infinite; }
.conversion-terminal-title { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; min-width:0; }
.conversion-terminal-title h1 { overflow-wrap:anywhere; }
.conversion-terminal-summary, .conversion-cancelled-config { display:flex; flex-wrap:wrap; gap:12px 18px; margin:0; }
.conversion-terminal-summary { padding:14px 16px; border:1px solid var(--am-border); border-radius:var(--am-radius-md); background:var(--am-surface); }
.conversion-terminal-summary > div, .conversion-cancelled-config > div { min-width:0; }
.conversion-terminal-summary > div:not(:last-child) { padding-inline-end:18px; border-inline-end:1px solid var(--am-border); }
.conversion-terminal-summary dt, .conversion-cancelled-config dt { font-size:12px; color:var(--am-text-muted); }
.conversion-terminal-summary dd, .conversion-cancelled-config dd { display:flex; align-items:center; gap:7px; margin:4px 0 0; overflow-wrap:anywhere; }
.conversion-terminal-summary dd svg { flex:none; }
.conversion-terminal-progress { container-type:inline-size; }
.conversion-stage-timeline { display:grid; grid-auto-flow:column; grid-auto-columns:minmax(0,1fr); gap:16px; margin:0; padding:0; list-style:none; }
.conversion-stage-timeline li { position:relative; display:grid; grid-template-columns:auto minmax(0,1fr); align-items:center; align-content:center; min-width:0; min-height:74px; gap:4px 9px; padding:10px; border:1px solid var(--am-border); border-radius:var(--am-radius-md); color:var(--am-text-muted); font-size:12px; }
.conversion-stage-timeline li > span:last-child { grid-column:2; }
.conversion-stage-timeline li:not(:last-child)::after { content:''; position:absolute; width:16px; left:100%; top:26px; border-top:1px dashed var(--am-border-strong); }
.conversion-stage-timeline li.is-done:not(:last-child)::after { border-top:1px solid var(--am-brand-primary); }
.conversion-stage-timeline li strong { color:var(--am-text); overflow-wrap:anywhere; }
.conversion-stage-timeline__mark { grid-row:span 2; align-self:start; display:grid; place-items:center; width:27px; height:27px; border:1px solid var(--am-border); border-radius:50%; color:var(--am-text-muted); background:var(--am-surface-muted); }
.is-done .conversion-stage-timeline__mark { color:var(--am-brand-on-primary); background:var(--am-brand-primary); border-color:transparent; }
.is-failed .conversion-stage-timeline__mark { color:var(--am-danger-text); background:var(--am-danger-surface); }
.is-running .conversion-stage-timeline__mark { color:var(--am-success-text); background:var(--am-success-surface); }
.is-running .conversion-stage-timeline__mark svg { animation:conversion-spinner 1.1s linear infinite; }
@keyframes conversion-spinner { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .is-running .conversion-stage-timeline__mark svg, .conversion-running-badge svg { animation:none; } }
.is-cancelled .conversion-stage-timeline__mark { color:var(--am-neutral-text); background:var(--am-neutral-surface); }
.conversion-stage-timeline .is-done > span:last-child { color:var(--am-action-primary-strong); }
.conversion-stage-timeline .is-failed > span:last-child { color:var(--am-danger-text); }
.conversion-cancelled-result h3 { margin:0; }
.conversion-cancelled-note { display:flex; align-items:center; gap:14px; padding:12px 14px; border-radius:6px; background:var(--am-surface-muted); }
.conversion-cancelled-note svg { flex:none; color:var(--am-neutral-text); }
.conversion-cancelled-note p { margin:3px 0 0; color:var(--am-text-muted); }
.conversion-empty-artifacts { display:flex; align-items:center; justify-content:center; gap:8px; margin:0; padding:13px; border:1px solid var(--am-border); border-radius:6px; color:var(--am-text-muted); }
.conversion-event-log { display:grid; gap:9px; margin:0; padding:0; list-style:none; }
.conversion-event-log li { display:flex; flex-wrap:wrap; gap:4px 14px; overflow-wrap:anywhere; }
.conversion-event-log time { color:var(--am-text-muted); font-size:12px; }
@container (max-width: 785px) {
  .conversion-stage-timeline li { grid-template-columns:minmax(0,1fr); justify-items:center; text-align:center; }
  .conversion-stage-timeline__mark { grid-row:auto; }
  .conversion-stage-timeline li > span:last-child { grid-column:1; }
}
@media (max-width: 760px) {
  .conversion-stage-timeline { grid-auto-flow:row; grid-template-columns:repeat(auto-fit,minmax(90px,1fr)); row-gap:12px; }
  .conversion-stage-timeline li:not(:last-child)::after { content:none; }
}
.conversion-output { scroll-margin:12px; }
.conversion-output :deep(.local-tabs) { flex-wrap:wrap; width:100%; border-bottom:1px solid var(--am-border); }
.conversion-output :deep(.local-tabs__tab) { border-bottom:2px solid transparent; border-radius:0; }
.conversion-output :deep(.local-tabs__tab.is-active) { border-bottom-color:var(--am-brand-primary); background:transparent; }
.conversion-output :deep(table) { min-width:0; table-layout:fixed; }
.conversion-output :deep(:is(td,th)) { overflow-wrap:anywhere; white-space:normal; }
.conversion-output :deep(:is(td,th):first-child) { width:45%; }
.conversion-output :deep(:is(td,th):last-child) { width:22%; }
.conversion-output-pending { min-height:165px; display:grid; place-content:center; justify-items:center; gap:8px; padding:20px 12px; text-align:center; }
.conversion-output-pending svg, .conversion-output-pending p { color:var(--am-text-muted); }
.conversion-output-pending :is(h2,p) { margin:0; }
.conversion-file-name { display:flex; align-items:center; gap:8px; }
.conversion-file-name svg { flex:none; color:var(--am-text-muted); }
.conversion-build-actions :deep(.ui-button--ghost) { color:var(--am-action-primary-strong); }
.conversion-log-download { justify-self:start; }
.conversion-muted, .conversion-detailed-fields dt { color:var(--am-text-muted); }
.conversion-muted { margin:0; }
.conversion-detailed-fields { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; margin:0; }
.conversion-detailed-fields dd { margin:5px 0 0; overflow-wrap:anywhere; }
.conversion-failure { padding:15px; background:var(--am-danger-surface); border-radius:var(--am-radius-md); overflow-wrap:anywhere; }
.conversion-failure > div { display:flex; align-items:center; gap:10px; color:var(--am-danger-text); }
.conversion-failure h2 { margin:0; color:inherit; }
.conversion-failure p { margin:9px 0 0; white-space:pre-wrap; }
.conversion-failure details { margin-top:12px; padding:12px; border-radius:var(--am-radius-md); background:var(--am-surface); }
.conversion-error-copy { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:6px; color:var(--am-text-muted); }
.conversion-environment { display:grid; gap:12px; min-width:0; overflow-wrap:anywhere; }
.conversion-environment__checked { display:flex; gap:12px; padding:12px 14px; color:var(--am-success-text); background:var(--am-success-surface); border-radius:var(--am-radius-md); }
.conversion-environment__checked svg { flex:none; }
.conversion-environment p { margin:5px 0 0; color:var(--am-text-muted); }
.conversion-environment__group { padding:12px 14px; border:1px solid var(--am-border); border-radius:var(--am-radius-md); }
.conversion-environment__group h2 { margin:0; font-size:14px; }
.conversion-environment__group dl { margin:8px 0 0; }
.conversion-environment__group dl > div { display:grid; grid-template-columns:minmax(96px,1fr) minmax(0,2fr); gap:10px; padding:8px 0; border-top:1px solid var(--am-border); }
.conversion-environment__group dt { color:var(--am-text-muted); }
.conversion-environment__group dd { margin:0; }
.conversion-validation dl { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:16px; margin:0; }
.conversion-validation dt, .conversion-validation p { color:var(--am-text-muted); }
.conversion-validation dd { margin:8px 0 0; overflow-wrap:anywhere; }
.conversion-validation p { margin:0; font-size:12px; }
.conversion-raw-detail { display:block; min-width:0; }
.conversion-raw-detail summary { cursor:pointer; font-weight:600; }
.conversion-raw-detail .json-view { max-height:420px; overflow:auto; margin-top:12px; white-space:pre-wrap; overflow-wrap:anywhere; }
</style>
