<template>
  <section class="resource-section validation-failure" :aria-label="label('输出差异', 'Output differences')">
    <header><h2>{{ label('校验结果', 'Validation results') }}</h2></header>
    <div class="validation-overview">
      <dl class="validation-statistics">
        <div><dt>{{ label('校验项', 'Checks') }}</dt><dd>{{ details.check_count }}</dd></div>
        <div><dt>{{ label('通过', 'Passed') }}</dt><dd class="validation-passed">{{ passedCount }}</dd></div>
        <div><dt>{{ label('失败', 'Failed') }}</dt><dd class="validation-rejected">{{ failedCount }}</dd></div>
      </dl>
      <div class="validation-rule">
        <h3>{{ label('当前校验规则', 'Validation rule') }}</h3>
        <p v-if="image">{{ peakLabel }} ≤ {{ number(details.max_error_limit) }} · {{ label('平均误差', 'Mean error') }} ≤ {{ number(details.mean_error_limit) }}</p>
        <p v-else>{{ label('逐元素容差', 'Per-element tolerance') }} = {{ number(details.absolute_tolerance) }} + {{ number(details.relative_tolerance) }} × |{{ label('转换输出值', 'converted value') }}|</p>
        <p>{{ peakLabel }} <strong class="validation-rejected">{{ number(maximumError) }}</strong></p>
      </div>
    </div>
    <InlineError v-if="active === null" :message="downloadError" />
    <TabList v-model="tab" :tabs="tabs" :label="label('校验明细', 'Validation details')" />
    <div v-if="tab === 'failures'" class="validation-count">
      <span>{{ image ? label(`${details.sample_count} 张验证图片 · `, `${details.sample_count} validation images · `) : label('生成的测试输入 · ', 'Generated test input · ') }}{{ label(`${details.failures.length} / ${details.check_count} 项未通过`, `${details.failures.length} of ${details.check_count} checks failed`) }}</span>
    </div>
    <div v-if="tab === 'failures'" class="resource-table validation-table">
      <table><thead><tr>
        <th scope="col">{{ image ? label('校验样本', 'Validation sample') : label('输出张量', 'Output tensor') }}</th>
        <th v-if="image" scope="col">Profile</th>
        <th scope="col">{{ label('最大误差', 'Maximum error') }}</th>
        <th scope="col">{{ label('超限项', 'Limit exceeded') }}</th>
        <th scope="col">{{ label('操作', 'Action') }}</th>
      </tr></thead><tbody>
        <tr v-for="(row, index) in details.failures" :key="index">
          <td><span class="validation-name" :title="row.sample_name ?? row.output_name">{{ row.sample_name ?? row.output_name }}</span></td>
          <td v-if="image">{{ row.profile }}</td><td>{{ number(row.max_error) }}</td>
          <td>{{ failedRule(row) }}</td>
          <td><Button size="sm" variant="ghost" @click="active = index"><Search :size="14" />{{ label('查看差异', 'View details') }}</Button></td>
        </tr>
      </tbody></table>
    </div>
    <dl v-else class="validation-statistics validation-statistics--detail">
      <div><dt>{{ label('参考运行时', 'Reference runtime') }}</dt><dd>{{ details.source_runtime }}</dd></div>
      <div><dt>{{ label('目标运行时', 'Target runtime') }}</dt><dd>{{ details.target_runtime }}</dd></div>
      <div><dt>{{ peakLabel }}</dt><dd>{{ number(maximumError) }}</dd></div>
      <div v-if="image"><dt>{{ label('验证图片', 'Validation images') }}</dt><dd>{{ details.sample_count }}</dd></div>
    </dl>
    <div class="validation-notice" role="status"><CircleAlert :size="18" /><span>{{ label('数值校验未通过，产物未登记', 'Numerical validation failed. The artifact was not registered.') }}</span></div>
  </section>

  <SideDrawer :open="active !== null" :title="label('输出差异详情', 'Output difference details')" :close-label="label('关闭', 'Close')" plain @close="active = null">
    <div v-if="selected && active !== null" class="diagnostic-content">
      <nav class="diagnostic-nav" :aria-label="label('差异导航', 'Difference navigation')">
        <span>{{ label(`第 ${active + 1} 项 / 共 ${details.failures.length} 项`, `${active + 1} of ${details.failures.length}`) }}</span>
        <div>
          <Button size="sm" variant="secondary" :disabled="active === 0" :aria-label="label('上一项', 'Previous')" @click="active--"><ChevronLeft :size="16" /></Button>
          <Button size="sm" variant="secondary" :disabled="active === details.failures.length - 1" :aria-label="label('下一项', 'Next')" @click="active++"><ChevronRight :size="16" /></Button>
        </div>
      </nav>
      <div class="diagnostic-sample"><strong>{{ selected.sample_name ?? selected.output_name }}</strong><p>{{ details.source_runtime }} → {{ details.target_runtime }}<template v-if="selected.profile"> · {{ selected.profile }} profile</template></p></div>
      <section class="diagnostic-panel">
        <h3>{{ label('输出数值', 'Output values') }}</h3>
        <p>{{ selected.output_name }} · {{ label('张量索引（从 0 开始）', 'Zero-based tensor index') }} [{{ selected.index.join(', ') }}]</p>
        <dl class="diagnostic-values">
          <div><dt>{{ label('参考值', 'Reference value') }}</dt><dd>{{ number(selected.source_value) }}</dd></div>
          <div><dt>{{ label('转换输出值', 'Converted value') }}</dt><dd>{{ number(selected.target_value) }}</dd></div>
          <div><dt>{{ image ? peakLabel + ' / ' + label('上限', 'Limit') : label('此处绝对误差 / 容差', 'Absolute error / tolerance at this index') }}</dt><dd>{{ number(image ? selected.max_error : selected.absolute_error) }} / {{ number(image ? details.max_error_limit : selected.allowed_error) }}</dd></div>
          <div><dt>{{ image ? label('平均误差 / 上限', 'Mean error / limit') : label('张量最大绝对误差', 'Maximum tensor error') }}</dt><dd>{{ image ? `${number(selected.mean_error)} / ${number(details.mean_error_limit)}` : number(selected.max_error) }}</dd></div>
        </dl>
        <p><strong>{{ label('超限项：', 'Limit exceeded: ') }}{{ failedRule(selected) }}</strong></p>
      </section>
      <details class="diagnostic-panel">
        <summary>{{ label('技术细节', 'Technical details') }}</summary>
        <dl class="diagnostic-values">
          <div><dt>{{ label('输入张量', 'Input tensor') }}</dt><dd>{{ selected.input_shape.join(' × ') || 'Scalar' }} · {{ selected.input_dtype }}</dd></div>
          <div><dt>{{ label('输出张量', 'Output tensor') }}</dt><dd>{{ selected.output_shape.join(' × ') || 'Scalar' }} · {{ selected.output_dtype }}</dd></div>
        </dl>
        <p>{{ image ? label('两端使用相同的 LetterBox 输入。坐标值按输入宽高归一化，分类分数直接比较。', 'Both runtimes use the same LetterBox input. Coordinates are normalized by input size and scores are compared directly.') : label(`两端使用同一个生成的输入。逐元素容差 = ${number(details.absolute_tolerance)} + ${number(details.relative_tolerance)} × |转换输出值|。`, `Both runtimes use the same generated input. Point tolerance = ${number(details.absolute_tolerance)} + ${number(details.relative_tolerance)} × |converted value|.`) }}</p>
      </details>
      <InlineError :message="downloadError" />
    </div>
    <template #footer>
      <Button size="sm" variant="secondary" :loading="downloading" :disabled="downloading" @click="emit('download')"><Download :size="16" />{{ label('下载校验诊断', 'Download diagnostics') }}</Button>
      <Button size="sm" variant="secondary" @click="active = null">{{ label('关闭详情', 'Close details') }}</Button>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { ChevronLeft, ChevronRight, CircleAlert, Download, Search } from '@lucide/vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from '@/shared/ui/components/Button.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'
