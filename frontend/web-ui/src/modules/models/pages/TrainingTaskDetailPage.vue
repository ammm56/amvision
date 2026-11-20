<template>
  <section class="page-stack training-detail model-workspace">
    <PageHeader :title="task?.display_name || taskId">
      <template #heading>
        <ButtonLink class="training-detail-back" variant="ghost" :to="modelTaskListLocation('training', taskType || undefined, route.query)">
          <ArrowLeft :size="16" />{{ t('trainingDetail.actions.backToModels') }}
        </ButtonLink>
        <div class="training-detail-title">
          <h1>{{ task?.display_name || taskId }}</h1>
          <StatusBadge v-if="cancellingTraining" tone="warning" role="status">{{ zh ? '正在取消' : 'Cancelling' }}</StatusBadge>
          <StatusBadge v-else-if="task?.state === 'running' || task?.state === 'succeeded'" tone="success" with-dot>
            {{ t(task.state === 'running' ? 'tasks.status.running' : 'tasks.status.succeeded') }}
          </StatusBadge>
          <TaskStateBadge v-else-if="task" :state="task.state" />
        </div>
      </template>
      <template #actions>
        <ButtonLink
          v-if="task"
          :to="`/tasks/${task.task_id}`"
        >
          <Activity :size="16" />
          {{ t('trainingDetail.actions.taskStatus') }}
        </ButtonLink>
        <Button
          v-if="task && canDeleteTask"
          variant="danger"
          :disabled="loading || actionRunning !== null || cancellingTraining"
          :loading="actionRunning === 'delete'"
          @click="openDeleteDialog"
        >
          <Trash2 :size="16" />
          {{ t('trainingDetail.actions.delete') }}
        </Button>
        <Button variant="secondary" :disabled="loading" :loading="loading" @click="refreshPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
        <Button v-if="cancelledTraining || failedTraining" type="button" :disabled="loading || actionRunning !== null" @click="checkResume">
          <FileCheck :size="16" />
          {{ zh ? '检查恢复条件' : 'Check recovery conditions' }}
        </Button>
        <Button v-if="task?.state === 'succeeded' && task.model_version_id && !primaryVersionDeleted" variant="primary" :loading="linkedModelLoading" @click="openLinkedModel">
          <Box :size="16" />{{ zh ? '查看模型版本' : 'View model version' }}
        </Button>
        <ButtonLink v-if="evaluationLocation" :to="evaluationLocation"><Play :size="16" />{{ zh ? '创建评估' : 'Create evaluation' }}</ButtonLink>
        <ButtonLink v-if="trainingCopyLocation" :variant="task?.state === 'succeeded' ? 'secondary' : 'primary'" :to="trainingCopyLocation">
          <Play :size="16" />
          {{ failedTraining ? (zh ? '调整参数重新训练' : 'Adjust parameters and retrain') : (zh ? '按此配置新建训练' : 'Create training with this configuration') }}
        </ButtonLink>
        <Button v-if="visibleControlActions.includes('terminate')" class="training-terminate" size="sm" variant="danger"
          :disabled="loading || actionRunning !== null || cancellingTraining" :loading="actionRunning === 'terminate'" @click="runAction('terminate')">
          <Square :size="14" />{{ zh ? '取消训练' : 'Cancel training' }}
        </Button>
      </template>
    </PageHeader>

    <InlineError :message="errorMessage" />
    <InlineError :message="linkedModelError" />
    <InlineMessage v-if="outputVersionDeleted" tone="info" :message="zh
      ? '输出模型版本已删除。训练记录和任务目录中的文件继续保留。'
      : 'The output model version was deleted. Training history and task-owned files are retained.'" />

    <template v-if="task && cancelledTraining">
      <dl v-if="cancelledContext.length" class="training-cancelled-context">
        <div v-for="field in cancelledContext" :key="field.label">
          <dt>{{ field.label }}</dt><dd>{{ field.value }}</dd>
        </div>
      </dl>
      <p v-if="!outputVersionDeleted" class="training-cancelled-note" role="status">
        <CircleAlert :size="18" aria-hidden="true" />
        {{ task.model_version_id || task.latest_checkpoint_model_version_id
          ? (zh ? '训练已取消。已登记的模型版本可在模型目录中查看。' : 'Training was cancelled. The registered version is available in the model catalog.')
          : (zh ? '训练已取消，未登记新的模型版本。' : 'Training was cancelled before a model version was registered.') }}
      </p>
      <InlineError v-if="task.error_message" :message="task.error_message" />
      <section class="resource-section training-cancelled-progress" :aria-label="t('trainingDetail.progressTitle')">
        <div class="training-cancelled-progress__status">
          <div class="training-cancelled-progress__counts">
            <strong>{{ terminationProgress }}</strong>
            <span v-if="stoppedAtEpoch">{{ stoppedAtEpoch }}</span>
          </div>
          <TaskProgress class="training-progress--cancelled" :percent="progressPercent" compact
            :aria-label="t('trainingDetail.progressTitle')" />
        </div>
        <dl v-if="task.started_at || task.finished_at" class="training-stop-times">
          <div v-if="task.started_at"><dt>{{ zh ? '开始时间' : 'Started at' }}</dt><dd>{{ formatSystemDateTime(task.started_at) }}</dd></div>
          <div v-if="task.finished_at"><dt>{{ zh ? '结束时间' : 'Finished at' }}</dt><dd>{{ formatSystemDateTime(task.finished_at) }}</dd></div>
          <div v-if="cancelledDuration"><dt>{{ zh ? '运行时长' : 'Duration' }}</dt><dd>{{ cancelledDuration }}</dd></div>
        </dl>
      </section>
      <TrainingMetricsCharts v-if="taskType" compact
        :task-type="taskType" :train-history="trainMetricHistory" :validation-history="validationMetricHistory"
        :learning-rate-history="learningRateHistory" :runtime-history="runtimeHistory" :runtime-empty-text="runtimeHistoryEmptyText" />
      <div v-if="taskType === 'detection' && canRegisterCheckpoint" class="table-actions">
        <Button size="sm" :disabled="loading || actionRunning !== null" :loading="actionRunning === 'register-model-version'" @click="registerCheckpoint">
          <UploadCloud :size="14" />{{ t('trainingDetail.actions.registerModelVersion') }}
        </Button>
      </div>
    </template>

    <template v-if="task && !cancelledTraining">
      <dl v-if="trainingContext.length" class="training-cancelled-context">
        <div v-for="field in trainingContext" :key="field.label">
          <dt>{{ field.label }}</dt><dd>{{ field.value }}</dd>
        </div>
      </dl>
      <div v-if="failedTraining" class="training-failed-note" role="alert">
        <CircleAlert :size="20" aria-hidden="true" />
        <div>
          <strong>{{ task.error_message || (task.state === 'timed_out' ? (zh ? '训练超时。' : 'Training timed out.') : (zh ? '训练失败，暂无错误说明。' : 'Training failed. No error details were recorded.')) }}</strong>
          <p v-if="savedCheckpointFile">{{ zh ? '最新检查点' : 'Latest checkpoint' }} · {{ resumeCheckpointName }}<template v-if="latestCheckpointEpoch"> · {{ zh ? `第 ${latestCheckpointEpoch} 轮` : `Epoch ${latestCheckpointEpoch}` }}</template></p>
        </div>
      </div>
      <section class="resource-section training-overview-progress" :aria-label="t('trainingDetail.progressTitle')">
        <dl class="training-progress-facts">
          <div><dt>{{ zh ? '已完成' : 'Completed' }}</dt><dd><strong>{{ completedTrainingEpoch ?? '—' }}</strong><template v-if="totalTrainingEpochs"> / {{ totalTrainingEpochs }}</template> {{ zh ? '轮' : 'epochs' }}</dd></div>
          <div v-if="activeEpoch"><dt>{{ epochLabel }}</dt><dd>{{ activeEpoch }}</dd></div>
          <div v-if="batchText"><dt>{{ zh ? '当前批次' : 'Current batch' }}</dt><dd>{{ batchText }}</dd></div>
          <div v-if="estimatedDuration"><dt>{{ zh ? '预计剩余' : 'Estimated remaining' }}</dt><dd>{{ estimatedDuration }}</dd></div>
          <div v-if="failedTraining && task.started_at"><dt>{{ zh ? '开始时间' : 'Started at' }}</dt><dd>{{ formatSystemDateTime(task.started_at) }}</dd></div>
          <div v-if="task.finished_at"><dt>{{ task.state === 'succeeded' ? (zh ? '完成时间' : 'Completed at') : (zh ? '结束时间' : 'Finished at') }}</dt><dd>{{ formatSystemDateTime(task.finished_at) }}</dd></div>
          <div v-if="cancelledDuration"><dt>{{ zh ? '运行时长' : 'Duration' }}</dt><dd>{{ cancelledDuration }}</dd></div>
        </dl>
        <TaskProgress :percent="progressPercent" compact :class="{ 'training-progress--failed': failedTraining }"
          :indeterminate="isActiveTrainingState(task.state)" :aria-label="t('trainingDetail.progressTitle')" />
      </section>
      <TrainingMetricsCharts v-if="taskType" compact :task-type="taskType" :train-history="completedTrainHistory"
        :validation-history="completedValidationHistory" :learning-rate-history="learningRateHistory" :runtime-history="runtimeHistory"
        :runtime-empty-text="runtimeHistoryEmptyText" :best-epoch="bestCheckpointEpoch" :primary-metric="task.best_metric_name" />
    </template>

    <section v-if="task" class="resource-section training-output-section">
      <TabList :model-value="cancelledOutputTab" :tabs="cancelledOutputTabs" :label="t('trainingDetail.outputsTitle')" @update:model-value="selectOutputTab" />
      <InlineError :message="outputDownloadError" />
      <div v-if="cancelledTraining && cancelledOutputTab === 'events'" role="tabpanel" :aria-label="zh ? '运行日志' : 'Run log'">
        <ol v-if="task.events.length" class="training-run-log">
          <li v-for="event in task.events" :key="event.event_id">
            <time :datetime="event.created_at">{{ formatSystemDateTime(event.created_at) }}</time>
            <span>{{ event.message || event.event_type }}</span>
          </li>
        </ol>
        <EmptyState v-else :title="zh ? '暂无运行记录' : 'No run events recorded'" />
      </div>
      <div v-else-if="cancelledOutputTab === 'parameters'" role="tabpanel" :aria-label="zh ? '参数' : 'Parameters'">
        <pre class="json-view training-saved-parameters">{{ JSON.stringify(task.task_spec, null, 2) }}</pre>
      </div>
      <EmptyState v-else-if="outputFiles.length === 0" :title="t('trainingDetail.emptyOutputsTitle')" :description="t('trainingDetail.emptyOutputsDescription')" />
      <div v-else class="training-output-layout">
        <div class="resource-table">
          <table>
            <colgroup><col style="width:25%"><col style="width:14%"><col style="width:10%"><col style="width:8%"><col style="width:19%"><col style="width:24%"></colgroup>
            <thead>
              <tr>
                <th>{{ t('trainingDetail.columns.file') }}</th>
                <th>{{ zh ? '类型' : 'Type' }}</th>
                <th>{{ t('trainingDetail.columns.size') }}</th>
                <th>{{ zh ? '轮次' : 'Epoch' }}</th>
                <th>{{ t('trainingDetail.columns.updatedAt') }}</th>
                <th>{{ t('trainingDetail.outputActions') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="file in outputFiles"
                :key="file.file_name"
                :class="{ 'is-selected': file.file_name === selectedOutputFileName }"
                @click="!loading && file.file_status === 'ready' && file.file_kind !== 'checkpoint' && (selectOutputFile(file.file_name), outputPreviewOpen = true)"
              >
                <td>
                  <strong>{{ file.object_key?.split('/').pop() || file.file_name }}</strong>
                  <span v-if="file.file_status !== 'ready'"><StatusBadge :tone="statusTone(file.file_status)">{{ file.file_status }}</StatusBadge></span>
                </td>
                <td>{{ file.file_kind === 'checkpoint' ? (zh ? '权重' : 'Weights') : file.file_kind === 'text' ? (zh ? '文本' : 'Text') : 'JSON' }}</td>
                <td>{{ formatOutputSize(file.size_bytes) }}</td>
                <td>{{ outputFileEpoch(file.file_name) ?? '—' }}</td>
                <td>{{ formatSystemDateTime(file.updated_at) }}</td>
                <td><Button size="sm" variant="ghost" :disabled="loading || file.file_status !== 'ready' || file.file_kind === 'checkpoint'" @click.stop="selectOutputFile(file.file_name); outputPreviewOpen = true">{{ t('trainingDetail.outputPreviewTitle') }}</Button><Button size="sm" variant="ghost" :disabled="loading || file.file_status !== 'ready' || !!outputDownloading" :loading="outputDownloading === file.file_name" @click.stop="downloadOutput(file)">{{ t('trainingDetail.actions.download') }}</Button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <details class="training-output-preview" :open="outputPreviewOpen" @toggle="outputPreviewOpen = ($event.target as HTMLDetailsElement).open">
          <summary>{{ selectedOutputFile?.file_name || t('trainingDetail.outputPreviewTitle') }}</summary>
          <pre class="json-view">{{ selectedOutputContent || t('trainingDetail.messages.noOutputContent') }}</pre>
        </details>
      </div>
    </section>

    <details v-if="task && !cancelledTraining" class="resource-section training-more" @toggle="detailedChartsOpen = ($event.target as HTMLDetailsElement).open">
      <summary>{{ zh ? '任务状态与详细指标' : 'Status and detailed metrics' }}</summary>
      <section>
      <div class="section-heading">
        <div>
          <h2>{{ t('trainingDetail.summaryTitle') }}</h2>
        </div>
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('trainingDetail.fields.datasetExportId') }}</span>
          <strong>{{ task.dataset_export_id || '-' }}</strong>
        </div>
        <div>
          <span>{{ zh ? '模型版本' : 'Model version' }}</span>
          <strong>{{ outputVersionName || (outputVersionDeleted ? (zh ? '已删除' : 'Deleted') : outputVersionRegistered ? (zh ? '已登记' : 'Registered') : '—') }}</strong>
        </div>
        <div>
          <span>{{ t('trainingDetail.fields.bestMetric') }}</span>
          <strong>{{ task.best_metric_name ? `${task.best_metric_name}: ${formatMetricValue(task.best_metric_value)}` : '-' }}</strong>
        </div>
        <div>
          <span>{{ t('trainingDetail.fields.controlStatus') }}</span>
          <strong>{{ task.control_status.status }}</strong>
        </div>
      </div>
      <div class="table-actions table-actions--wrap">
        <Button
          v-for="action in detailControlActions"
          :key="action"
          size="sm"
          variant="secondary"
          :disabled="loading || actionRunning !== null || cancellingTraining"
          :loading="actionRunning === action"
          @click="runAction(action)"
        >
          <component :is="actionIcon(action)" :size="14" />
          {{ t(`trainingDetail.actions.${action}`) }}
        </Button>
        <Button
          v-if="taskType === 'detection'"
          size="sm"
          variant="secondary"
          :disabled="loading || !canRegisterCheckpoint || actionRunning !== null"
          :loading="actionRunning === 'register-model-version'"
          @click="registerCheckpoint"
        >
          <UploadCloud :size="14" />
          {{ t('trainingDetail.actions.registerModelVersion') }}
        </Button>
      </div>
      </section>

    <section class="training-progress-section">
      <div class="summary-grid training-progress-grid">
        <div>
          <span>{{ t('trainingDetail.fields.stage') }}</span>
          <TaskStateBadge v-if="progressStage !== '-'" :state="progressStage" />
          <strong v-else>-</strong>
        </div>
        <div>
          <span>{{ t('trainingDetail.fields.epoch') }}</span>
          <strong>{{ progressEpochText }}</strong>
        </div>
        <div>
          <span>{{ t('trainingDetail.fields.learningRate') }}</span>
          <strong>{{ learningRateText }}</strong>
        </div>
        <div>
          <span>{{ t('trainingDetail.fields.currentMetric') }}</span>
          <strong>{{ currentMetricText }}</strong>
        </div>
        <div v-if="bestMetricText !== '-'">
          <span>{{ t('trainingDetail.fields.bestMetric') }}</span><strong>{{ bestMetricText }}</strong>
        </div>
        <div v-if="actualOptimizerText !== '-'">
          <span>{{ t('trainingDetail.fields.optimizer') }}</span>
          <strong>{{ actualOptimizerText }}</strong>
        </div>
        <div v-if="initialLearningRateText !== '-'">
          <span>{{ t('trainingDetail.fields.initialLearningRate') }}</span>
          <strong>{{ initialLearningRateText }}</strong>
        </div>
        <div v-if="finalLearningRateText !== '-'">
          <span>{{ t('trainingDetail.fields.finalLearningRate') }}</span>
          <strong>{{ finalLearningRateText }}</strong>
        </div>
      </div>
      <details class="training-metrics-details">
      <summary>{{ t('trainingDetail.completedEpochMetricsTitle') }}</summary>
      <div class="training-metric-panels">
        <article class="training-metric-panel">
          <div>
            <h3>{{ t('trainingDetail.completedEpochMetricsTitle') }}</h3>
            <p class="training-metric-hint">{{ t('trainingDetail.completedEpochMetricsHint') }}</p>
            <p v-if="showsYoloSpatialLossHint" class="training-metric-hint">
              {{ t('trainingDetail.yoloLossComponentsHint') }}
            </p>
          </div>
          <dl v-if="trainMetricEntries.length > 0" class="training-metric-list">
            <template v-for="metric in trainMetricEntries" :key="metric.name">
              <dt>{{ metric.name }}</dt>
              <dd>{{ metric.value }}</dd>
            </template>
          </dl>
          <span v-else class="training-muted-value">-</span>
        </article>
        <article v-if="batchMetricEntries.length > 0" class="training-metric-panel">
          <div>
            <h3>{{ t('trainingDetail.currentBatchMetricsTitle') }}</h3>
            <p class="training-metric-hint">{{ t('trainingDetail.currentBatchMetricsHint') }}</p>
          </div>
          <dl class="training-metric-list">
            <template v-for="metric in batchMetricEntries" :key="metric.name">
              <dt>{{ metric.name }}</dt>
              <dd>{{ metric.value }}</dd>
            </template>
          </dl>
        </article>
        <article class="training-metric-panel">
          <h3>{{ t('trainingDetail.validationMetricsTitle') }}</h3>
          <dl v-if="validationMetricEntries.length > 0" class="training-metric-list">
            <template v-for="metric in validationMetricEntries" :key="metric.name">
              <dt>{{ metric.name }}</dt>
              <dd>{{ metric.value }}</dd>
            </template>
          </dl>
          <span v-else class="training-muted-value">-</span>
        </article>
        <article v-if="runtimeMetricEntries.length > 0" class="training-metric-panel">
          <div>
            <h3>{{ t('trainingDetail.runtimeMetricsTitle') }}</h3>
            <p class="training-metric-hint">{{ t('trainingDetail.runtimeMetricsHint') }}</p>
          </div>
          <dl class="training-metric-list">
            <template v-for="metric in runtimeMetricEntries" :key="metric.name">
              <dt>{{ metric.name }}</dt>
              <dd>{{ metric.value }}</dd>
            </template>
          </dl>
        </article>
      </div>
      </details>
      <div class="training-chart-heading">
        <div>
          <h3>{{ t('trainingDetail.charts.title') }}</h3>
          <p>{{ t('trainingDetail.charts.description') }}</p>
        </div>
        <StatusBadge :tone="trainingStreamConnected ? 'success' : 'neutral'">
          {{ trainingStreamConnected ? t('trainingDetail.charts.live') : t('trainingDetail.charts.snapshot') }}
        </StatusBadge>
      </div>
      <p
        v-if="runtimeHistory.length === 0"
        class="training-metric-hint training-runtime-history-status"
      >
        {{ runtimeHistoryEmptyText }}
      </p>
      <TrainingMetricsCharts
        v-if="taskType && detailedChartsOpen"
        :task-type="taskType"
        :train-history="trainMetricHistory"
        :validation-history="validationMetricHistory"
        :learning-rate-history="learningRateHistory"
        :runtime-history="runtimeHistory"
        :runtime-empty-text="runtimeHistoryEmptyText"
      />
    </section>
    </details>

    <TrainingRunLog v-if="task && !cancelledTraining" :open="runLogOpen" :task-id="task.task_id" :task-name="task.display_name"
      :events="task.events" :live="taskEvents.streamState.value?.connected === true" :zh="zh" @close="runLogOpen = false" />

    <SideDrawer
      :open="resumeDialogOpen"
      size="compact"
      :title="locale.startsWith('zh') ? '恢复训练检查' : 'Review training recovery'"
      :close-label="zh ? '关闭' : 'Close'"
      :busy="actionRunning === 'resume'"
      @close="closeResumeDialog"
    >
      <div class="training-resume">
        <p v-if="resumeChecking" role="status">{{ zh ? '正在检查原数据集和检查点…' : 'Checking the original dataset and checkpoint…' }}</p>
        <div v-else-if="resumeError" class="training-resume__warning" role="alert">
          <CircleAlert :size="18" aria-hidden="true" />
          <div><strong>{{ zh ? '无法恢复原训练状态' : 'Training cannot be resumed' }}</strong><p>{{ resumeError }}</p></div>
        </div>
        <h3>{{ task?.display_name || taskId }}</h3>
        <dl class="training-resume-summary">
          <dt>{{ zh ? '训练进度' : 'Training progress' }}</dt><dd>{{ terminationProgress }}</dd>
          <dt>{{ zh ? '检查点' : 'Checkpoint' }}</dt><dd>{{ resumeCheckpointName }}</dd>
          <dt>{{ zh ? '数据集导出' : 'Dataset export' }}</dt><dd>{{ resumePreview?.dataset_export_id || task?.dataset_export_id || '—' }}</dd>
        </dl>
        <div class="resource-table training-resume__checks">
          <table>
            <thead><tr><th scope="col">{{ zh ? '检查项' : 'Check' }}</th><th scope="col">{{ zh ? '状态' : 'Status' }}</th></tr></thead>
            <tbody><tr v-for="row in resumeRows" :key="row.key"><th scope="row">{{ row.label }}</th><td :class="{ 'training-resume__unavailable': row.key === resumeBlockedAt && row.key !== 'task' }">{{ row.status }}</td></tr></tbody>
          </table>
        </div>
        <p v-if="!cancelledTraining">{{ zh ? 'Worker 在恢复时验证检查点中的优化器、调度器与轮次状态。' : 'The worker verifies optimizer, scheduler and epoch state when resuming.' }}</p>
      </div>
      <template #footer>
        <div class="training-resume__actions">
          <Button type="button" :disabled="actionRunning === 'resume'" @click="closeResumeDialog">{{ zh ? '关闭' : 'Close' }}</Button>
          <Button v-if="resumeError && !cancelledTraining" type="button" @click="checkResume">{{ zh ? '重新检查' : 'Check again' }}</Button>
          <Button v-if="!cancelledTraining" type="button" variant="primary" :loading="actionRunning === 'resume'"
            :disabled="!resumePreview || !!resumeError || !task?.available_actions.includes('resume') || actionRunning === 'resume'" @click="runAction('resume', true)"
          >{{ zh ? '恢复训练' : 'Resume training' }}</Button>
        </div>
      </template>
    </SideDrawer>

    <ConfirmDialog
      v-if="terminateDialogOpen"
      :title="zh ? '取消训练？' : 'Cancel training?'"
      :message="zh ? '将请求停止当前训练。已写入的检查点和日志会保留；取消本身不会登记新的模型版本。' : 'This requests a stop. Saved checkpoints and logs are kept. Cancelling does not register a new model version.'"
      :details="task?.state === 'running' ? (zh ? '确认后显示正在取消，执行器确认停止后显示已取消。' : 'The task first shows Cancelling, then Cancelled once the worker stops.') : undefined"
      :confirm-label="zh ? '取消训练' : 'Cancel training'"
      :cancel-label="zh ? '继续训练' : 'Keep training'"
      :busy="actionRunning === 'terminate'"
      :confirm-disabled="cancellingTraining || !task?.available_actions.includes('terminate')"
      @cancel="closeTerminateDialog"
      @confirm="runAction('terminate', true)"
    >
      <template #title-icon><CircleAlert class="training-stop-icon" :size="23" /></template>
      <dl class="training-stop-summary">
        <div><dt>{{ zh ? '任务' : 'Task' }}</dt><dd>{{ task?.display_name || taskId }}</dd></div>
        <div><dt>{{ zh ? '进度' : 'Progress' }}</dt><dd>{{ terminationProgress }}</dd></div>
      </dl>
      <InlineError v-if="terminateError" :message="terminateError" />
    </ConfirmDialog>

    <ConfirmDialog
      v-if="deleteDialogOpen"
      :title="t('trainingDetail.deleteDialog.title')"
      :message="t('common.confirmDelete')"
      :details="t('trainingDetail.messages.confirmDelete')"
      :confirm-label="t('trainingDetail.actions.delete')"
      :cancel-label="t('common.cancel')"
      :busy="actionRunning === 'delete'"
      :confirm-disabled="loading || !canDeleteTask"
      confirm-variant="danger"
      @cancel="deleteDialogOpen = false"
      @confirm="deleteCurrentTask"
    />
  </section>
