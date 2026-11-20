<template>
  <section class="page-stack evaluation-run" :class="{ 'evaluation-run--cancelled': cancelled }">
    <PageHeader>
      <template #heading>
        <ButtonLink class="evaluation-run__back" variant="ghost" size="sm" :to="listLocation"><ArrowLeft :size="16" />{{ label('返回评估列表', 'Back to evaluations') }}</ButtonLink>
        <div class="evaluation-run__title"><h1>{{ task.display_name }}</h1><TaskStateBadge :state="task.state" /></div>
      </template>
      <template #actions>
        <template v-if="cancelled">
          <Button :disabled="!task.events?.length && !coverage" @click="downloadLog"><Download :size="16" />{{ label('下载执行记录', 'Download run record') }}</Button>
          <ButtonLink v-if="canRetry" variant="primary" :to="{ path: '/models', query: { tab: 'evaluation', retry: task.task_id } }">{{ label('按此配置重新评估', 'Rerun with this configuration') }}</ButtonLink>
        </template>
        <template v-else>
          <Button :loading="refreshing" @click="emit('refresh')"><RefreshCw :size="16" />{{ label('刷新', 'Refresh') }}</Button>
          <Button v-if="canCancel" :disabled="task.state === 'cancelling'" @click="emit('cancel')">{{ label('取消任务', 'Cancel task') }}</Button>
        </template>
        <Button disabled><Download :size="16" />{{ label('下载报告', 'Download report') }}</Button>
        <Button v-if="cancelled" disabled><ChartNoAxesColumn :size="16" />{{ label('比较', 'Compare') }}</Button>
      </template>
    </PageHeader>

    <InlineError v-if="error" :message="error" />
    <dl class="resource-section evaluation-run__source">
      <div><dt>{{ label('模型版本', 'Model version') }}</dt><dd>{{ modelVersionName || task.model_type || '—' }}</dd></div>
      <div v-if="task.dataset_version_id"><dt>{{ label('数据版本', 'Dataset version') }}</dt><dd>{{ task.dataset_version_id }}</dd></div>
      <div v-if="split"><dt>{{ label('评估划分', 'Split') }}</dt><dd>{{ split }}<template v-if="requested != null"> · {{ requested }} {{ label('张', 'images') }}</template></dd></div>
      <div v-if="runtime"><dt>{{ label('运行时', 'Runtime') }}</dt><dd>{{ runtime }}</dd></div>
    </dl>

    <section class="resource-section evaluation-run__metrics" :aria-label="label('最终指标', 'Final metrics')">
      <dl>
        <div v-for="metric in ['mAP50–95', 'mAP50', 'Precision', 'Recall']" :key="metric"><dt>{{ metric }}</dt><dd>—</dd></div>
      </dl>
      <p role="status">{{ cancelled ? label('评估提前结束，未生成完整评估报告。', 'Evaluation ended early. No complete report was generated.') : label('评估完成后汇总指标。', 'Metrics are available after evaluation finishes.') }}</p>
    </section>

    <section class="resource-section evaluation-run__progress" :aria-label="label('执行进度', 'Run progress')">
      <ol class="evaluation-run__steps">
        <li v-for="(stage, index) in stages" :key="stage.label" :class="`is-${stage.state}`" :aria-current="stage.state === 'current' ? 'step' : undefined">
          <span class="evaluation-run__mark" aria-hidden="true"><Check v-if="stage.state === 'done'" :size="16" /><template v-else>{{ index + 1 }}</template></span>
          <strong>{{ stage.label }}</strong><span>{{ stage.detail }}</span>
        </li>
      </ol>
      <dl class="evaluation-run__counts">
        <div><dt>{{ label('已处理', 'Processed') }}</dt><dd>{{ processed ?? '—' }}<template v-if="requested != null"> / {{ requested }}</template></dd>
          <TaskProgress v-if="percent != null || task.state === 'running'" :percent="percent" :indeterminate="percent == null" :aria-label="label('已处理样本进度', 'Sample progress')" compact /></div>
        <div><dt>{{ label('失败', 'Failed') }}</dt><dd>{{ failed ?? '—' }}</dd></div>
        <div><dt>{{ label('未处理', 'Unprocessed') }}</dt><dd>{{ coverage?.unprocessed ?? '—' }}</dd></div>
      </dl>
    </section>

    <section class="resource-section evaluation-run__log-panel">
      <TabList v-model="tab" :tabs="tabs" :label="label('执行记录', 'Run record')" />
      <template v-if="tab === 'samples'">
        <div v-if="samples.length" class="resource-table evaluation-run__table"><table>
          <thead><tr><th scope="col">{{ label('序号', 'No.') }}</th><th scope="col">{{ label('文件名', 'Filename') }}</th><th scope="col">{{ label('类别', 'Classes') }}</th><th scope="col">{{ label('处理状态', 'Status') }}</th><th scope="col">{{ label('处理时间', 'Processed at') }}</th></tr></thead>
          <tbody><tr v-for="row in samples" :key="row.image_index"><td>{{ row.image_index + 1 }}</td><td>{{ row.name || '—' }}</td><td>{{ row.classes.join('、') || '—' }}</td><td><StatusBadge :tone="row.status === 'succeeded' ? 'success' : 'danger'" with-dot>{{ row.status === 'succeeded' ? label('成功', 'Succeeded') : label('失败', 'Failed') }}</StatusBadge></td><td>{{ formatSystemDateTime(row.processed_at) }}</td></tr></tbody>
        </table></div>
        <p v-else class="evaluation-run__empty">{{ label('暂无已保存的样本处理记录。', 'No sample processing records were saved.') }}</p>
      </template>
      <ol v-else-if="task.events?.length" class="evaluation-run__log">
        <li v-for="event in task.events" :key="event.event_id"><time :datetime="event.created_at">{{ formatSystemDateTime(event.created_at) }}</time><span>{{ event.message }}</span></li>
      </ol>
      <p v-else class="evaluation-run__empty">{{ label('暂无运行日志。', 'No run events were saved.') }}</p>
    </section>
  </section>
