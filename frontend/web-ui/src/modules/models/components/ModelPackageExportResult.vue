<template>
  <section class="package-export-result" :aria-busy="checking">
    <h3>{{ zh ? '基本信息' : 'Overview' }}</h3>
    <div class="package-export-result__file">
      <FileArchive :size="24" aria-hidden="true" />
      <div><span>{{ zh ? '导出文件' : 'Export file' }}</span>
        <h3>{{ record.file_name || record.export_options?.file_name || '—' }}</h3></div>
    </div>
    <dl>
      <dt>{{ zh ? '来源版本' : 'Source version' }}</dt>
      <dd>{{ sourceVersionName || [record.model?.model_name, record.source?.source_version_label].filter(Boolean).join(' · ') || '—' }}</dd>
      <dt>{{ zh ? '提交时间' : 'Submitted' }}</dt><dd>{{ formatSystemDateTime(record.created_at) }}</dd>
      <dt>{{ zh ? '生成时间' : 'Generated' }}</dt><dd>{{ record.completed_at ? formatSystemDateTime(record.completed_at) : '—' }}</dd>
      <dt>{{ zh ? '文件大小' : 'File size' }}</dt><dd>{{ record.total_bytes == null ? '—' : formatBytes(record.total_bytes) }}</dd>
    </dl>
    <h3>{{ zh ? '状态信息' : 'Status' }}</h3>
    <dl role="status">
      <dt>{{ zh ? '任务状态' : 'Job status' }}</dt><dd><ModelPackageExportStatus :record="record" :zh="zh" part="task" /></dd>
      <dt>{{ zh ? '文件状态' : 'File status' }}</dt><dd><ModelPackageExportStatus :record="record" :zh="zh" part="file" /></dd>
    </dl>
    <p v-if="fileLabel" class="package-export-result__note">{{ zh
      ? '导出 ZIP 当前不可下载。重新生成前会检查原模型版本和所选产物。'
      : 'The ZIP is no longer downloadable. Regenerating checks the original version and selected artifacts.' }}</p>
    <p v-else-if="packagePending(record.state)" class="package-export-result__note">
      {{ zh ? '关闭面板不会取消生成，可在导出记录中查看进度。' : 'Closing this panel does not cancel generation. Follow the job in export records.' }}
    </p>
    <p v-if="record.error" role="alert" class="package-export-result__error">{{ record.error }}</p>
    <p v-if="selection" class="package-export-result__selection">{{ zh ? '选定产物：' : 'Selected artifacts: ' }}{{ selection }}</p>
    <div v-if="record.files?.length" class="resource-table package-export-result__files">
      <table><thead><tr><th scope="col">{{ zh ? '包内文件' : 'Package contents' }}</th><th scope="col">SHA-256</th></tr></thead>
        <tbody><tr v-for="file in record.files" :key="`${file.owner}/${file.path}`">
          <td :title="file.path">{{ file.path }}</td><td :title="file.sha256">{{ file.sha256.slice(0, 12) }}</td>
        </tr></tbody>
      </table>
    </div>
    <footer>
      <Button @click="$emit('close')">{{ closeLabel }}</Button>
      <Button :variant="canRegenerate ? 'secondary' : 'primary'" :loading="busy && canDownload" :disabled="checking || actionsBlocked || !canDownload" @click="$emit('download')">{{ zh ? '下载 ZIP' : 'Download ZIP' }}</Button>
      <Button v-if="canRegenerate" variant="primary" :loading="busy" :disabled="checking || actionsBlocked" @click="$emit('regenerate')">{{ zh ? '重新生成' : 'Regenerate' }}</Button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { useCatalogVersionLabel } from '../composables/useCatalogVersionLabel'
import { computed } from 'vue'
import { FileArchive } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { canDownloadModelPackage, canRegenerateModelPackage, packageExportFileLabel, packagePending, type ModelPackageRecord } from '../services/model-package.service'
import ModelPackageExportStatus from './ModelPackageExportStatus.vue'

const props = defineProps<{ record: ModelPackageRecord; projectId?: string; zh: boolean; closeLabel: string; busy: boolean; checking?: boolean; actionsBlocked?: boolean }>()
const sourceVersionName = useCatalogVersionLabel(() => [props.projectId, props.record.model?.task_type, props.record.source_version_id || props.record.export_options?.model_version_id])
defineEmits<{ close: []; download: []; regenerate: [] }>()
const canDownload = computed(() => canDownloadModelPackage(props.record))
const canRegenerate = computed(() => canRegenerateModelPackage(props.record))
const fileLabel = computed(() => packageExportFileLabel(props.record, props.zh))
const selection = computed(() => {
  const formats: Record<string, string> = { onnx: 'ONNX', 'onnx-optimized': 'ONNX optimized', 'openvino-ir': 'OpenVINO', 'tensorrt-engine': 'TensorRT' }
  const options = props.record.export_options
  const builds = props.record.builds?.map(build => `${formats[build.build_format] || build.build_format} ${build.runtime_precision.toUpperCase()}`) ?? []
  const entries = options?.include_checkpoint ? ['PyTorch', ...builds] : builds
  if (!builds.length && options?.build_ids.length) entries.push(props.zh ? `${options.build_ids.length} 个转换产物` : `${options.build_ids.length} converted artifacts`)
  return entries.join(' · ')
})
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}
</script>

<style scoped>
.package-export-result { display:grid; gap:14px; min-width:0; }
.package-export-result :is(h3,p,dd) { margin:0; overflow-wrap:anywhere; }
.package-export-result__file { display:flex; align-items:center; flex-wrap:wrap; gap:12px; padding:12px; border:1px solid var(--am-border); border-radius:6px; }
.package-export-result__file > div { min-width:0; flex:1 1 150px; }
.package-export-result__file div span,.package-export-result dt { color:var(--am-text-muted); }
.package-export-result dl { display:grid; gap:8px 12px; grid-template-columns:max-content minmax(0,1fr); margin:0; }
.package-export-result__note { padding:12px; background:var(--am-surface); border-radius:6px; color:var(--am-text-muted); }
.package-export-result__selection { padding-top:12px; border-top:1px solid var(--am-border); }
.package-export-result__error { color:var(--am-danger-text); }
.package-export-result__files table { width:100%; table-layout:fixed; }
.package-export-result__files th:last-child { width:28%; }
.package-export-result__files td { overflow-wrap:anywhere; white-space:normal; }
.package-export-result footer { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
</style>