</template>

<script setup lang="ts">
import { useCatalogVersionLabel } from '../composables/useCatalogVersionLabel'
import { formatLearningRate, formatModelNumber } from '../model-number-format'
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue'
import { Activity, ArrowLeft, Box, CircleAlert, FileCheck, Pause, Play, RefreshCw, Save, Square, Trash2, UploadCloud } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { modelTaskListLocation } from '../model-task-navigation'
import { isDeletedTrainingVersion } from '../model-version-action'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '@/app/stores/session.store'

import {
  deleteModelTrainingTask,
  downloadModelTrainingOutputFile,
  getModelTrainingOutputFileDetail,
  getModelTrainingTaskDetail,
  listModelTrainingOutputFiles,
  listDeploymentSourceModels,
  registerModelTrainingLatestCheckpoint,
  requestModelTrainingTaskAction,
  previewModelTrainingResume,
  type ModelTrainingOutputFileDetail,
  type ModelTrainingOutputFileSummary,
  type ModelTrainingTaskActionName,
  type ModelTrainingTaskDetail,
  type ModelTaskType,
} from '../services/model.service'
import Button from '@/shared/ui/components/Button.vue'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import { ApiError } from '@/shared/api/error'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import PageHeader from '@/shared/ui/layout/PageHeader.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'
import TrainingRunLog from '../components/TrainingRunLog.vue'
import { getDatasetExportDetail } from '@/modules/datasets/services/dataset.service'
import { getDatasetWorkspace } from '@/modules/datasets/services/dataset-workspace.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import TaskProgress from '@/modules/tasks/components/TaskProgress.vue'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import { useTaskEvents } from '@/modules/tasks/composables/useTaskEvents'
import type { TaskEvent } from '@/shared/contracts'
import { useModelTaskScope, type ModelTaskTarget } from '../composables/useModelTaskScope'
import {
  useTrainingTelemetry,
  type TrainingTelemetryPayload,
} from '../composables/useTrainingTelemetry'
import {
  appendTrainingMetricPoint,
  appendTrainingRuntimePoint,
  appendTrainingScalarPoint,
  buildLearningRatePointFromProgress,
  buildMetricPointFromProgress,
  buildRuntimePoint,
  readPersistedLearningRateHistory,
  readPersistedMetricHistory,
  readPersistedRuntimeHistory,
  type TrainingMetricPoint,
  type TrainingRuntimePoint,
  type TrainingScalarPoint,
} from '../training-metric-history'