import type { ConversionValidationFailureDetails, ConversionValidationFailureRow } from '../conversion-validation-failure'
import { formatSmallModelNumber } from '../model-number-format'

const props = defineProps<{ details: ConversionValidationFailureDetails; downloading: boolean; downloadError: string | null }>()
const emit = defineEmits<{ download: [] }>()
const { locale } = useI18n()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const image = computed(() => props.details.input_kind === 'validation_image')
const tab = ref('failures')
const tabs = computed(() => [
  { id: 'failures', label: `${image.value ? label('失败样本校验', 'Failed sample checks') : label('失败输出', 'Failed outputs')} (${props.details.failures.length})` },
  { id: 'statistics', label: label('校验统计', 'Statistics') },
])
const failedCount = computed(() => props.details.failed_check_count ?? props.details.failures.length)
const passedCount = computed(() => props.details.check_count - failedCount.value)
const peakLabel = computed(() => props.details.peak_rule === 'p99' ? label('P99 误差', 'P99 error') : label('最大误差', 'Maximum error'))
const maximumError = computed(() => props.details.failures.reduce((max, row) => Math.max(max, row.max_error), 0))
const active = ref<number | null>(null)
const selected = computed(() => active.value === null ? null : props.details.failures[active.value])
const number = (value?: number) => formatSmallModelNumber(value ?? NaN)

