<template>
  <section class="package-check">
    <h3>{{ zh ? '检查结果' : 'Check results' }}</h3>
    <p v-if="pending" role="status">{{ zh ? '正在检查文件完整性和模型信息。' : 'Checking archive integrity and model information.' }}</p>
    <p v-else-if="record.state === 'failed' && failureIndex < 0" role="alert" class="package-check__failure">{{ problem }}</p>
    <div class="resource-table package-check__table">
      <table><thead><tr><th scope="col">{{ zh ? '检查项' : 'Check' }}</th><th scope="col">{{ zh ? '结果' : 'Result' }}</th><th scope="col">{{ zh ? '说明' : 'Details' }}</th></tr></thead>
        <tbody><template v-for="(row, index) in rows" :key="row.label">
          <tr :class="{ 'package-check__failure': row.bad }"><th scope="row">{{ row.label }}</th>
            <td><StatusBadge :tone="row.bad ? 'danger' : row.passed ? 'success' : 'neutral'" :label="row.bad ? t('未通过', 'Failed') : row.passed ? t('通过', 'Passed') : t('未确认', 'Not confirmed')" with-dot /></td>
            <td>{{ row.detail }}</td></tr>
          <tr v-if="row.bad && index === failureIndex" class="package-check__failure"><td colspan="3">
            <details open><summary>{{ t('错误详情', 'Error details') }}</summary>
              <p v-if="record.import_check?.member">{{ record.import_check.member }}</p>
              <p>{{ problem }}</p>
            </details>
          </td></tr>
        </template></tbody>
      </table>
    </div>
    <section v-if="checked && record.model">
      <h3>{{ t('将导入', 'To be imported') }}</h3>
      <div class="resource-table package-check__table package-check__inventory">
        <table><thead><tr><th scope="col">{{ t('类型', 'Type') }}</th><th scope="col">{{ t('名称', 'Name') }}</th><th scope="col">{{ t('大小', 'Size') }}</th></tr></thead>
          <tbody><tr><td>{{ t('模型版本', 'Model version') }}</td><td>{{ [record.model.model_name, packageSourceVersionLabel(record)].filter(Boolean).join(' · ') }}</td><td>—</td></tr>
            <tr v-for="entry in record.files" :key="`${entry.owner}/${entry.path}`"><td>{{ entry.owner === 'version' ? t('版本文件', 'Version file') : t('转换产物', 'Converted artifact') }}</td><td>{{ entry.path }}</td><td>{{ formatPackageBytes(entry.byte_size) }}</td></tr>
          </tbody>
        </table>
      </div>
      <details v-if="record.categories?.length" class="package-check__categories">
        <summary>
          <Tags :size="17" aria-hidden="true" />
          <strong>{{ t('类别顺序', 'Class order') }}</strong>
          <span>{{ t(`${record.categories.length} 个类别`, `${record.categories.length} classes`) }}</span>
          <ChevronDown :size="16" class="package-check__chevron" aria-hidden="true" />
        </summary>
        <ModelPackageClassTable class="package-check__category-table" :categories="record.categories" :zh="zh" />
      </details>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ChevronDown, Tags } from '@lucide/vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import ModelPackageClassTable from './ModelPackageClassTable.vue'
import { formatPackageBytes, packageSourceVersionLabel } from '../model-package-presentation'
import { modelTaskLabel } from '../model-evaluation-types'
import type { ModelPackageRecord } from '../services/model-package.service'
const props = defineProps<{ record: ModelPackageRecord; zh: boolean; pending: boolean }>()
const t = (zh: string, en: string) => props.zh ? zh : en
const checked = computed(() => !props.pending && ['ready', 'needs_attention'].includes(props.record.state) && !!props.record.model)
const problem = computed(() => props.record.import_check?.message || props.record.error || t('检查未完成，请重新选择文件。', 'Checks did not finish. Choose the file again.'))
const failureIndex = computed(() => props.record.state === 'failed' && props.record.import_check ? (props.record.import_check.phase === 'model' ? 2 : 0) : -1)
const inputSize = computed(() => props.record.input_size ? `${props.record.input_size.width} × ${props.record.input_size.height}` : '')
const rows = computed(() => [
  { label: t('包完整性', 'Package integrity'), passed: checked.value || failureIndex.value === 2, detail: t('ZIP 条目和 SHA-256 校验', 'ZIP entries and SHA-256') },
  { label: t('文件路径', 'File paths'), passed: checked.value || failureIndex.value === 2, detail: t('归档路径和文件清单', 'Archive paths and file manifest') },
  { label: t('模型结构', 'Model structure'), passed: checked.value, detail: checked.value ? `${props.record.model?.model_type}-${props.record.model?.model_scale}` : '—' },
  { label: t('任务类型', 'Task type'), passed: checked.value, detail: checked.value ? modelTaskLabel(props.record.model?.task_type, props.zh) : '—' },
  { label: t('输入尺寸（宽 × 高）', 'Input size (width × height)'), passed: checked.value && !!inputSize.value, detail: checked.value ? inputSize.value || '—' : '—' },
  { label: t('类别顺序', 'Class order'), passed: checked.value, detail: checked.value ? t(`${props.record.categories?.length ?? 0} 个类别`, `${props.record.categories?.length ?? 0} classes`) : '—' },
  { label: t('资源冲突', 'Target conflicts'), passed: false, detail: checked.value ? t('选择目标后检查', 'Checked after selecting a target') : '—' },
].map((row, index) => ({ ...row, bad: index === failureIndex.value, detail: index === failureIndex.value ? problem.value : row.detail })))
</script>

<style scoped>
.package-check,.package-check section { display:grid; gap:10px; min-width:0; }
.package-check :is(h3,p) { margin:0; }
.package-check__table table { table-layout:fixed; }
.package-check__table :is(th,td) { overflow-wrap:anywhere; white-space:normal; text-align:left; padding-block:8px; }
.package-check__table th:first-child { width:26%; }
.package-check__table th:nth-child(2) { width:24%; }
.package-check__inventory th:nth-child(2) { width:auto; }
.package-check__inventory tr > :last-child { width:105px; text-align:end; font-variant-numeric:tabular-nums; }
.package-check__failure { color:var(--am-danger-text); background:var(--am-danger-surface); }
.package-check__failure summary,.package-check__categories summary { cursor:pointer; }
.package-check__categories { border:1px solid var(--am-border); border-radius:6px; }
.package-check__categories summary { display:flex; align-items:center; gap:9px; min-height:42px; padding:8px 12px; list-style:none; }
.package-check__categories summary::-webkit-details-marker { display:none; }
.package-check__categories summary:hover { background:var(--am-hover-surface); }
.package-check__categories summary:focus-visible { outline-offset:-3px; }
.package-check__categories summary :is(span,svg) { color:var(--am-text-muted); }
.package-check__categories summary span { margin-inline-start:auto; font-size:var(--am-type-caption); }
.package-check__chevron { flex:none; }
.package-check__categories[open] .package-check__chevron { transform:rotate(180deg); }
.package-check__category-table { margin:0 12px 12px; }
</style>