const TrainingMetricsCharts = defineAsyncComponent(
  () => import('../components/TrainingMetricsCharts.vue'),
)

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()

const task = ref<ModelTrainingTaskDetail | null>(null)
const outputVersionName = useCatalogVersionLabel(() => [task.value?.project_id, String(route.params.taskType ?? ''), task.value?.model_version_id || task.value?.latest_checkpoint_model_version_id])
const primaryVersionDeleted = computed(() => isDeletedTrainingVersion(task.value, task.value?.model_version_id))
const outputVersionDeleted = computed(() => isDeletedTrainingVersion(task.value, task.value?.model_version_id || task.value?.latest_checkpoint_model_version_id))
const outputVersionRegistered = computed(() => !!(task.value?.model_version_id || task.value?.latest_checkpoint_model_version_id))
const outputFiles = ref<ModelTrainingOutputFileSummary[]>([])
const selectedOutputFile = ref<ModelTrainingOutputFileDetail | null>(null)
const selectedOutputFileName = ref<string | null>(null)
const outputPreviewOpen = ref(false)
const outputDownloading = ref('')
const outputDownloadError = ref<string | null>(null)
function formatOutputSize(size: number | null | undefined): string {
  if (size == null || !Number.isFinite(size)) return '—'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
const loading = ref(false)
const actionRunning = ref<string | null>(null)
const deleteDialogOpen = ref(false)
const resumeDialogOpen = ref(false)
const terminateDialogOpen = ref(false)
const terminateError = ref<string | null>(null)
const terminateRequested = ref(false)
const resumeChecking = ref(false)
const resumeError = ref('')
const resumePreview = ref<Awaited<ReturnType<typeof previewModelTrainingResume>> | null>(null)
const resumeBlockedAt = ref<'task' | 'checkpoint' | 'dataset' | null>(null)
let resumeRequest: AbortController | null = null
const errorMessage = ref<string | null>(null)
const trainingMetricsPayload = ref<Record<string, unknown>>({})
const validationMetricsPayload = ref<Record<string, unknown>>({})
const runtimeMetricsPayload = ref<Record<string, unknown>>({})
const trainMetricHistory = ref<TrainingMetricPoint[]>([])
const validationMetricHistory = ref<TrainingMetricPoint[]>([])
const learningRateHistory = ref<TrainingScalarPoint[]>([])
const runtimeHistory = ref<TrainingRuntimePoint[]>([])
const latestTaskEventCursor = ref<string | null>(null)
let snapshotRefreshTimer: ReturnType<typeof window.setTimeout> | null = null
let outputFilesRefreshTimer: ReturnType<typeof window.setTimeout> | null = null
let cancellationRefreshTimer: ReturnType<typeof window.setTimeout> | null = null

const taskId = computed(() => String(route.params.taskId ?? ''))
const taskType = computed<ModelTaskType | null>(() => {
  const value = String(route.params.taskType ?? '')
  return ['detection', 'classification', 'segmentation', 'pose', 'obb'].includes(value)
    ? value as ModelTaskType
    : null
})
const taskScope = useModelTaskScope(() => taskType.value, () => taskId.value)
let deleteTarget: ModelTaskTarget | null = null
const zh = computed(() => locale.value.startsWith('zh'))
const sessionStore = useSessionStore()
const trainingCopyLocation = computed(() => {
  const source = task.value
  if (!taskType.value || source?.task_id !== taskId.value || !['cancelled', 'failed', 'timed_out', 'succeeded'].includes(source.state)
    || !sessionStore.hasScopes(['models:read', 'tasks:read', 'tasks:write'])) return null
  return { path: '/models', query: { tab: 'training', task: taskType.value, trainingFrom: source.task_id } }
})
const cancelledTraining = computed(() => task.value?.state === 'cancelled')
const failedTraining = computed(() => ['failed', 'timed_out'].includes(task.value?.state ?? ''))
const epochLabel = computed(() => {
  if (task.value?.state === 'timed_out') return zh.value ? '超时轮次' : 'Timed-out epoch'
  return failedTraining.value ? (zh.value ? '失败轮次' : 'Failed epoch') : (zh.value ? '当前轮次' : 'Current epoch')
})
const cancelledOutputTab = ref('files')
const runLogOpen = ref(false)
const detailedChartsOpen = ref(false)
const linkedModelLoading = ref(false)
const linkedModelError = ref('')
const trainingDatasetName = ref('')
const trainingDatasetSplits = ref<Record<string, unknown>>({})
const cancelledOutputTabs = computed(() => [
  { id: 'files', label: zh.value ? '输出文件' : 'Output files' },
  { id: 'events', label: zh.value ? '运行日志' : 'Run log' },
  { id: 'parameters', label: zh.value ? '参数' : 'Parameters' },
])
const cancelledContext = computed(() => {
  const spec = task.value?.task_spec ?? {}
  const input = readRecord(spec.input_size)
  const options = readRecord(spec.extra_options)
  const device = options.resolved_device || options.requested_device || options.device
  const splits = readRecord(task.value?.training_summary?.split_counts)
  const splitCounts = ['train', 'val', 'test'].flatMap(name => {
    const count = readNumber(splits[name])
    return count === null ? [] : [`${name} ${count.toLocaleString(locale.value)}`]
  }).join(' / ')
  return [
    { label: zh.value ? '数据集导出' : 'Dataset export', value: task.value?.dataset_export_id },
    { label: zh.value ? '数据划分' : 'Dataset splits', value: splitCounts },
    { label: zh.value ? '训练设备' : 'Device', value: typeof device === 'string' ? device : '' },
    { label: zh.value ? '输入尺寸' : 'Input size', value: readNumber(input.width) && readNumber(input.height) ? `${input.width} × ${input.height}` : '' },
  ].filter(field => field.value)
})
const trainingContext = computed(() => {
  const summary = task.value?.training_summary ?? {}
  const spec = task.value?.task_spec ?? {}
  const config = readRecord(summary.training_config)
  const options = readRecord(spec.extra_options)
  const input = readRecord(summary.input_size ?? config.input_size ?? spec.input_size)
  const device = summary.device ?? config.device ?? options.device ?? options.requested_device
  const splitCounts = { ...trainingDatasetSplits.value, ...readRecord(summary.split_counts) }
  const trainCount = readNumber(summary.training_sample_count)
  const valCount = readNumber(readRecord(summary.validation).sample_count)
  const splits = [
    ['train', trainCount ?? readNumber(splitCounts.train)],
    ['val', valCount ?? readNumber(splitCounts.val)],
    ['test', readNumber(splitCounts.test)],
  ].filter((entry): entry is [string, number] => typeof entry[1] === 'number')
    .map(([name, count]) => `${name} ${count.toLocaleString(locale.value)}`).join(' / ')
  return [
    { label: zh.value ? '数据集版本' : 'Dataset version', value: trainingDatasetName.value || task.value?.dataset_export_id },
    { label: zh.value ? '数据划分' : 'Dataset splits', value: splits },
    { label: zh.value ? '训练设备' : 'Device', value: typeof device === 'string' ? device : '' },
    { label: zh.value ? '输入尺寸' : 'Input size', value: readNumber(input.width) && readNumber(input.height) ? `${input.width} × ${input.height}` : '' },
  ].filter(field => field.value)
})
watch([() => task.value?.project_id, () => task.value?.dataset_export_id, cancelledTraining], async ([projectId, exportId, cancelled], _, onCleanup) => {
  trainingDatasetName.value = ''
  trainingDatasetSplits.value = {}
  if (!projectId || !exportId || cancelled || !sessionStore.hasScopes(['datasets:read'])) return
  const request = new AbortController()
  onCleanup(() => request.abort())
  try {
    const data = await getDatasetExportDetail(exportId, request.signal)
    if (request.signal.aborted || data.project_id !== projectId) return
    trainingDatasetName.value = data.display_name ?? ''
    trainingDatasetSplits.value = readRecord(data.metadata.split_counts ?? data.metadata.split_sample_counts)
    const version = await getDatasetWorkspace(data.dataset_id, data.dataset_version_id, request.signal)
    if (!request.signal.aborted && version.project_id === projectId) {
      trainingDatasetName.value = `${version.dataset.display_name} · v${version.version_number}`
    }
  } catch { /* 历史导出不可读时保留训练任务保存的引用。 */ }
})
const evaluationLocation = computed(() => {
  const source = task.value
  if (taskType.value !== 'detection' || source?.state !== 'succeeded' || !source.model_version_id || primaryVersionDeleted.value
    || !sessionStore.hasScopes(['models:read', 'datasets:read', 'tasks:read', 'tasks:write'])) return null
  return { path: '/models', query: { tab: 'evaluation', evaluation: 'detection', evaluationFrom: source.model_version_id, datasetFrom: source.dataset_export_id ?? undefined } }
})
function selectOutputTab(tab: string): void {
  if (tab === 'events' && !cancelledTraining.value) {
    runLogOpen.value = true
    return
  }
  cancelledOutputTab.value = tab
}
async function openLinkedModel(): Promise<void> {
  const request = taskScope.startRead('linked-model')
  const versionId = task.value?.model_version_id
  const projectId = task.value?.project_id
  if (!request || !versionId || !projectId || primaryVersionDeleted.value) return
  linkedModelLoading.value = true
  linkedModelError.value = ''
  try {
    const models = await listDeploymentSourceModels(projectId, request.taskType, request.signal)
    if (!request.isCurrent()) return
    const model = models.find(item => item.project_id === projectId && item.scope_kind === 'project'
      && item.available_versions.some(version => version.model_version_id === versionId))
    if (!model) throw new Error('model not found')
    await router.push({ path: '/models', query: { tab: 'versions', model: model.model_id, version: versionId } })
  } catch {
    if (request.isCurrent()) linkedModelError.value = zh.value ? '无法读取训练登记的模型版本。' : 'Could not open the registered model version.'
  } finally { if (request.isCurrent()) linkedModelLoading.value = false }
}
const cancellingTraining = computed(() => Boolean(task.value
  && (isActiveTrainingState(task.value.state) || task.value.state === 'paused')
  && (terminateRequested.value || task.value.control_status.pending_action === 'terminate')))
const completedTrainingEpoch = computed(() => (
  readNumber(progressSnapshot.value.completed_epoch)
    ?? readNumber(completedEpochMetrics.value.epoch)
    ?? trainMetricHistory.value.at(-1)?.epoch
    ?? (task.value?.state === 'succeeded' ? readNumber(progressSnapshot.value.epoch) : null)
    ?? null
))
const totalTrainingEpochs = computed(() => readNumber(progressSnapshot.value.max_epochs) ?? readNumber(task.value?.task_spec.max_epochs))
const terminationProgress = computed(() => {
  const completed = completedTrainingEpoch.value
  const total = totalTrainingEpochs.value
  if (completed === null) return '—'
  const count = total == null ? `${completed}` : `${completed} / ${total}`
  return zh.value ? `已完成 ${count} 轮` : `${count} epochs completed`
})
const stoppedAtEpoch = computed(() => {
  const epoch = readNumber(progressSnapshot.value.epoch)
  const completed = completedTrainingEpoch.value
  if (epoch === null || completed !== null && epoch <= completed) return ''
  return zh.value ? `停止在第 ${epoch} 轮` : `Stopped in epoch ${epoch}`
})
const cancelledDuration = computed(() => {
  const start = Date.parse(task.value?.started_at ?? '')
  const end = Date.parse(task.value?.finished_at ?? '')
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return ''
  return formatDuration(Math.round((end - start) / 1000))
})
function formatDuration(seconds: number): string {
  const units = [
    { value: Math.floor(seconds / 3600), unit: 'hour' },
    { value: Math.floor(seconds / 60) % 60, unit: 'minute' },
    { value: seconds % 60, unit: 'second' },
  ]
  return units.filter(({ value, unit }) => value > 0 || (seconds === 0 && unit === 'second'))
    .map(({ value, unit }) => new Intl.NumberFormat(locale.value, { style: 'unit', unit, unitDisplay: 'short' }).format(value))
    .join(' ')
}
const resumeCheckpointName = computed(() => {
  const key = task.value?.control_status.resume_checkpoint_object_key || task.value?.latest_checkpoint_object_key
  return resumePreview.value?.checkpoint_name || key?.split(/[\\/]/).pop() || '—'
})
const resumeRows = computed(() => {
  const unavailable = zh.value ? '不可用' : 'Unavailable'
  const pending = zh.value ? '待确认' : 'Unconfirmed'
  const allowed = task.value?.available_actions.includes('resume') && resumeBlockedAt.value !== 'task' && !cancelledTraining.value
  return [
    { key: 'task', label: zh.value ? '任务状态' : 'Task state', status: allowed ? (zh.value ? '允许检查恢复' : 'Eligible for recovery checks') : unavailable },
    { key: 'checkpoint', label: zh.value ? '权重文件' : 'Checkpoint file',
      status: resumeBlockedAt.value === 'checkpoint' ? unavailable : resumePreview.value || resumeBlockedAt.value === 'dataset' ? (zh.value ? '可读取' : 'Readable') : pending },
    { key: 'dataset', label: zh.value ? '原数据集导出' : 'Original dataset export',
      status: resumeBlockedAt.value === 'dataset' ? unavailable : resumePreview.value ? (zh.value ? '可用' : 'Available') : pending },
  ]
})
const visibleControlActions = computed(() => task.value?.available_actions.filter((action) => action !== 'delete') ?? [])
const detailControlActions = computed(() => visibleControlActions.value.filter(action => action !== 'terminate'))
const showsYoloSpatialLossHint = computed(() => (
  ['yolov8', 'yolo11', 'yolo26'].includes(String(task.value?.model_type ?? '').toLowerCase())
  && ['detection', 'segmentation', 'pose', 'obb'].includes(String(taskType.value ?? ''))
))
const canDeleteTask = computed(() => task.value?.available_actions.includes('delete') ?? false)
const canRegisterCheckpoint = computed(() => Boolean(task.value?.latest_checkpoint_object_key || task.value?.control_status.resume_checkpoint_object_key))
const progressSnapshot = computed(() => task.value?.progress ?? {})
const progressPercent = computed(() => {
  const completed = completedTrainingEpoch.value
  const total = totalTrainingEpochs.value
  if (completed !== null && total && total > 0) return completed / total * 100
  return readNumber(progressSnapshot.value.percent)
})
const activeEpoch = computed(() => {
  if (task.value?.state === 'succeeded') return null
  const epoch = readNumber(progressSnapshot.value.epoch)
  return epoch !== null && (completedTrainingEpoch.value === null || epoch > completedTrainingEpoch.value) ? epoch : null
})
const batchText = computed(() => {
  const batch = readNumber(progressSnapshot.value.batch)
  const total = readNumber(progressSnapshot.value.total_batches)
  return activeEpoch.value !== null && batch !== null && total ? `${batch} / ${total}` : ''
})
const estimatedDuration = computed(() => {
  if (task.value?.state !== 'running') return ''
  const seconds = readNumber(progressSnapshot.value.estimated_remaining_seconds)
    ?? readNumber(readRecord(progressSnapshot.value.runtime).estimated_remaining_seconds)
  return seconds !== null && seconds > 0 ? formatDuration(Math.round(seconds)) : ''
})
const completedTrainHistory = computed(() => trainMetricHistory.value.filter(point => completedTrainingEpoch.value === null || point.epoch <= completedTrainingEpoch.value))
const completedValidationHistory = computed(() => validationMetricHistory.value.filter(point => completedTrainingEpoch.value === null || point.epoch <= completedTrainingEpoch.value))
const bestCheckpointEpoch = computed(() => {
  const recorded = readNumber(progressSnapshot.value.best_checkpoint_saved_epoch) ?? task.value?.events
    .map(event => readNumber(readRecord(event.payload.progress).best_checkpoint_saved_epoch))
    .filter(value => value !== null).at(-1)
  if (recorded != null) return recorded
  const name = task.value?.best_metric_name
  const value = task.value?.best_metric_value
  if (!name || value == null) return undefined
  const matches = completedValidationHistory.value.filter(point => (point.metrics[name] ?? point.metrics[name.replace(/^val[_/]/, '')]) === value)
  return matches.length === 1 ? matches[0].epoch : undefined
})
const latestCheckpointEpoch = computed(() => readNumber(task.value?.training_summary.latest_checkpoint_epoch)
  ?? readNumber(task.value?.result.latest_checkpoint_epoch) ?? readNumber(task.value?.control_status.last_save_epoch))
const savedCheckpointFile = computed(() => outputFiles.value.find(file => file.file_name === 'latest-checkpoint' && file.file_status === 'ready'))
function outputFileEpoch(name: string): number | null | undefined {
  if (name === 'best-checkpoint') return bestCheckpointEpoch.value
  if (name === 'latest-checkpoint') return latestCheckpointEpoch.value
  return null
}
const progressStage = computed(() => formatPlainValue(progressSnapshot.value.stage))
const progressEpochText = computed(() => {
  const epoch = readNumber(progressSnapshot.value.epoch)
  const maxEpochs = readNumber(progressSnapshot.value.max_epochs)
  if (epoch === null && maxEpochs === null) return '-'
  return `${epoch ?? '-'} / ${maxEpochs ?? '-'}`
})
const learningRateText = computed(() => formatMetricValue(progressSnapshot.value.learning_rate, 'learning_rate'))
const optimizerPayload = computed(() => readRecord(trainingMetricsPayload.value.optimizer))
const actualOptimizerText = computed(() => formatPlainValue(
  optimizerPayload.value?.name ?? trainingMetricsPayload.value.optimizer,
))
const initialLearningRateText = computed(() => formatMetricValue(
  trainingMetricsPayload.value.initial_learning_rate
    ?? optimizerPayload.value?.initial_learning_rate, 'learning_rate',
))
const finalLearningRateText = computed(() => formatMetricValue(
  trainingMetricsPayload.value.final_learning_rate
    ?? optimizerPayload.value?.final_learning_rate, 'learning_rate',
))
const currentMetricText = computed(() => {
  const name = formatPlainValue(progressSnapshot.value.current_metric_name)
  const value = formatMetricValue(progressSnapshot.value.current_metric_value)
  if (name === '-' && value === '-') return '-'
  return `${name}: ${value}`
})
const bestMetricText = computed(() => {
  const name = task.value?.best_metric_name || formatPlainValue(progressSnapshot.value.best_metric_name)
  const value = task.value?.best_metric_value ?? progressSnapshot.value.best_metric_value
  if (!name || name === '-') return '-'
  return `${name}: ${formatMetricValue(value)}`
})
const completedEpochMetrics = computed(() => {
  const persistedMetrics = readRecord(trainingMetricsPayload.value.final_metrics)
  if (Object.keys(persistedMetrics).length > 0) return persistedMetrics
  return readRecord(progressSnapshot.value.train_metrics)
})
const trainMetricEntries = computed(() => buildMetricEntries(completedEpochMetrics.value))
const batchMetricEntries = computed(() => {
  const explicitBatchMetrics = readRecord(progressSnapshot.value.batch_metrics)
  return buildMetricEntries(explicitBatchMetrics)
})
const validationMetricEntries = computed(() => buildMetricEntries(progressSnapshot.value.validation_metrics))
const runtimeMetricEntries = computed(() => buildRuntimeMetricEntries(progressSnapshot.value.runtime))
const selectedOutputContent = computed(() => {
  const outputFile = selectedOutputFile.value
  if (!outputFile) return ''
  if (outputFile.file_kind === 'text') return outputFile.text_content || outputFile.lines.join('\n')
  if (Object.keys(outputFile.payload).length > 0) return JSON.stringify(outputFile.payload, null, 2)
  return outputFile.object_key || ''
})
const taskEvents = useTaskEvents(
  () => taskId.value,
  handleTaskEvent,
  () => latestTaskEventCursor.value,
)
const trainingTelemetry = useTrainingTelemetry(
  () => taskId.value,
  handleTrainingTelemetry,
  scheduleSnapshotRefresh,
)
const trainingStreamConnected = computed(() => (
  trainingTelemetry.streamState.value?.connected === true
))
const runtimeHistoryEmptyText = computed(() => {
  if (runtimeHistory.value.length > 0) return t('common.noValue')
  const runtimeFile = outputFiles.value.find((file) => file.file_name === 'runtime-metrics')
  return !isActiveTrainingState(task.value?.state) && runtimeFile?.file_status !== 'ready'
    ? t('trainingDetail.charts.legacyRuntimeUnavailable')
    : t('trainingDetail.charts.runtimePending')
})

function clearRefreshTimers(): void {
  if (snapshotRefreshTimer !== null) {
    window.clearTimeout(snapshotRefreshTimer)
    snapshotRefreshTimer = null
  }
  if (outputFilesRefreshTimer !== null) {
    window.clearTimeout(outputFilesRefreshTimer)
    outputFilesRefreshTimer = null
  }
}

function clearCancellationRefresh(): void {
  if (cancellationRefreshTimer !== null) window.clearTimeout(cancellationRefreshTimer)
  cancellationRefreshTimer = null
  taskScope.cancelRead('cancellation')
}

watch(cancellingTraining, (pending) => {
  if (pending) scheduleCancellationRefresh()
  else clearCancellationRefresh()
})

watch([() => route.params.taskType, () => route.params.taskId], () => {
  taskScope.invalidate()
  taskEvents.stop()
  trainingTelemetry.stop()
  clearRefreshTimers()
  clearCancellationRefresh()
  task.value = null
  outputFiles.value = []
  cancelledOutputTab.value = 'files'
  runLogOpen.value = false
  detailedChartsOpen.value = false
  linkedModelLoading.value = false
  linkedModelError.value = ''
  selectedOutputFile.value = null
  selectedOutputFileName.value = null
  outputPreviewOpen.value = false
  outputDownloading.value = ''
  outputDownloadError.value = null
  trainingMetricsPayload.value = {}
  validationMetricsPayload.value = {}
  runtimeMetricsPayload.value = {}
  trainMetricHistory.value = []
  validationMetricHistory.value = []
  learningRateHistory.value = []
  runtimeHistory.value = []
  latestTaskEventCursor.value = null
  actionRunning.value = null
  deleteDialogOpen.value = false
  closeResumeDialog()
  closeTerminateDialog()
  terminateRequested.value = false
  deleteTarget = null
  errorMessage.value = null
  loading.value = false
  void refreshPage()
}, { immediate: true, flush: 'sync' })

onBeforeUnmount(() => { clearRefreshTimers(); clearCancellationRefresh(); closeResumeDialog() })

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('success') || normalized.includes('succeed') || normalized.includes('ready')) return 'success'
  if (normalized.includes('fail') || normalized.includes('error') || normalized.includes('terminate')) return 'danger'
  if (normalized.includes('queue') || normalized.includes('pending') || normalized.includes('pause')) return 'warning'
  if (normalized.includes('run') || normalized.includes('process') || normalized.includes('save')) return 'info'
  return 'neutral'
}