</template>

<script setup lang="ts">
import { useCatalogVersionLabel } from '../composables/useCatalogVersionLabel'
import { computed, ref } from 'vue'
import { ArrowLeft, ChartNoAxesColumn, Check, Download, RefreshCw } from '@lucide/vue'
import PageHeader from '@/shared/ui/layout/PageHeader.vue'
import Button from '@/shared/ui/components/Button.vue'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import TaskProgress from '@/modules/tasks/components/TaskProgress.vue'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { downloadEvaluationJson, type DetectionEvaluationTask } from '../services/model-evaluation.service'

const props = defineProps<{ task: DetectionEvaluationTask; canRetry: boolean; canCancel: boolean; refreshing: boolean; error: string; zh: boolean }>()
const modelVersionName = useCatalogVersionLabel(() => [props.task.project_id, 'detection', props.task.model_version_id])
const emit = defineEmits<{ refresh: []; cancel: [] }>()
const label = (zh: string, en: string) => props.zh ? zh : en
const listLocation = { path: '/models', query: { tab: 'evaluation' } }
const coverage = computed(() => props.task.progress.coverage)
const cancelled = computed(() => props.task.state === 'cancelled')
const requested = computed(() => coverage.value?.requested)
const notStarted = computed(() => props.task.started_at === null)
const processed = computed(() => coverage.value ? coverage.value.succeeded + coverage.value.failed : notStarted.value ? 0 : null)
const failed = computed(() => coverage.value?.failed ?? (notStarted.value ? 0 : null))
const percent = computed(() => requested.value && processed.value != null ? 100 * processed.value / requested.value : null)
const split = computed(() => props.task.progress.split_name || props.task.task_spec?.extra_options?.split || props.task.report_summary.split_name)
const runtime = computed(() => {
  const backend = props.task.progress.runtime_backend
  return [backend === 'pytorch' ? 'PyTorch' : backend, props.task.progress.runtime_precision?.toUpperCase()].filter(Boolean).join(' ')
})
const samples = computed(() => props.task.progress.recent_samples?.slice(0, 3) ?? [])
const stages = computed(() => {
  const stage = props.task.progress.stage
  const summarizing = stage === 'summarizing' || stage === 'publishing'
  const dataLoaded = Boolean(coverage.value) || stage === 'evaluating' || summarizing
  const activeState = cancelled.value ? 'stopped' : 'current'
  const done = label('已完成', 'Completed')
  const stopped = label('已取消', 'Cancelled')
  const skipped = label('未执行', 'Not started')
  const unknown = label('未记录', 'Not recorded')
  const current = cancelled.value ? stopped : props.task.state === 'cancelling' ? label('正在取消', 'Cancelling') : label('进行中', 'In progress')
  const preparing = stage === 'preparing'
  return [
    { label: label('加载数据', 'Load data'), state: dataLoaded ? 'done' : preparing ? activeState : 'idle', detail: dataLoaded ? done : preparing ? current : notStarted.value ? skipped : unknown },
    { label: label('执行评估', 'Evaluate'), state: summarizing ? 'done' : dataLoaded ? activeState : 'idle', detail: summarizing ? done : dataLoaded ? current : skipped },
    { label: label('汇总结果', 'Summarize'), state: summarizing ? activeState : 'idle', detail: summarizing ? current : skipped },
  ]
})
const tab = ref('samples')
const tabs = computed(() => [{ id: 'samples', label: label('最近处理文件', 'Recent files') }, { id: 'log', label: label('运行日志', 'Run log') }])

