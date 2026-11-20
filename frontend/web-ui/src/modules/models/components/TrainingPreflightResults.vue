<template>
  <section class="training-preflight" :aria-label="text('检查训练配置', 'Review training configuration')">
    <h3>{{ text('检查训练配置', 'Training checks') }}</h3>
    <p v-if="loading" class="training-preflight__notice" role="status">{{ text('正在检查训练配置…', 'Checking training configuration…') }}</p>
    <div v-else-if="error" class="training-preflight__notice training-preflight__notice--warning">
      <TriangleAlert :size="18" aria-hidden="true" />
      <div role="alert">
        <strong>{{ failureSummary }}</strong>
        <p v-if="failedCount === 0">{{ error }}</p>
      </div>
      <Button v-if="editable" size="sm" type="button" @click="$emit('retry')">{{ text('重新检查', 'Check again') }}</Button>
    </div>
    <p v-else-if="passed" class="training-preflight__notice training-preflight__notice--success" role="status">
      <Check :size="16" aria-hidden="true" />{{ text('提交前检查通过', 'Preflight checks passed') }}
    </p>
    <div class="resource-table training-preflight__table">
      <table>
        <thead><tr><th scope="col">{{ text('检查项', 'Check') }}</th><th scope="col">{{ text('状态', 'Status') }}</th><th scope="col">{{ text('处理', 'Action') }}</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.check">
            <th scope="row">{{ row.label }}</th>
            <td>
              <span :class="'training-preflight__state--' + row.status">{{ statusLabels[row.status] }}</span>
              <span v-if="row.message" class="training-preflight__detail">{{ row.message }}</span>
              <details v-if="row.missing_files?.length" class="training-preflight__files">
                <summary>{{ text('查看缺失文件', 'View missing files') }} ({{ row.missing_files.length }})</summary>
                <ul><li v-for="path in row.missing_files" :key="path">{{ path }}</li></ul>
              </details>
            </td>
            <td>
              <Button v-if="row.status === 'failed' && row.step && editable" size="sm" type="button" :aria-label="row.action" @click="$emit('edit', row.step)">{{ row.action }}</Button>
              <span v-else aria-hidden="true">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Check, TriangleAlert } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import type { ModelTrainingPreflightCheck } from '../services/model.service'

const props = defineProps<{
  checks: ModelTrainingPreflightCheck[]
  loading: boolean
  passed: boolean
  error: string
  warmStart: boolean
  editable: boolean
  zh: boolean
}>()
defineEmits<{ retry: []; edit: [step: number] }>()
const text = (zh: string, en: string) => props.zh ? zh : en
const statusLabels = computed(() => ({
  passed: text('通过', 'Passed'),
  failed: text('未通过', 'Failed'),
  skipped: text('从头训练', 'From scratch'),
  deferred: text('由 Worker 确认', 'Checked by worker'),
  pending: text('待确认', 'Unconfirmed'),
}))
const rows = computed(() => {
  const items = [
    { check: 'dataset_export', label: text('数据导出', 'Dataset export'), action: text('返回数据', 'Back to data'), step: 2 },
    { check: 'initialization', label: text('初始化权重', 'Initialization weights'), action: text('返回初始化', 'Back to initialization'), step: 3 },
    { check: 'environment', label: text('执行环境', 'Execution environment') },
    { check: 'output_model', label: text('输出模型', 'Output model'), action: text('编辑输出名称', 'Edit output name'), step: 1 },
  ] as const
  return items.map(item => {
    const result = props.checks.find(check => check.check === item.check)
    const status: keyof typeof statusLabels.value = result?.status ??
      (item.check === 'environment' ? 'deferred' : item.check === 'initialization' && !props.warmStart ? 'skipped' : props.passed ? 'passed' : 'pending')
    return { ...item, step: 'step' in item ? item.step : undefined, action: 'action' in item ? item.action : '', status, message: result?.message, missing_files: result?.missing_files }
  })
})
const failedCount = computed(() => rows.value.filter(row => row.status === 'failed').length)
const failureSummary = computed(() => failedCount.value > 0
  ? text(`${failedCount.value} 项检查未通过，尚未创建训练任务`, `${failedCount.value} checks failed. Training task has not been created.`)
  : text('检查未完成，尚未创建训练任务', 'Checks are incomplete. Training task has not been created.'))
</script>

<style scoped>
.training-preflight { display: grid; gap: 12px; min-width: 0; padding: 14px; border: 1px solid var(--am-border); border-radius: 8px; background: var(--am-surface); }
.training-preflight h3, .training-preflight p { margin: 0; }
.training-preflight h3 { font-size: 15px; }
.training-preflight__notice { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 8px; }
.training-preflight__notice > div { flex: 1; min-width: 180px; overflow-wrap: anywhere; }
.training-preflight__notice svg { flex: none; }
.training-preflight__notice--warning { color: var(--am-warning-text); border: 1px solid var(--am-warning-border); background: var(--am-warning-surface); padding: 10px 12px; border-radius: 6px; }
.training-preflight__notice--success, .training-preflight__state--passed { color: var(--am-success-text); }
.training-preflight__state--failed { color: var(--am-danger-text); font-weight: 600; }
.training-preflight__detail { display: block; margin-block-start: 4px; color: var(--am-text-muted); }
.training-preflight__table table { width: 100%; min-width: 0; table-layout: fixed; }
.training-preflight__table :is(th, td) { overflow-wrap: anywhere; text-align: start; white-space: normal; }
.training-preflight__table :is(th, td):first-child { width: 24%; }
.training-preflight__table :is(th, td):last-child { width: 25%; }
.training-preflight__table :deep(.ui-button) { max-width: 100%; white-space: normal; }
.training-preflight__files { margin-block-start: 6px; }
.training-preflight__files summary { cursor: pointer; }
.training-preflight__files ul { margin-block-end: 0; padding-inline-start: 20px; }
@media (max-width: 650px) {
  .training-preflight__table :is(th, td) { padding-inline: 6px; }
}
</style>