function actionIcon(action: ModelTrainingTaskActionName) {
  if (action === 'save') return Save
  if (action === 'pause') return Pause
  if (action === 'resume') return Play
  if (action === 'terminate') return Square
  return Trash2
}

async function refreshPage(): Promise<void> {
  const request = taskScope.startRead('snapshot')
  if (!request) {
    if (taskType.value && taskId.value) return
    errorMessage.value = t('trainingDetail.messages.taskTypeRequired')
    return
  }
  taskScope.cancelRead('files')
  taskScope.cancelRead('preview')
  clearRefreshTimers()
  loading.value = true
  errorMessage.value = null
  try {
    const [taskDetail, files] = await Promise.all([
      getModelTrainingTaskDetail(request.taskType, request.taskId, request.signal, !task.value || runLogOpen.value),
      listModelTrainingOutputFiles(request.taskType, request.taskId, request.signal),
    ])
    if (!request.isCurrent()) return
    if (task.value?.task_id === taskDetail.task_id) {
      const received = new Set(taskDetail.events.map(event => event.event_id))
      taskDetail.events = [...taskDetail.events, ...task.value.events.filter(event => !received.has(event.event_id))]
    }
    task.value = taskDetail
    latestTaskEventCursor.value = buildLatestTaskEventCursor(taskDetail.events)
    outputFiles.value = files
    const metricsFile = files.find((file) => file.file_name === 'train-metrics')
    const validationMetricsFile = files.find((file) => file.file_name === 'validation-metrics')
    const runtimeMetricsFile = files.find((file) => file.file_name === 'runtime-metrics')
    const [trainMetricsDetail, validationMetricsDetail, runtimeMetricsDetail] = await Promise.all([
      metricsFile
        ? getModelTrainingOutputFileDetail(request.taskType, request.taskId, metricsFile.file_name, request.signal)
        : Promise.resolve(null),
      validationMetricsFile
        ? getModelTrainingOutputFileDetail(request.taskType, request.taskId, validationMetricsFile.file_name, request.signal)
        : Promise.resolve(null),
      runtimeMetricsFile?.file_status === 'ready'
        ? getModelTrainingOutputFileDetail(request.taskType, request.taskId, runtimeMetricsFile.file_name, request.signal)
        : Promise.resolve(null),
    ])
    if (!request.isCurrent()) return
    trainingMetricsPayload.value = trainMetricsDetail?.payload ?? {}
    validationMetricsPayload.value = validationMetricsDetail?.payload ?? {}
    runtimeMetricsPayload.value = runtimeMetricsDetail?.payload ?? {}
    mergePersistedHistories()
    appendProgressHistory(taskDetail.progress)
    taskDetail.events.forEach((event) => {
      appendProgressHistory(readRecord(event.payload).progress)
    })
    const selectedFileName = selectedOutputFileName.value
    const nextFileName = files.some((file) => file.file_name === selectedFileName)
      ? selectedFileName
      : files[0]?.file_name
    selectedOutputFile.value = null
    selectedOutputFileName.value = nextFileName ?? null
    if (nextFileName) {
      void selectOutputFile(nextFileName)
    }
  } catch (error) {
    if (request.isCurrent()) {
      errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.loadFailed')
    }
  } finally {
    if (request.isCurrent()) {
      loading.value = false
      syncTaskEventSubscription()
    }
  }
}

