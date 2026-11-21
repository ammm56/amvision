<template>
  <SideDrawer :open="!!file" :title="fileTitle" :close-label="zh ? '关闭' : 'Close'" @close="$emit('close')">
    <div v-if="file" class="training-file-preview">
      <dl class="training-file-preview__metadata">
        <div><dt>{{ zh ? '大小' : 'Size' }}</dt><dd>{{ sizeLabel }}</dd></div>
        <div v-if="epoch != null"><dt>{{ zh ? '轮次' : 'Epoch' }}</dt><dd>{{ epoch }}</dd></div>
        <div v-if="file.updated_at"><dt>{{ zh ? '更新时间' : 'Updated' }}</dt><dd>{{ formatSystemDateTime(file.updated_at) }}</dd></div>
      </dl>
      <InlineError :message="downloadError" />
      <p v-if="loading" role="status">{{ zh ? '正在读取文件…' : 'Reading file…' }}</p>
      <template v-else-if="error">
        <InlineError :message="error" />
        <Button size="sm" @click="$emit('retry')">{{ zh ? '重试' : 'Retry' }}</Button>
      </template>
      <template v-else-if="detail">
        <pre v-if="detail.file_kind === 'text'" class="json-view">{{ detail.text_content ?? detail.lines.join('\n') }}</pre>
        <template v-else>
          <p v-if="testUnavailable">{{ zh ? '没有可用的独立测试结果。' : 'Independent test results are unavailable.' }}</p>
          <section v-if="metrics.length" class="training-file-preview__metrics">
            <h3>{{ zh ? '指标摘要' : 'Metrics summary' }}</h3>
            <div class="resource-table">
              <table>
                <thead><tr><th scope="col">{{ zh ? '指标' : 'Metric' }}</th><th scope="col">{{ zh ? '数值' : 'Value' }}</th></tr></thead>
                <tbody><tr v-for="[key, value] in metrics" :key="key"><th scope="row">{{ key }}</th><td>{{ formatMetric(key, value) }}</td></tr></tbody>
              </table>
            </div>
          </section>
          <details v-if="metrics.length" class="training-file-preview__raw" @toggle="rawOpen = ($event.target as HTMLDetailsElement).open">
            <summary>{{ zh ? '原始 JSON' : 'Raw JSON' }}</summary>
            <pre v-if="rawOpen" class="json-view">{{ rawContent }}</pre>
          </details>
          <pre v-else class="json-view">{{ rawContent }}</pre>
        </template>
      </template>
    </div>
    <template #footer>
      <Button v-if="file" variant="primary" :loading="downloading" :disabled="downloading" @click="$emit('download', file)">
        <Download :size="16" aria-hidden="true" />{{ zh ? '下载' : 'Download' }}
      </Button>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Download } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { formatLearningRate, formatModelNumber, formatTrainingMetric } from '../model-number-format'
import type { ModelTrainingOutputFileDetail, ModelTrainingOutputFileSummary } from '../services/model.service'

const props = defineProps<{
  file: ModelTrainingOutputFileSummary | null
  detail: ModelTrainingOutputFileDetail | null
  sizeLabel: string
  epoch?: number | null
  loading: boolean
  error: string | null
  downloading: boolean
  downloadError: string | null
}>()
defineEmits<{ close: []; retry: []; download: [file: ModelTrainingOutputFileSummary] }>()

const { locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const fileTitle = computed(() => props.file?.object_key?.split(/[\\/]/).pop() || props.file?.file_name || '')
const rawOpen = ref(false)
watch(() => props.file?.file_name, () => { rawOpen.value = false })
const rawContent = computed(() => JSON.stringify(props.detail?.payload ?? {}, null, 2))
const testUnavailable = computed(() =>
  props.detail?.file_name === 'test-metrics' && props.detail.payload.available === false,
)
const metrics = computed(() => {
  const payload = props.detail?.payload ?? {}
  const runtime = Array.isArray(payload.runtime_history) ? payload.runtime_history.at(-1)?.runtime : null
  const reportMetrics = props.detail?.file_name === 'test-metrics' ? payload.metrics : null
  const summary = payload.final_metrics ?? reportMetrics ?? payload.metrics_summary ?? runtime ?? payload
  if (!summary || typeof summary !== 'object' || Array.isArray(summary)) return []
  return Object.entries(summary).filter((entry): entry is [string, number] => typeof entry[1] === 'number' && Number.isFinite(entry[1]))
})

function formatMetric(name: string, value: number): string {
  if (name.endsWith('_ms')) return `${formatModelNumber(value, 0)} ms`
  if (name.endsWith('learning_rate')) return formatLearningRate(value)
  return formatTrainingMetric(value)
}
</script>

<style scoped>
.training-file-preview { display:grid; gap:18px; min-width:0; }
.training-file-preview :is(h3,p) { margin:0; }
.training-file-preview__metadata { display:flex; flex-wrap:wrap; gap:12px 24px; margin:0; }
.training-file-preview__metadata dt { color:var(--am-text-muted); }
.training-file-preview__metadata dd { margin:4px 0 0; overflow-wrap:anywhere; }
.training-file-preview__metrics { display:grid; gap:10px; min-width:0; }
.training-file-preview .resource-table table { width:100%; min-width:0; table-layout:fixed; }
.training-file-preview .resource-table :is(th,td) { white-space:normal; overflow-wrap:anywhere; }
.training-file-preview__raw { display:grid; padding:12px; border:1px solid var(--am-border); border-radius:var(--am-radius-sm); }
.training-file-preview__raw summary { cursor:pointer; font-weight:600; }
.training-file-preview .json-view { min-width:0; max-height:55dvh; margin:0; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; }
.training-file-preview__raw .json-view { margin-block-start:12px; }
</style>