function failedRule(row: ConversionValidationFailureRow) {
  if (!image.value) return label('逐元素容差', 'Per-element tolerance')
  const exceeded: string[] = []
  if (row.max_error > (props.details.max_error_limit ?? Infinity)) exceeded.push(peakLabel.value)
  if (row.mean_error > (props.details.mean_error_limit ?? Infinity)) exceeded.push(label('平均误差', 'Mean error'))
  return exceeded.join(' / ')
}
</script>

<style scoped>
.validation-failure, .diagnostic-content { display: grid; gap: 16px; min-width: 0; }
.validation-overview { display:flex; flex-wrap:wrap; gap:16px 22px; }
.validation-statistics { flex:1 1 240px; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:0; }
.validation-statistics > div + div { border-inline-start:1px solid var(--am-border); padding-inline-start:12px; }
.validation-statistics dt, .validation-rule p { color:var(--am-text-muted); }
.validation-statistics dd { margin:4px 0 0; font-size:22px; font-weight:650; overflow-wrap:anywhere; }
.validation-statistics--detail { grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); }
.validation-statistics--detail dd { font-size:14px; }
.validation-passed { color:var(--am-success-text); }
.validation-rejected { color:var(--am-danger-text); }
.validation-rule { flex:1 1 220px; border-inline-start:1px solid var(--am-border); padding-inline-start:16px; }
.validation-rule :is(h3,p) { margin:0; }
.validation-rule p { margin-block-start:5px; }
.validation-table .ui-button { color:var(--am-action-primary-strong); }
.validation-failure > .validation-table { margin:0; border:1px solid var(--am-border); border-radius:6px; }
.validation-failure :deep(.local-tabs) { width:100%; border-bottom:1px solid var(--am-border); }
.validation-failure :deep(.local-tabs__tab) { border-bottom:2px solid transparent; border-radius:0; }
.validation-failure :deep(.local-tabs__tab.is-active) { border-bottom-color:var(--am-brand-primary); background:transparent; }
.validation-count, .diagnostic-nav, .diagnostic-nav > div { display: flex; align-items: center; justify-content: space-between; gap: 8px 16px; flex-wrap: wrap; }
.diagnostic-content h3 { margin: 0; }
.diagnostic-content p { margin: 4px 0 0; color: var(--am-text-muted); }
.validation-notice { display: flex; gap: 12px; padding: 12px 14px; border: 1px solid var(--am-border); border-radius: 8px; background: var(--am-surface-subtle); }
.validation-notice svg { flex: none; }
.validation-count span, .diagnostic-nav > span { color: var(--am-text-muted); }
.validation-table table { table-layout: fixed; width: 100%; min-width: 0; }
.validation-table :is(th, td):first-child { width: 38%; }
.validation-table :is(th, td):last-child { width: 128px; }
.validation-table td { white-space: normal; overflow-wrap: anywhere; }
.validation-name { display: block; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.diagnostic-content { overflow-wrap: anywhere; }
.diagnostic-sample, .diagnostic-panel { padding: 14px; border: 1px solid var(--am-border); border-radius: 8px; background: var(--am-surface-subtle); }
.diagnostic-panel summary { cursor: pointer; font-weight: 600; }
.diagnostic-values { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 12px 0; }
.diagnostic-values dt { color: var(--am-text-muted); }
.diagnostic-values dd { margin: 4px 0 0; font-weight: 600; font-variant-numeric: tabular-nums; }
</style>