function captureLoadedTask(): ModelTaskTarget | null {
  const target = taskScope.capture()
  return target && task.value?.task_id === target.taskId && !loading.value && actionRunning.value === null
    ? target
    : null
}

function closeResumeDialog(): void {
  resumeRequest?.abort()
  resumeRequest = null
  resumeDialogOpen.value = false
  resumePreview.value = null
  resumeBlockedAt.value = null
  resumeError.value = ''
  resumeChecking.value = false
}

async function checkResume(): Promise<void> {
  const target = captureLoadedTask()
  if (!target) return
  if (cancelledTraining.value) {
    closeResumeDialog()
    resumeDialogOpen.value = true
    resumeBlockedAt.value = 'task'
    resumeError.value = zh.value ? '任务已取消。可在详情中查看已写入的检查点和日志。' : 'This task was cancelled. Checkpoints and logs are listed in task details.'
    return
  }
  if (!task.value?.available_actions.includes('resume')) {
    if (!failedTraining.value) return
    closeResumeDialog()
    resumeDialogOpen.value = true
    resumeBlockedAt.value = 'task'
    resumeError.value = zh.value ? '此任务没有可恢复的执行状态。' : 'The task has no recoverable execution state.'
    return
  }
  closeResumeDialog()
  const controller = new AbortController()
  resumeRequest = controller
  resumeDialogOpen.value = true
  resumeChecking.value = true
  try {
    const result = await previewModelTrainingResume(target.taskType, target.taskId, controller.signal)
    if (!controller.signal.aborted && target.isCurrent()) resumePreview.value = result
  } catch (error) {
    if (!controller.signal.aborted && target.isCurrent()) {
      const check = error instanceof ApiError ? (error.details as { resume_check?: unknown } | undefined)?.resume_check : null
      if (check === 'task' || check === 'checkpoint' || check === 'dataset') resumeBlockedAt.value = check
      resumeError.value = error instanceof Error ? error.message : t('trainingDetail.messages.actionFailed')
    }
  } finally {
    if (resumeRequest === controller) resumeChecking.value = false
  }
}

