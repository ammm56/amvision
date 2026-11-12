<template>
  <div class="dataset-job-result" :class="{ 'dataset-job-result--created': created }">
    <div v-if="created" class="dataset-result-title">
      <CircleCheck :size="28" aria-hidden="true" />
      <div><h2>{{ label('版本已创建', 'Version created') }}</h2>
        <p v-if="sourceName || sourceNumber">{{ sourceName }}<span v-if="sourceNumber"> · {{ label('来源版本', 'Source version') }} v{{ sourceNumber }}</span></p>
      </div>
      <span class="dataset-result-date">{{ datasetDate(job.finished_at || job.created_at) }}</span>
    </div>
    <div v-else class="dataset-heading">
      <StatusBadge
        :status="job.state"
        :label="text(job.state)"
        :tone="job.state === 'cancelled' ? 'neutral' : undefined"
      /><span>{{ datasetDate(job.finished_at || job.created_at) }}</span>
    </div>
    <InlineError v-if="job.error_message" :message="job.error_message" />
    <progress
      v-if="['queued', 'running'].includes(job.state)"
      :value="job.progress.percent"
      max="100"
      :aria-label="label('执行进度', 'Progress')"
    />
    <template v-if="job.state === 'succeeded' && job.result">
      <InlineError
        v-if="job.result.can_create === false"
        :message="
          label(
            '回传存在阻止项，请修正数据或调整缺失/图片变更选项后重新检查。',
            'Returned data has blockers. Correct the data or review missing/image change options, then check again.',
          )
        "
      />
      <dl :class="created ? 'dataset-result-metrics' : 'dataset-details'">
        <template
          v-for="key in summaryKeys.filter(
            (key) => typeof job.result?.[key] === 'number',
          )"
          :key="key"
          ><dt>{{ fieldName(key) }}</dt>
          <dd>{{ job.result[key] }}</dd></template
        >
        <template v-if="job.result.split_counts && job.operation !== 'revise' && !created"
          ><dt>train / val / test</dt>
          <dd>
            {{
              ['train', 'val', 'test']
                .map((key) => job.result?.split_counts[key] ?? 0)
                .join(' / ')
            }}
          </dd></template
        >
        <template v-for="(value, key) in job.result.counts || {}" :key="key"
          ><dt>{{ countName(String(key)) }}</dt>
          <dd>{{ value }}</dd></template
        >
      </dl>

      <div v-if="created && job.result.split_counts" class="dataset-result-splits">
        <h3>{{ text('splits') }}</h3>
        <p>{{ ['train', 'test', 'val'].map(key => `${key} ${(job.result?.split_counts[key] ?? 0).toLocaleString()}`).join(' / ') }}</p>
      </div>
      <p
        v-if="!created &&
          job.result.group_key === '' &&
          !['quality', 'revise'].includes(job.operation)
        "
        class="dataset-muted"
      >
        {{
          label(
            '未配置分组；划分按单张图片进行。',
            'No grouping configured; splits use individual images.',
          )
        }}
      </p>
      <ResourceTable
        v-if="rows.length"
        class="dataset-table"
        :label="label('检查结果', 'Results')"
        ><thead>
          <tr>
            <th>{{ text('fileName') }}</th>
            <th>{{ label('结果', 'Result') }}</th>
            <th>{{ text('actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in rows" :key="i">
            <td :title="row.file_name">{{ row.file_name }}</td>
            <td :title="row.message">
              {{ row.message || row.kinds?.map(fieldName).join('、') }}
            </td>
            <td>
              <Button
                size="sm"
                @click="
                  emit(
                    'sample',
                    row.sample_id,
                    row.kinds?.includes('removed')
                      ? undefined
                      : job.result?.compare_version_id ||
                          job.result?.returned_version_id,
                  )
                "
                >{{ text('view') }}</Button
              >
            </td>
          </tr>
        </tbody></ResourceTable
      >
      <p v-if="job.result.truncated" class="dataset-muted">
        {{
          label(
            '仅展示前 200 条问题；总数包含全部检查结果。',
            'Showing the first 200 issues; counts include all results.',
          )
        }}
      </p>
      <div v-if="job.result.created_version_id || job.result.updated_version_id" class="dataset-result-actions"><Button
        :variant="created ? 'primary' : 'secondary'"
        @click="emit('version', job.result.updated_version_id || job.result.created_version_id)"
        >{{ job.result.updated_version_id ? label('查看数据集', 'View dataset') : label('查看新版本', 'View new version') }}</Button
      ></div>
    </template>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck } from '@lucide/vue'
import { useI18n } from 'vue-i18n'
import Button from '@/shared/ui/components/Button.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { datasetDate, useDatasetText } from '../dataset-workspace'
import type { DatasetJob } from '../services/dataset-workspace.service'
const props = defineProps<{ job: DatasetJob; sourceName?: string; sourceNumber?: number }>()
const emit = defineEmits<{
  sample: [id: string, version?: string]
  version: [id: string]
}>()
const { locale } = useI18n(),
  text = useDatasetText(),
  label = (zh: string, en: string) =>
    locale.value.startsWith('zh') ? zh : en
const created = computed(() => props.job.operation === 'derive' && props.job.state === 'succeeded' && !!props.job.result?.created_version_id)
const summaryKeys = computed(() =>
  created.value
    ? ['source_count', 'sample_count', 'excluded_count', ...(props.job.result?.split_changed ? ['split_changed'] : [])]
    :
  props.job.operation === 'revise'
    ? ['source_count', 'excluded_count', 'sample_count']
    : [
        'source_count',
        'target_count',
        'sample_count',
        'excluded_count',
        'split_changed',
        'group_count',
        'issue_count',
      ],
)
const rows = computed(
  () => props.job.result?.issues || props.job.result?.changes || [],
)
const countName = (key: string) =>
  props.job.operation === 'compare'
    ? {
        categories: label('类别变化样本', 'Samples with class changes'),
        annotations: label('标注变化样本', 'Samples with annotation changes'),
        split: label('划分变化样本', 'Samples with split changes'),
        image: label('图片变化样本', 'Samples with image changes'),
        cloud: label('点云变化样本', 'Samples with point cloud changes'),
        depth: label('深度变化样本', 'Samples with depth changes'),
        mask: label('掩膜变化样本', 'Samples with mask changes'),
        calibration: label('标定变化样本', 'Samples with calibration changes'),
        media_metadata: label('媒体信息变化样本', 'Samples with media metadata changes'),
        added: label('新增样本', 'Added samples'),
        removed: label('移除样本', 'Removed samples'),
      }[key] || fieldName(key)
    : fieldName(key)
const fieldName = (key: string) =>
  ({
    source_count: label('来源样本', 'Source samples'),
    target_count: label('目标样本', 'Target samples'),
    sample_count: text('samples'),
    excluded_count: label('移除样本', 'Removed samples'),
    split_changed: label('划分变化', 'Split changes'),
    group_count: label('分组数量', 'Groups'),
    issue_count: label('检查提示', 'Issues'),
    unreadable_image: label('图片不可读', 'Unreadable images'),
    image_size: label('尺寸不一致', 'Size mismatch'),
    duplicate_image: label('内容相同图片', 'Identical images'),
    empty_annotation: label('无标注样本', 'Empty annotations'),
    unknown_category: label('未知类别', 'Unknown categories'),
    invalid_geometry: label('几何无效', 'Invalid geometry'),
    added: label('新增', 'Added'),
    removed: label('移除', 'Removed'),
    annotations: text('annotation'),
    categories: text('classes'),
    split: text('splits'),
    image: label('图片变化', 'Image changed'),
    cloud: label('原始点云变化', 'Source point cloud changed'),
    depth: label('原始深度变化', 'Source depth changed'),
    mask: label('原始掩膜变化', 'Source mask changed'),
    calibration: label('标定资料变化', 'Calibration changed'),
    media_metadata: label('单位、标定参数或样本信息变化', 'Units, calibration parameters or sample metadata changed'),
    changed_samples: label('变化样本', 'Changed samples'),
    matched: label('匹配样本', 'Matched samples'),
    unknown: label('身份不匹配', 'Unmatched identity'),
    duplicate: label('重复身份', 'Duplicate identity'),
    missing: label('未回传样本', 'Missing samples'),
    image_changed: label('图片内容变化', 'Changed images'),
    category_conflicts: label('类别冲突', 'Class conflicts'),
  })[key] || key
</script>
<style scoped>
.dataset-job-result {
  display: grid;
  gap: 16px;
}
.dataset-job-result progress {
  width: 100%;
  accent-color: var(--am-brand-primary);
}

.dataset-result-title { display: flex; align-items: center; gap: 12px; min-width: 0; }
.dataset-result-title > svg { color: var(--am-brand-primary); flex-shrink: 0; }
.dataset-result-title h2 { margin: 0; font-size: 18px; font-weight: 600; }
.dataset-result-title p { margin: 5px 0 0; color: var(--am-text-muted); font-size: 13px; overflow-wrap: anywhere; }
.dataset-result-date { margin-left: auto; color: var(--am-text-muted); font-size: 13px; white-space: nowrap; }
.dataset-result-metrics { display: grid; grid-auto-flow: column; grid-template-rows: auto auto; grid-auto-columns: minmax(0, 1fr); gap: 8px 24px; margin: 4px 0; padding: 20px; border-radius: var(--am-radius-md); background: var(--am-hover-surface); }
.dataset-result-metrics dt { color: var(--am-text-muted); font-size: 13px; }
.dataset-result-metrics dd { margin: 0; font-size: 24px; line-height: 32px; font-variant-numeric: tabular-nums; }
.dataset-result-splits h3 { font-size: 14px; font-weight: 600; margin: 0 0 8px; }
.dataset-result-splits p { margin: 0; font-size: 14px; overflow-wrap: anywhere; }
.dataset-result-actions { display: flex; justify-content: flex-end; }
@media (max-width: 1100px) {
  .dataset-result-title { flex-wrap: wrap; }
  .dataset-result-metrics { gap: 8px 16px; padding: 16px; }
}
</style>