function downloadLog(): void {
  const task = props.task
  downloadEvaluationJson(`${task.task_id}-execution.json`, {
    task_id: task.task_id, state: task.state, started_at: task.started_at, finished_at: task.finished_at,
    progress: task.progress, events: task.events ?? [],
  })
}
</script>

<style scoped>
.evaluation-run { gap:14px; }
.evaluation-run :deep(.page-header) { align-items:flex-end; }
.evaluation-run :deep(.page-actions > .ui-button--primary) { order:0; }
.evaluation-run > .resource-section { padding:16px 18px; }
.evaluation-run__title { display:flex; align-items:center; flex-wrap:wrap; gap:6px 12px; min-width:0; }
.evaluation-run__title h1 { display:block; margin:0; }
.evaluation-run__back { justify-self:start; }
.evaluation-run__source, .evaluation-run__metrics dl, .evaluation-run__counts { margin:0; }
.evaluation-run__source { display:flex; flex-wrap:wrap; gap:10px 18px; padding:13px 16px; }
.evaluation-run__source > div:not(:last-child) { border-inline-end:1px solid var(--am-border); padding-inline-end:18px; }
.evaluation-run dt { color:var(--am-text-muted); }
.evaluation-run dd { margin:4px 0 0; overflow-wrap:anywhere; }
.evaluation-run__metrics dl { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); text-align:center; }
.evaluation-run__metrics dl > div + div, .evaluation-run__counts > div + div { border-inline-start:1px solid var(--am-border); }
.evaluation-run__metrics p, .evaluation-run__empty { margin:0; color:var(--am-text-muted); }
.evaluation-run__metrics p { text-align:center; }
.evaluation-run__metrics dd, .evaluation-run__counts dd { font-size:20px; font-weight:650; font-variant-numeric:tabular-nums; }
.evaluation-run__progress { display:flex; flex-wrap:wrap; align-items:center; gap:16px 22px; }
.evaluation-run__steps { flex:1 1 265px; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); padding:0; margin:0; list-style:none; }
.evaluation-run__steps li { position:relative; display:grid; justify-items:center; align-content:start; gap:4px; text-align:center; color:var(--am-text-muted); font-size:12px; }
.evaluation-run__steps li strong { color:var(--am-text); }
.evaluation-run__steps li:not(:last-child)::after { content:''; position:absolute; top:15px; left:calc(50% + 20px); width:calc(100% - 40px); border-top:1px dashed var(--am-border-strong); }
.evaluation-run__steps li.is-done::after { border-color:var(--am-brand-primary); border-top-style:solid; }
.evaluation-run__mark { display:grid; place-items:center; width:31px; height:31px; border:1px solid var(--am-border); border-radius:50%; }
:is(.is-done,.is-current) > .evaluation-run__mark { color:var(--am-brand-on-primary); background:var(--am-brand-primary); border-color:transparent; }
.is-stopped > .evaluation-run__mark { color:var(--am-neutral-text); background:var(--am-surface-muted); }
.evaluation-run__counts { flex:1 1 290px; display:grid; grid-template-columns:minmax(110px,2fr) repeat(2,minmax(60px,1fr)); gap:10px; }
.evaluation-run__counts > div + div { padding-inline-start:12px; }
.evaluation-run__counts .task-progress { width:100%; }
.evaluation-run--cancelled .evaluation-run__counts .task-progress { --am-progress-fill:var(--am-text-muted); --am-progress-text:var(--am-text-muted); }
.evaluation-run__log-panel :deep(.local-tabs) { width:100%; border-bottom:1px solid var(--am-border); }
.evaluation-run__log-panel :deep(.local-tabs__tab.is-active) { border-bottom:2px solid var(--am-brand-primary); border-radius:0; background:transparent; }
.evaluation-run__log-panel > .evaluation-run__table { margin:0; }
.evaluation-run__table table { min-width:0; table-layout:fixed; }
.evaluation-run__table :is(th,td) { white-space:normal; overflow-wrap:anywhere; }
.evaluation-run__table :is(th,td):first-child { width:68px; }
.evaluation-run__table :is(th,td):last-child { width:26%; }
.evaluation-run__log { margin:0; padding:0; list-style:none; display:grid; gap:8px; }
.evaluation-run__log li { display:flex; flex-wrap:wrap; gap:4px 12px; overflow-wrap:anywhere; }
.evaluation-run__log time { color:var(--am-text-muted); }
@media (max-width:1100px) {
  .evaluation-run__title h1 { font-size:22px; }
  .evaluation-run :deep(.page-actions > .ui-button) { padding-inline:9px; }
}
</style>
