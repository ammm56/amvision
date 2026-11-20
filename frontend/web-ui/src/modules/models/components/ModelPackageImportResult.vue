<template>
  <section class="package-import-result">
    <header>
      <div v-if="record.state === 'completed'" class="package-import-result__completed" role="status">
        <CircleCheck :size="28" aria-hidden="true" /><strong>{{ packageStatus(record.state, zh) }}</strong>
      </div>
      <StatusBadge v-else :status="record.state" :label="packageStatus(record.state, zh)" with-dot />
      <Button v-if="allowDelete" variant="ghost" class="package-import-result__delete" @click="$emit('delete')"><Trash2 :size="15" />{{ zh ? '删除记录' : 'Delete record' }}</Button>
    </header>
    <p v-if="record.state === 'completed'">{{ zh ? '模型及包内产物已登记到项目，导入本身不会创建部署。' : 'The model and its artifacts are registered. Importing does not create a deployment.' }}</p>
    <p v-if="record.error" role="alert">{{ record.error }}</p>
    <h3>{{ zh ? '基本信息' : 'Overview' }}</h3>
    <dl>
      <dt>{{ zh ? '文件名称' : 'File name' }}</dt><dd>{{ record.file_name || '—' }}</dd>
      <dt>{{ zh ? '文件大小' : 'Archive size' }}</dt><dd>{{ record.upload_bytes == null ? '—' : formatBytes(record.upload_bytes) }}</dd>
      <dt>{{ zh ? '目标项目' : 'Target project' }}</dt><dd>{{ projectName }}</dd>
      <dt>{{ zh ? '模型名称' : 'Model name' }}</dt><dd>{{ record.plan?.name || record.model?.model_name || '—' }}</dd>
      <dt>{{ zh ? '本地版本' : 'Local version' }}</dt><dd>{{ localVersionName || '—' }}</dd>
      <template v-if="record.source?.source_version_label && /^v[1-9]\d*$/.test(record.source.source_version_label)">
        <dt>{{ zh ? '来源包版本' : 'Source package version' }}</dt><dd>{{ record.source.source_version_label }}</dd>
      </template>
      <template v-if="record.state === 'completed'">
        <dt>{{ zh ? '登记时间' : 'Registered' }}</dt><dd>{{ formatSystemDateTime(record.registered_at || record.updated_at) }}</dd>
      </template>
    </dl>
    <template v-if="record.state === 'completed'">
      <h3>{{ zh ? '检查摘要' : 'Checks' }}</h3>
      <ul class="package-import-result__checks">
        <li v-for="label in checks" :key="label"><CircleCheck :size="16" />{{ label }}</li>
      </ul>
      <h3>{{ zh ? '已登记的模型产物' : 'Registered artifacts' }}</h3>
      <div v-if="artifactRows.length" class="resource-table package-import-result__table">
        <table><thead><tr><th scope="col">{{ zh ? '文件格式' : 'Format' }}</th><th scope="col">{{ zh ? '精度' : 'Precision' }}</th><th scope="col">{{ zh ? '登记状态' : 'Registration' }}</th></tr></thead>
          <tbody><tr v-for="(item,index) in artifactRows" :key="index"><td>{{ item.format }}</td><td>{{ item.precision }}</td><td>{{ zh ? '已登记' : 'Registered' }}</td></tr></tbody>
        </table>
      </div>
      <p v-else>{{ zh ? '此记录没有产物清单。' : 'This record has no artifact manifest.' }}</p>
      <p v-if="allowDelete" class="package-import-result__note">{{ zh ? '删除记录会清理上传暂存文件，已登记的模型和产物保留。' : 'Deleting the record clears the temporary upload. Registered models and artifacts are kept.' }}</p>
    </template>
    <details v-if="record.files?.length" class="package-import-result__files">
      <summary>{{ zh ? '包内文件' : 'Package files' }}</summary>
      <ul><li v-for="entry in record.files" :key="`${entry.owner}/${entry.path}`">{{ entry.path }}</li></ul>
    </details>
  </section>
</template>

<script setup lang="ts">
import { useCatalogVersionLabel } from '../composables/useCatalogVersionLabel'
import { computed } from 'vue'
import { CircleCheck, Trash2 } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { packageStatus, type ModelPackageRecord } from '../services/model-package.service'
const props = defineProps<{ record: ModelPackageRecord; projectId?: string; projectName: string; zh: boolean; allowDelete?: boolean }>()
const localVersionName = useCatalogVersionLabel(() => [props.projectId, props.record.model?.task_type, props.record.result?.model_version_id])
defineEmits<{ delete: [] }>()
const checks = computed(() => props.zh ? ['文件完整性与路径', '模型结构', '类别顺序与目标'] : ['File integrity and paths', 'Model structure', 'Class order and target'])
const artifactRows = computed(() => {
  const formats: Record<string, string> = { onnx: 'ONNX', 'onnx-optimized': 'ONNX optimized', 'openvino-ir': 'OpenVINO', 'tensorrt-engine': 'TensorRT' }
  const rows = props.record.builds?.map(build => ({ format: formats[build.build_format] || build.build_format, precision: build.runtime_precision.toUpperCase() })) ?? []
  if (props.record.files?.some(entry => entry.owner === 'version' && /\.(pt|pth)$/i.test(entry.path))) rows.unshift({ format: 'PyTorch', precision: '—' })
  return rows
})
function formatBytes(value: number): string { return value < 1024 ? `${value} B` : value < 2 ** 20 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 2 ** 20).toFixed(1)} MB` }
</script>

<style scoped>
.package-import-result { display:grid; gap:12px; min-width:0; }
.package-import-result header { display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; }
.package-import-result__completed { display:flex; align-items:center; gap:8px; color:var(--am-success-text); font-size:var(--am-type-section); }
.package-import-result :is(h3,p,dd,ul) { margin:0; overflow-wrap:anywhere; }
.package-import-result dl { display:grid; grid-template-columns:max-content minmax(0,1fr); gap:8px 16px; margin:0; }
.package-import-result dt { color:var(--am-text-muted); }
.package-import-result__checks { display:flex; gap:8px 16px; flex-wrap:wrap; list-style:none; padding:0; }
.package-import-result__checks li { display:flex; align-items:center; gap:6px; }
.package-import-result__checks svg { color:var(--am-success-text); }
.package-import-result__delete svg { color:var(--am-danger-text); }
.package-import-result__table table { table-layout:fixed; }
.package-import-result__table :is(th,td) { white-space:normal; overflow-wrap:anywhere; }
.package-import-result__note { padding:10px; background:var(--am-surface); border-radius:5px; color:var(--am-text-muted); }
.package-import-result__files summary { cursor:pointer; }
</style>