function closeTerminateDialog(): void {
  terminateDialogOpen.value = false
  terminateError.value = null
}

async function runAction(action: ModelTrainingTaskActionName, confirmed = false): Promise<void> {
  const target = captureLoadedTask()
  if (!target || actionRunning.value || cancellingTraining.value || !task.value?.available_actions.includes(action)) return
  if (action === 'delete') {
    openDeleteDialog()
    return
  }
  if (action === 'terminate') {
    if (!confirmed) {
      terminateError.value = null
      terminateDialogOpen.value = true
      return
    }
    if (!terminateDialogOpen.value) return
    terminateError.value = null
  }
  if (action === 'resume' && !confirmed) {
    await checkResume()
    return
  }
  if (action === 'resume' && (!resumeDialogOpen.value || !resumePreview.value || resumeError.value)) return
  actionRunning.value = action
  errorMessage.value = null
  try {
    const response = await requestModelTrainingTaskAction(target.taskType, target.taskId, action)
    if (target.isCurrent()) {
      if (action === 'resume') closeResumeDialog()
      if (action === 'terminate') {
        terminateRequested.value = true
        if ('state' in response && task.value) {
          task.value = { ...task.value, state: response.state, control_status: response.control_status, available_actions: response.available_actions }
        }
        closeTerminateDialog()
      }
      await refreshPage()
    }
  } catch (error) {
    if (target.isCurrent()) {
      const message = error instanceof Error ? error.message : t('trainingDetail.messages.actionFailed')
      if (action === 'resume') resumeError.value = message
      else if (action === 'terminate') terminateError.value = message
      else errorMessage.value = message
    }
  } finally {
    if (target.isCurrent()) actionRunning.value = null
  }
}

function handleTaskEvent(event: TaskEvent): void {
  const target = taskScope.capture()
  if (!target || task.value?.task_id !== target.taskId || event.task_id !== target.taskId) return
  const data = readRecord(event.payload)
  const timestamp = event.created_at ?? event.occurred_at
  if (event.event_id && timestamp && !task.value.events.some(item => item.event_id === event.event_id)) {
    task.value.events.push({ event_id: event.event_id, task_id: target.taskId, event_type: event.event_type ?? 'status',
      created_at: timestamp, message: event.message ?? '', payload: data })
  }
  const progress = readRecord(data.progress)
  const shouldApplySnapshot = shouldApplyTaskEventSnapshot(data, progress)
  const shouldApplyCompletedEpoch = shouldApplySnapshot
    || shouldApplyRecentCompletedEpochMetrics(progress)
  if (task.value && Object.keys(data).length > 0 && shouldApplySnapshot) {
    const nextState = typeof data.state === 'string' ? data.state : task.value.state
    const nextBestMetricName = typeof progress.best_metric_name === 'string'
      ? progress.best_metric_name
      : task.value.best_metric_name
    const nextBestMetricValue = readNumber(progress.best_metric_value) ?? task.value.best_metric_value
    task.value = {
      ...task.value,
      state: nextState,
      progress: { ...task.value.progress, ...progress },
      result: { ...task.value.result, ...readRecord(data.result) },
      metadata: { ...task.value.metadata, ...readRecord(data.metadata) },
      best_metric_name: nextBestMetricName,
      best_metric_value: nextBestMetricValue,
    }
  }
  if (task.value && shouldApplyCompletedEpoch) {
    const nextBestMetricName = typeof progress.best_metric_name === 'string'
      ? progress.best_metric_name
      : task.value.best_metric_name
    const nextBestMetricValue = readNumber(progress.best_metric_value)
      ?? task.value.best_metric_value
    task.value = {
      ...task.value,
      best_metric_name: nextBestMetricName,
      best_metric_value: nextBestMetricValue,
    }
    mergeCompletedEpochMetricPayloads(progress)
  }
  appendProgressHistory(progress)
  if (event.event_type === 'result' || event.event_type === 'status') {
    scheduleSnapshotRefresh()
  }
  if (shouldApplySnapshot && !isActiveTrainingState(task.value?.state)) {
    taskEvents.stop()
    trainingTelemetry.stop()
  }
}

function shouldApplyRecentCompletedEpochMetrics(
  incomingProgress: Record<string, unknown>,
): boolean {
  const trainMetrics = readRecord(incomingProgress.train_metrics)
  const validationMetrics = readRecord(incomingProgress.validation_metrics)
  if (Object.keys(trainMetrics).length === 0 && Object.keys(validationMetrics).length === 0) {
    return false
  }
  const incomingEpoch = readNumber(incomingProgress.epoch)
  if (incomingEpoch === null) return false
  const persistedEpoch = Math.max(
    readNumber(trainingMetricsPayload.value.epoch) ?? -1,
    readNumber(validationMetricsPayload.value.epoch) ?? -1,
  )
  if (incomingEpoch <= persistedEpoch) return false
  const currentEpoch = readNumber(task.value?.progress.epoch)
  return currentEpoch === null || incomingEpoch >= currentEpoch - 1
}

function mergeCompletedEpochMetricPayloads(progress: Record<string, unknown>): void {
  const trainMetrics = readRecord(progress.train_metrics)
  if (Object.keys(trainMetrics).length > 0) {
    trainingMetricsPayload.value = {
      ...trainingMetricsPayload.value,
      epoch: readNumber(progress.epoch) ?? trainingMetricsPayload.value.epoch,
      epoch_index: readNumber(progress.epoch_index) ?? trainingMetricsPayload.value.epoch_index,
      max_epochs: readNumber(progress.max_epochs) ?? trainingMetricsPayload.value.max_epochs,
      final_metrics: trainMetrics,
    }
  }
  const validationMetrics = readRecord(progress.validation_metrics)
  if (Object.keys(validationMetrics).length > 0) {
    validationMetricsPayload.value = {
      ...validationMetricsPayload.value,
      epoch: readNumber(progress.epoch) ?? validationMetricsPayload.value.epoch,
      epoch_index: readNumber(progress.epoch_index) ?? validationMetricsPayload.value.epoch_index,
      max_epochs: readNumber(progress.max_epochs) ?? validationMetricsPayload.value.max_epochs,
      final_metrics: validationMetrics,
    }
  }
}

