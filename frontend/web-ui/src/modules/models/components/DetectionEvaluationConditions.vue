<template>
  <section class="evaluation-conditions" :aria-label="label('执行条件', 'Execution conditions')">
    <details v-for="group in groups" :key="group.title" class="evaluation-conditions__group" open>
      <summary>{{ group.title }}<ChevronDown :size="16" aria-hidden="true" /></summary>
      <dl>
        <div v-for="field in group.fields" :key="field.label">
          <dt>{{ field.label }}</dt>
          <dd>{{ field.value }}</dd>
          <dd v-if="field.notes?.length" class="evaluation-conditions__notes">
            <span v-for="note in field.notes" :key="note">{{ note }}</span>
          </dd>
        </div>
      </dl>
    </details>
    <div v-if="canRetry" class="evaluation-conditions__actions">
      <ButtonLink size="sm" :to="{ path: '/models', query: { tab: 'evaluation', retry: task.task_id } }">
        <RotateCcw :size="16" :stroke-width="1.75" />
        {{ label('修改规则并重评', 'Edit rules and run again') }}
      </ButtonLink>
      <p>{{ label('重评会生成新的任务和报告。', 'Re-evaluation creates a new task and report.') }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useCatalogVersionLabel } from '../composables/useCatalogVersionLabel'
import { computed } from 'vue'
import { ChevronDown, RotateCcw } from '@lucide/vue'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import { evaluationRuntime } from '../detection-evaluation-comparison'
import { formatSmallModelNumber } from '../model-number-format'
import type { DetectionEvaluationReport, DetectionEvaluationTask } from '../services/model-evaluation.service'

const props = defineProps<{ task: DetectionEvaluationTask; report: DetectionEvaluationReport['payload']; canRetry: boolean; zh: boolean }>()
const modelVersionName = useCatalogVersionLabel(() => [props.task.project_id, 'detection', props.task.model_version_id])
const label = (zh: string, en: string) => props.zh ? zh : en
const notRecorded = computed(() => label('未记录', 'Not recorded'))
const text = (value: unknown): string => typeof value === 'string' && value.trim() ? value : notRecorded.value
const number = (value: number | null | undefined): string => value != null && Number.isFinite(value) ? formatSmallModelNumber(value) : notRecorded.value
const pixelNormalization = computed(() => {
  switch (props.report.execution?.model_input_spec?.normalization) {
    case 'zero-to-one': return label('除以 255，缩放至 0–1', 'Divide by 255, scale to 0–1')
    case 'none': return label('不归一化', 'None')
    case 'imagenet': return 'ImageNet'
    default: return text(props.report.execution?.model_input_spec?.normalization)
  }
})

const resizeMethod = computed(() => {
  const method = props.report.execution?.model_input_spec?.preprocess
  switch (method) {
    case 'letterbox': return 'Letterbox'
    case 'yolox-top-left-letterbox': return label('Letterbox（左上对齐）', 'Letterbox (top-left)')
    case 'resize': return label('缩放', 'Resize')
    case 'resize-center-crop': return label('缩放并居中裁剪', 'Resize and center crop')
    default: return text(method)
  }
})

interface ConditionGroup {
  title: string
  fields: Array<{ label: string; value: string; notes?: string[] }>
}

const groups = computed<ConditionGroup[]>(() => {
  const { task, report } = props
  const { execution, curves, duration_seconds: seconds } = report
  const input = execution?.input_size
  const coverage = report.coverage ?? task.report_summary.coverage
  const count = report.sample_count ?? task.report_summary.sample_count
  const split = report.split_name || task.report_summary.split_name
  return [
    {
      title: label('数据来源', 'Sources'),
      fields: [
        {
          label: label('源模型', 'Model'), value: text(execution?.model_name || task.model_type),
          notes: modelVersionName.value ? [modelVersionName.value] : undefined,
        },
        { label: label('框架与精度', 'Runtime and precision'), value: evaluationRuntime({ task, report }) },
        { label: label('评估权重', 'Evaluation weights'), value: text(execution?.runtime_artifact_file_id) },
        {
          label: label('评估数据', 'Evaluation data'), value: text(task.dataset_version_id),
          notes: [task.dataset_export_id, split && count != null ? `${split} · ${count} ${label('张图像', 'images')}` : split]
            .filter((item): item is string => Boolean(item)),
        },
      ],
    },
    {
      title: label('预处理（模型契约）', 'Preprocessing (model contract)'),
      fields: [
        { label: label('输入尺寸', 'Input size'), value: input ? `${input.width} × ${input.height}` : notRecorded.value },
        { label: label('通道顺序', 'Color space'), value: text(execution?.model_input_spec?.color_space) },
        { label: label('归一化', 'Normalization'), value: pixelNormalization.value },
        { label: label('缩放方式', 'Resizing'), value: resizeMethod.value },
      ],
    },
    {
      title: label('评估规则', 'Evaluation rules'),
      fields: [
        { label: label('评估指标', 'Metrics'), value: 'mAP50–95 / mAP50' },
        { label: label('指标候选最低分', 'Metric score floor'), value: number(curves?.score_floor) },
        { label: label('置信度工作点', 'Confidence operating point'), value: number(curves?.working_point ?? report.score_threshold) },
        { label: label('匹配 IoU', 'Matching IoU'), value: number(curves?.iou_threshold) },
        { label: label('NMS 阈值', 'NMS threshold'), value: report.nms_threshold === null ? label('未使用', 'Not used') : number(report.nms_threshold) },
      ],
    },
    {
      title: label('执行配置', 'Run configuration'),
      fields: [
        { label: label('推理设备', 'Device'), value: text(execution?.device_name) },
        { label: label('批大小', 'Batch size'), value: number(execution?.batch_size) },
        { label: label('完成样本数', 'Evaluated samples'), value: coverage ? `${coverage.succeeded} / ${coverage.requested}` : number(count) },
        { label: label('耗时', 'Duration'), value: typeof seconds === 'number' && Number.isFinite(seconds) ? `${Math.round(seconds * 1000).toLocaleString()} ms` : notRecorded.value },
      ],
    },
  ]
})
</script>

<style scoped>
.evaluation-conditions { display:grid; gap:10px; min-width:0; }
.evaluation-conditions__group { border:1px solid var(--am-border); border-radius:8px; background:var(--am-surface); }
.evaluation-conditions__group summary {
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  padding:10px 14px;
  border-radius:7px;
  background:var(--am-surface-muted);
  font-weight:600;
  cursor:pointer;
  list-style:none;
}
.evaluation-conditions__group summary::-webkit-details-marker { display:none; }
.evaluation-conditions__group[open] summary { border-end-start-radius:0; border-end-end-radius:0; }
.evaluation-conditions__group[open] summary svg { transform:rotate(180deg); }
.evaluation-conditions__group dl { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,110px),1fr)); gap:12px 16px; margin:0; padding:12px 14px; }
.evaluation-conditions__group dl > div { min-width:0; padding-inline-start:12px; border-inline-start:1px solid var(--am-border); }
.evaluation-conditions__group dt { color:var(--am-text-muted); }
.evaluation-conditions__group dd { margin:4px 0 0; overflow-wrap:anywhere; }
.evaluation-conditions__notes { display:grid; gap:2px; color:var(--am-text-muted); font-size:var(--am-type-caption); }
.evaluation-conditions__actions { display:flex; flex-wrap:wrap; align-items:center; justify-content:flex-end; gap:8px 12px; }
.evaluation-conditions__actions p { margin:0; color:var(--am-text-muted); }
</style>
