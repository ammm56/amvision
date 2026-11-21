<template>
  <section class="package-export-result" :aria-busy="checking">
    <h3>{{ zh ? '基本信息' : 'Overview' }}</h3>
    <div class="package-export-result__file">
      <FileArchive :size="24" aria-hidden="true" />
      <div><span>{{ zh ? '导出文件' : 'Export file' }}</span>
        <h3>{{ record.file_name || record.export_options?.file_name || '—' }}</h3></div>
    </div>
    <dl class="package-export-result__facts">
      <div>
        <dt>{{ zh ? '来源版本' : 'Source version' }}</dt>
        <dd>{{ sourceVersionName || [record.model?.model_name, record.source?.source_version_label].filter(Boolean).join(' · ') || '—' }}</dd>
      </div>
      <div v-if="record.model?.model_type">
        <dt>{{ zh ? '模型类型' : 'Model type' }}</dt><dd>{{ record.model.model_type.toUpperCase() }}</dd>
      </div>
      <div v-if="formats">
        <dt>{{ zh ? '文件格式' : 'Formats' }}</dt><dd>{{ formats }}</dd>
      </div>
      <div><dt>{{ zh ? '提交时间' : 'Submitted' }}</dt><dd>{{ formatSystemDateTime(record.created_at) }}</dd></div>
      <div><dt>{{ zh ? '生成时间' : 'Generated' }}</dt><dd>{{ record.completed_at ? formatSystemDateTime(record.completed_at) : '—' }}</dd></div>
      <div><dt>{{ zh ? '文件大小' : 'File size' }}</dt><dd>{{ record.total_bytes == null ? '—' : formatBytes(record.total_bytes) }}</dd></div>
    </dl>
    <h3>{{ zh ? '状态信息' : 'Status' }}</h3>
    <dl class="package-export-result__facts" aria-live="polite">
      <div><dt>{{ zh ? '任务状态' : 'Job status' }}</dt><dd><ModelPackageExportStatus :record="record" :zh="zh" part="task" /></dd></div>
      <div><dt>{{ zh ? '文件状态' : 'File status' }}</dt><dd><ModelPackageExportStatus :record="record" :zh="zh" part="file" /></dd></div>
    </dl>
    <p v-if="fileLabel" class="package-export-result__note">{{ zh
      ? '导出 ZIP 当前不可下载。重新生成前会检查原模型版本和所选产物。'
      : 'The ZIP is no longer downloadable. Regenerating checks the original version and selected artifacts.' }}</p>
    <p v-if="record.error" role="alert" class="package-export-result__error">{{ record.error }}</p>
    <div v-if="record.files?.length" class="resource-table package-export-result__files">
      <table><thead><tr><th scope="col">{{ zh ? '包内文件' : 'Package contents' }}</th><th scope="col">SHA-256</th></tr></thead>
        <tbody><tr v-for="file in record.files" :key="`${file.owner}/${file.path}`">
          <td :title="file.path">{{ file.path }}</td>
          <td>
            <div v-if="file.sha256" class="package-export-result__checksum-actions">
              <ModelFileChecksumTooltip :open="openChecksum === file" :zh="zh"
                @update:open="setOpenChecksum(file, $event)">
                <code>{{ file.sha256 }}</code>
              </ModelFileChecksumTooltip>
              <Button variant="ghost" size="sm" icon-only :aria-label="zh ? '复制 SHA-256' : 'Copy SHA-256'" @click="copyChecksum(file.sha256)">
                <Copy :size="14" aria-hidden="true" />
              </Button>
            </div>
            <span v-else>—</span>
          </td>
        </tr></tbody>
      </table>
    </div>
    <p v-if="copyMessage" role="status" class="package-export-result__copy-status">{{ copyMessage }}</p>
    <footer>
      <Button @click="$emit('close')">{{ closeLabel }}</Button>
      <Button :variant="canRegenerate ? 'secondary' : 'primary'" :loading="busy && canDownload" :disabled="checking || actionsBlocked || !canDownload" @click="$emit('download')">{{ zh ? '下载 ZIP' : 'Download ZIP' }}</Button>
      <Button v-if="canRegenerate" variant="primary" :loading="busy" :disabled="checking || actionsBlocked" @click="$emit('regenerate')">{{ zh ? '重新生成' : 'Regenerate' }}</Button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { useCatalogVersionLabel } from '../composables/useCatalogVersionLabel'
import { computed, ref, watch } from 'vue'
import { Copy, FileArchive } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { canDownloadModelPackage, canRegenerateModelPackage, packageExportFileLabel, type ModelPackageRecord } from '../services/model-package.service'
import ModelFileChecksumTooltip from './ModelFileChecksumTooltip.vue'
import ModelPackageExportStatus from './ModelPackageExportStatus.vue'

const props = defineProps<{ record: ModelPackageRecord; projectId?: string; zh: boolean; closeLabel: string; busy: boolean; checking?: boolean; actionsBlocked?: boolean }>()
const sourceVersionName = useCatalogVersionLabel(() => [props.projectId, props.record.model?.task_type, props.record.source_version_id || props.record.export_options?.model_version_id])
defineEmits<{ close: []; download: []; regenerate: [] }>()
const canDownload = computed(() => canDownloadModelPackage(props.record))
const canRegenerate = computed(() => canRegenerateModelPackage(props.record))
const fileLabel = computed(() => packageExportFileLabel(props.record, props.zh))
const formats = computed(() => {
  const names: Record<string, string> = { onnx: 'ONNX', 'onnx-optimized': 'ONNX optimized', 'openvino-ir': 'OpenVINO', 'tensorrt-engine': 'TensorRT' }
  const options = props.record.export_options
  const builds = props.record.builds?.map(build => `${names[build.build_format] || build.build_format} ${build.runtime_precision.toUpperCase()}`) ?? []
  return (options?.include_checkpoint ? ['PyTorch', ...builds] : builds).join(' · ')
})
type PackageFile = NonNullable<ModelPackageRecord['files']>[number]
const openChecksum = ref<PackageFile | null>(null)
const copyMessage = ref('')
watch(() => props.record.operation_id, () => {
  openChecksum.value = null
  copyMessage.value = ''
})

function setOpenChecksum(file: PackageFile, open: boolean): void {
  if (open) openChecksum.value = file
  else if (openChecksum.value === file) openChecksum.value = null
}

async function copyChecksum(sha256: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(sha256)
    copyMessage.value = props.zh ? '已复制 SHA-256' : 'SHA-256 copied'
  } catch {
    copyMessage.value = props.zh ? '无法复制 SHA-256' : 'Could not copy SHA-256'
  }
}
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
.package-export-result__facts { margin:0; border:1px solid var(--am-border); border-radius:6px; }
.package-export-result__facts > div { display:grid; grid-template-columns:minmax(76px,24%) minmax(0,1fr); align-items:center; gap:12px; padding:8px 12px; }
.package-export-result__facts > div + div { border-block-start:1px solid var(--am-border); }
.package-export-result__note { padding:12px; background:var(--am-surface); border-radius:6px; color:var(--am-text-muted); }
.package-export-result__copy-status { color:var(--am-text-muted); font-size:12px; }
.package-export-result__error { color:var(--am-danger-text); }
.package-export-result__files table { width:100%; table-layout:fixed; }
.package-export-result__files th:last-child { width:106px; }
.package-export-result__files td { overflow-wrap:anywhere; white-space:normal; }
.package-export-result__checksum-actions { display:flex; align-items:center; gap:4px; }
.package-export-result footer { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
</style>