function handleTrainingTelemetry(payload: TrainingTelemetryPayload): void {
  const target = taskScope.capture()
  if (!target || payload.task_id !== target.taskId) return
  const currentTask = task.value
  if (currentTask === null || payload.task_id !== currentTask.task_id) return
  if (payload.attempt_no < currentTask.current_attempt_no) return
  const currentEpoch = readNumber(currentTask.progress.epoch)
  if (currentEpoch !== null && payload.epoch !== null && payload.epoch !== undefined) {
    if (payload.epoch < currentEpoch) return
  }
  const nextProgress: Record<string, unknown> = {
    ...currentTask.progress,
    stage: payload.stage,
    granularity: payload.granularity,
  }
  assignTelemetryValue(nextProgress, 'percent', payload.progress_percent)
  assignTelemetryValue(nextProgress, 'epoch', payload.epoch)
  assignTelemetryValue(nextProgress, 'epoch_index', payload.epoch_index)
  assignTelemetryValue(nextProgress, 'max_epochs', payload.max_epochs)
  assignTelemetryValue(nextProgress, 'iteration', payload.step)
  assignTelemetryValue(nextProgress, 'max_iterations', payload.steps_per_epoch)
  assignTelemetryValue(nextProgress, 'global_iteration', payload.global_step)
  assignTelemetryValue(nextProgress, 'total_iterations', payload.total_steps)
  assignTelemetryValue(nextProgress, 'input_size', payload.input_size)
  assignTelemetryValue(nextProgress, 'learning_rate', payload.learning_rate)
  if (payload.granularity === 'batch') nextProgress.batch_metrics = payload.metrics
  if (Object.keys(payload.runtime).length > 0) nextProgress.runtime = payload.runtime
  runtimeHistory.value = appendTrainingRuntimePoint(
    runtimeHistory.value,
    buildRuntimePoint(
      payload.global_step,
      payload.timestamp,
      payload.runtime,
      payload.attempt_no,
    ),
  )
  task.value = {
    ...currentTask,
    current_attempt_no: Math.max(currentTask.current_attempt_no, payload.attempt_no),
    progress: nextProgress,
  }
  if (
    payload.epoch !== null
    && payload.epoch !== undefined
    && (currentEpoch === null || payload.epoch > currentEpoch)
  ) {
    scheduleOutputFilesRefresh()
  }
}

function assignTelemetryValue(
  target: Record<string, unknown>,
  name: string,
  value: unknown,
): void {
  if (value !== null && value !== undefined) target[name] = value
}

function shouldApplyTaskEventSnapshot(
  data: Record<string, unknown>,
  incomingProgress: Record<string, unknown>,
): boolean {
  const currentTask = task.value
  if (currentTask === null) return true
  const incomingAttempt = readNumber(data.attempt_no)
  if (incomingAttempt !== null && incomingAttempt < currentTask.current_attempt_no) {
    return false
  }
  const incomingState = typeof data.state === 'string' ? data.state : null
  if (!isActiveTrainingState(currentTask.state) && isActiveTrainingState(incomingState)) {
    return false
  }
  const currentProgress = currentTask.progress
  const currentGlobalStep = readNumber(
    currentProgress.global_step ?? currentProgress.global_iteration,
  )
  const incomingGlobalStep = readNumber(
    incomingProgress.global_step ?? incomingProgress.global_iteration,
  )
  if (
    currentGlobalStep !== null
    && incomingGlobalStep !== null
    && incomingGlobalStep < currentGlobalStep
  ) {
    return false
  }
  const currentEpoch = readNumber(currentProgress.epoch)
  const incomingEpoch = readNumber(incomingProgress.epoch)
  return currentEpoch === null || incomingEpoch === null || incomingEpoch >= currentEpoch
}

function buildLatestTaskEventCursor(
  events: ModelTrainingTaskDetail['events'],
): string | null {
  const latestEvent = [...events].sort((left, right) => (
    left.created_at.localeCompare(right.created_at)
    || left.event_id.localeCompare(right.event_id)
  )).at(-1)
  return latestEvent ? `${latestEvent.created_at}|${latestEvent.event_id}` : null
}

function isActiveTrainingState(state: string | null | undefined): boolean {
  return state === 'queued' || state === 'running'
}

function syncTaskEventSubscription(): void {
  const target = taskScope.capture()
  if (target && task.value?.task_id === target.taskId && isActiveTrainingState(task.value?.state)) {
    taskEvents.start()
    trainingTelemetry.start()
    return
  }
  taskEvents.stop()
  trainingTelemetry.stop()
}

function appendProgressHistory(value: unknown): void {
  const progress = readRecord(value)
  if (Object.keys(progress).length === 0) return
  trainMetricHistory.value = appendTrainingMetricPoint(
    trainMetricHistory.value,
    buildMetricPointFromProgress(progress, 'train_metrics'),
  )
  validationMetricHistory.value = appendTrainingMetricPoint(
    validationMetricHistory.value,
    buildMetricPointFromProgress(progress, 'validation_metrics'),
  )
  learningRateHistory.value = appendTrainingScalarPoint(
    learningRateHistory.value,
    buildLearningRatePointFromProgress(progress),
  )
}

function mergePersistedHistories(): void {
  readPersistedMetricHistory(trainingMetricsPayload.value).forEach((point) => {
    trainMetricHistory.value = appendTrainingMetricPoint(trainMetricHistory.value, point)
  })
  readPersistedMetricHistory(validationMetricsPayload.value).forEach((point) => {
    validationMetricHistory.value = appendTrainingMetricPoint(validationMetricHistory.value, point)
  })
  readPersistedLearningRateHistory(trainingMetricsPayload.value).forEach((point) => {
    learningRateHistory.value = appendTrainingScalarPoint(learningRateHistory.value, point)
  })
  readPersistedRuntimeHistory(runtimeMetricsPayload.value).forEach((point) => {
    runtimeHistory.value = appendTrainingRuntimePoint(runtimeHistory.value, point)
  })
}

function scheduleCancellationRefresh(): void {
  const target = taskScope.capture()
  if (!target || cancellationRefreshTimer !== null || !cancellingTraining.value) return
  cancellationRefreshTimer = window.setTimeout(async () => {
    cancellationRefreshTimer = null
    if (!target.isCurrent() || !cancellingTraining.value) return
    try {
      const request = taskScope.startRead('cancellation')
      if (!request || loading.value) return
      const detail = await getModelTrainingTaskDetail(request.taskType, request.taskId, request.signal)
      if (request.isCurrent() && !loading.value && cancellingTraining.value
        && !isActiveTrainingState(detail.state) && detail.state !== 'paused') {
        await refreshPage()
      }
    } catch {
      // 状态读取失败时保留“正在取消”，继续查询，不重复发送取消请求。
    } finally {
      if (target.isCurrent()) scheduleCancellationRefresh()
    }
  }, 3000)
}

function scheduleSnapshotRefresh(): void {
  const target = taskScope.capture()
  if (!target || snapshotRefreshTimer !== null) return
  snapshotRefreshTimer = window.setTimeout(() => {
    snapshotRefreshTimer = null
    if (target.isCurrent()) void refreshPage()
  }, 300)
}

function scheduleOutputFilesRefresh(): void {
  const target = taskScope.capture()
  if (!target || outputFilesRefreshTimer !== null) return
  outputFilesRefreshTimer = window.setTimeout(() => {
    outputFilesRefreshTimer = null
    if (target.isCurrent()) void refreshOutputFiles()
  }, 300)
}

async function refreshOutputFiles(): Promise<void> {
  if (loading.value) return
  const request = taskScope.startRead('files')
  if (!request) return
  try {
    const files = await listModelTrainingOutputFiles(request.taskType, request.taskId, request.signal)
    if (!request.isCurrent()) return
    outputFiles.value = files
    const selectedFileName = selectedOutputFileName.value
    if (selectedFileName && files.some((file) => file.file_name === selectedFileName)) {
      void selectOutputFile(selectedFileName)
    } else {
      taskScope.cancelRead('preview')
      selectedOutputFileName.value = null
      selectedOutputFile.value = null
      outputPreviewOpen.value = false
    }
  } catch {
    // 后台状态同步失败不覆盖页面已有数据，后续 epoch 或手动刷新会再次获取。
  }
}

function openDeleteDialog(): void {
  const target = captureLoadedTask()
  if (!target || !canDeleteTask.value) return
  deleteTarget = target
  deleteDialogOpen.value = true
}

async function deleteCurrentTask(): Promise<void> {
  const target = deleteTarget
  if (!deleteDialogOpen.value || !target?.isCurrent() || !captureLoadedTask() || !canDeleteTask.value) return
  actionRunning.value = 'delete'
  errorMessage.value = null
  try {
    await deleteModelTrainingTask(target.taskType, target.taskId)
    if (target.isCurrent()) await router.replace(modelTaskListLocation('training', target.taskType, route.query))
  } catch (error) {
    if (target.isCurrent()) errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.actionFailed')
  } finally {
    if (target.isCurrent()) {
      actionRunning.value = null
      deleteDialogOpen.value = false
      deleteTarget = null
    }
  }
}

async function registerCheckpoint(): Promise<void> {
  const target = captureLoadedTask()
  if (!target || target.taskType !== 'detection' || !canRegisterCheckpoint.value) return
  actionRunning.value = 'register-model-version'
  errorMessage.value = null
  try {
    const detail = await registerModelTrainingLatestCheckpoint(target.taskType, target.taskId)
    if (!target.isCurrent()) return
    task.value = detail
    await refreshPage()
  } catch (error) {
    if (target.isCurrent()) errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.registerFailed')
  } finally {
    if (target.isCurrent()) actionRunning.value = null
  }
}

async function downloadOutput(file: ModelTrainingOutputFileSummary): Promise<void> {
  if (outputDownloading.value || file.file_status !== 'ready') return
  const request = taskScope.startRead('download')
  if (!request) return
  outputDownloading.value = file.file_name
  outputDownloadError.value = null
  try {
    const blob = await downloadModelTrainingOutputFile(request.taskType, request.taskId, file.file_name, request.signal)
    if (!request.isCurrent()) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = (file.object_key?.split(/[\\/]/).pop() || file.file_name).replace(/[\\/:*?"<>|\x00-\x1f]/g, '_') || 'training-output'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch {
    if (request.isCurrent()) outputDownloadError.value = t('trainingDetail.messages.downloadFailed')
  } finally {
    if (request.isCurrent()) outputDownloading.value = ''
  }
}

async function selectOutputFile(fileName: string): Promise<void> {
  if (!outputFiles.value.some((file) => file.file_name === fileName)) return
  const request = taskScope.startRead('preview')
  if (!request) return
  selectedOutputFileName.value = fileName
  selectedOutputFile.value = null
  errorMessage.value = null
  try {
    const detail = await getModelTrainingOutputFileDetail(request.taskType, request.taskId, fileName, request.signal)
    if (request.isCurrent()) selectedOutputFile.value = detail
  } catch (error) {
    if (request.isCurrent()) errorMessage.value = error instanceof Error ? error.message : t('trainingDetail.messages.outputFailed')
  }
}

function buildMetricEntries(value: unknown): Array<{ name: string; value: string }> {
  const metrics = readRecord(value)
  return Object.entries(metrics)
    .filter(([, metricValue]) => metricValue !== null && metricValue !== undefined)
    .map(([name, metricValue]) => ({ name, value: formatMetricValue(metricValue, name) }))
}

function buildRuntimeMetricEntries(value: unknown): Array<{ name: string; value: string }> {
  const runtime = readRecord(value)
  const orderedNames = [
    'device',
    'batch_size',
    'batch_resolution_mode',
    'oom_recovery_count',
    'samples_per_second',
    'steps_per_second',
    'step_time_ms',
    'forward_loss_host_time_ms',
    'backward_optimizer_host_time_ms',
    'batch_compute_host_time_ms',
    'epoch_elapsed_seconds',
    'elapsed_seconds',
    'estimated_remaining_seconds',
    'gpu_utilization_percent',
    'gpu_memory_used_percent',
    'gpu_memory_allocated_bytes',
    'gpu_memory_reserved_bytes',
  ]
  return orderedNames.flatMap((name) => {
    const runtimeValue = runtime[name]
    if (runtimeValue === null || runtimeValue === undefined) return []
    return [{ name, value: formatRuntimeValue(name, runtimeValue) }]
  })
}

function formatRuntimeValue(name: string, value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return formatPlainValue(value)
  if (name.endsWith('_bytes')) return `${(value / (1024 ** 3)).toFixed(3)} GiB`
  if (name.endsWith('_percent')) return `${Number(value.toFixed(2))}%`
  if (name.endsWith('_ms')) return `${formatModelNumber(value, 0)} ms`
  if (name.endsWith('_seconds')) return `${Number(value.toFixed(1))} s`
  if (name.endsWith('_per_second')) return Number(value.toFixed(2)).toString()
  return formatMetricValue(value)
}

function readRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return {}
}

function readNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  return null
}

function formatMetricValue(value: unknown, name = ''): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (name.endsWith('learning_rate')) return formatLearningRate(value)
    return formatModelNumber(value, name.endsWith('_ms') ? 0 : 3)
  }
  return formatPlainValue(value)
}

function formatPlainValue(value: unknown): string {
  if (typeof value === 'string' && value.trim()) return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return '-'
}
</script>

<style scoped>
.training-stop-icon { color:var(--am-warning-icon); }
.training-stop-summary { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin:0; padding:12px; border-radius:var(--am-radius-sm); background:var(--am-surface-muted); }
.training-stop-summary > div + div { padding-inline-start:12px; border-inline-start:1px solid var(--am-border); }
.training-stop-summary dt { color:var(--am-text-muted); }
.training-stop-summary dd { margin:4px 0 0; overflow-wrap:anywhere; }
.training-resume-summary { display:grid; grid-template-columns: minmax(95px, auto) minmax(0, 1fr); gap:8px 14px; margin:0; }
.training-resume-summary dt { color:var(--am-text-muted); }
.training-resume-summary dd { margin:0; overflow-wrap:anywhere; }
.training-cancelled-note { display:flex; align-items:flex-start; gap:8px; margin:0; padding:11px; border-radius:6px; background:var(--am-surface-muted); }
.training-cancelled-note svg,.training-resume__warning svg { flex:none; }
.training-detail-title { display:flex; align-items:center; flex-wrap:wrap; gap:8px 12px; min-width:0; }
.training-detail-title h1 { overflow-wrap:anywhere; }
.training-detail-back { justify-self:start; align-self:flex-start; margin-inline-start:-8px; margin-bottom:3px; }
.training-detail :deep(.page-header) { align-items:flex-end; }
.training-detail :deep(.page-actions) { max-width:56%; }
.training-detail :deep(.page-header__heading) { flex:1; }
.training-progress--failed { --am-progress-text:var(--am-danger-text); }
.training-overview-progress { display:flex; flex-wrap:wrap; align-items:center; gap:14px 20px; }
.training-overview-progress .task-progress { flex:1 1 180px; }
.training-progress-facts { flex:0 1 auto; display:flex; flex-wrap:wrap; align-items:center; gap:8px 15px; margin:0; }
.training-progress-facts div { display:flex; align-items:center; flex-wrap:wrap; gap:4px 8px; }
.training-progress-facts div:not(:last-child) { padding-inline-end:15px; border-inline-end:1px solid var(--am-border); }
.training-progress-facts dt { color:var(--am-text-muted); }
.training-progress-facts dd { margin:0; }
.training-progress-facts dd strong { font-size:19px; }
.training-failed-note { display:flex; gap:10px; padding:13px 16px; border:1px solid var(--am-danger-border); background:var(--am-danger-surface); border-radius:var(--am-radius-md); color:var(--am-danger-text); overflow-wrap:anywhere; }
.training-failed-note svg { flex:none; }
.training-failed-note p { margin:6px 0 0; color:var(--am-text); }
.training-more summary { cursor:pointer; font-weight:600; }
.training-more[open] > section { margin-block:14px; }
.training-cancelled-context { display:flex; flex-wrap:wrap; gap:9px 16px; margin:0; padding:12px 16px; border:1px solid var(--am-border); border-radius:var(--am-radius-md); background:var(--am-surface); }
.training-cancelled-context > div { display:grid; min-width:0; gap:3px; padding-inline-end:16px; }
.training-cancelled-context > div:not(:last-child) { border-inline-end:1px solid var(--am-border); }
.training-cancelled-context dt { font-size:12px; color:var(--am-text-muted); }
.training-cancelled-context dd { margin:0; overflow-wrap:anywhere; }
.training-cancelled-progress { display:flex; align-items:center; flex-wrap:wrap; gap:14px 22px; padding:14px 16px; }
.training-cancelled-progress__status { display:grid; grid-template-columns:auto minmax(100px,1fr); align-items:center; gap:12px; flex:1 1 320px; min-width:0; }
.training-cancelled-progress__counts { display:flex; align-items:center; flex-wrap:wrap; gap:4px 12px; }
.training-cancelled-progress__counts span { color:var(--am-text-muted); }
.training-progress--cancelled.task-progress { width:100%; --am-progress-fill:var(--am-text-muted); --am-progress-text:var(--am-text-muted); }
.training-stop-times { display:grid; gap:4px; margin:0; padding-inline-start:14px; border-inline-start:1px solid var(--am-border); color:var(--am-text-muted); font-size:12px; }
.training-stop-times > div { display:flex; flex-wrap:wrap; gap:4px 8px; }
.training-stop-times dd { margin:0; color:var(--am-text); }
.training-resume { display:grid; gap:16px; min-width:0; }
.training-resume :is(h3,p) { margin:0; overflow-wrap:anywhere; }
.training-resume__warning { display:flex; gap:8px; padding:12px; border:1px solid var(--am-warning-border); border-radius:6px; background:var(--am-warning-surface); color:var(--am-warning-text); }
.training-resume__warning p { margin-block-start:4px; }
.training-resume__checks table { width:100%; min-width:0; table-layout:fixed; }
.training-resume__checks :is(th,td) { white-space:normal; overflow-wrap:anywhere; text-align:start; }
.training-resume__unavailable { color:var(--am-danger-text); }
.training-resume__actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; width:100%; }
.training-detail :deep(.page-header h1) { display: block; }
.training-detail > .resource-section:first-of-type .summary-grid strong { font-size:14px; overflow-wrap:anywhere; }
.training-metrics-details { margin:16px 0; border:1px solid var(--am-border); border-radius:8px; }
.training-metrics-details > summary { padding:12px; cursor:pointer; font-weight:600; }
.training-metrics-details .training-metric-panels { padding:0 12px 12px; }
.training-output-layout { display:grid; gap:16px; min-width:0; }
.training-output-layout table { table-layout:fixed; width:100%; }
.training-output-layout :is(td,th) { white-space:normal; overflow-wrap:anywhere; padding-inline:8px; }
.training-output-section :deep(.local-tabs) { margin-block-start:-4px; }
.training-output-section :deep(.local-tabs__tab) { border-radius:0; border-bottom:2px solid transparent; }
.training-output-section :deep(.local-tabs__tab.is-active) { background:transparent; border-bottom-color:var(--am-brand-primary); color:var(--am-success-text); }
.training-run-log { display:grid; gap:8px; margin:0; padding:0; list-style:none; }
.training-run-log li { display:flex; flex-wrap:wrap; gap:4px 14px; padding-block:6px; overflow-wrap:anywhere; }
.training-run-log time { color:var(--am-text-muted); font-variant-numeric:tabular-nums; }
.training-saved-parameters { max-height:420px; margin:0; white-space:pre-wrap; overflow-wrap:anywhere; }
.training-output-preview { border:1px solid var(--am-border); border-radius:8px; padding:12px; }
.training-output-preview summary { cursor:pointer; font-weight:600; }
.training-output-preview .json-view { max-height:420px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; }
.training-progress-section {
  gap: 14px;
}

.training-progress-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.training-metric-panels {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.training-metric-panel {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  background: var(--am-surface-soft);
  border: 1px solid var(--am-border);
  border-radius: 8px;
}

.training-metric-panel h3 {
  margin: 0;
  color: var(--am-text);
  font-size: 13px;
}

.training-chart-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-top: 4px;
}

.training-chart-heading h3,
.training-chart-heading p {
  margin: 0;
}

.training-chart-heading h3 {
  color: var(--am-text);
  font-size: 14px;
}

.training-chart-heading p {
  margin-top: 4px;
  color: var(--am-text-muted);
  font-size: 12px;
}

.training-metric-hint {
  margin: 4px 0 0;
  color: var(--am-text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.training-metric-list {
  display: grid;
  grid-template-columns: minmax(0, 1fr) max-content;
  gap: 7px 12px;
  margin: 0;
}

.training-metric-list dt,
.training-metric-list dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}

.training-metric-list dt {
  color: var(--am-text-muted);
}

.training-metric-list dd {
  color: var(--am-text);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.training-muted-value {
  color: var(--am-text-muted);
  font-weight: 700;
}

@media (max-width: 960px) {
  .training-progress-grid,
  .training-metric-panels {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 1160px) {
  .training-detail :deep(.page-header) { display:grid; grid-template-columns:minmax(0,1fr); gap:10px; }
  .training-detail :deep(.page-actions) { max-width:100%; justify-content:flex-start; }
}
</style>
