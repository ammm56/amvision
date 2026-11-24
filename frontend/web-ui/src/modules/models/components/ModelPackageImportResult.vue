<template>
  <section class="package-import-result">
    <header class="package-import-result__header" :class="{ 'is-complete': completed }">
      <span v-if="completed" class="package-import-result__mark"><Check :size="24" aria-hidden="true" /></span>
      <div class="package-import-result__identity">
        <h3 v-if="completed">{{ zh ? '模型导入完成' : 'Model imported' }}</h3>
        <StatusBadge v-else :status="record.state" :label="packageStatus(record.state, zh)" with-dot />
        <div class="package-import-result__archive">
          <span v-if="record.file_name"><FileArchive :size="15" aria-hidden="true" />{{ record.file_name }}</span>
          <span v-if="record.upload_bytes != null">{{ formatPackageBytes(record.upload_bytes) }}</span>
        </div>
      </div>
      <Button v-if="allowDelete" variant="ghost" class="package-import-result__delete" @click="$emit('delete')"><Trash2 :size="15" />{{ zh ? '删除记录' : 'Delete record' }}</Button>
    </header>
    <InlineError :message="record.error || ''" />
    <div class="package-import-result__grid">
      <section class="package-import-result__section">
        <h3>{{ zh ? '模型信息' : 'Model information' }}</h3>
        <dl>
          <dt>{{ zh ? '模型名称' : 'Model name' }}</dt><dd>{{ record.plan?.name || record.model?.model_name || '—' }}</dd>
          <dt>{{ zh ? '目标项目' : 'Target project' }}</dt><dd>{{ projectName }}</dd>
          <template v-if="record.model?.task_type">
            <dt>{{ zh ? '任务类型' : 'Task type' }}</dt><dd>{{ modelTaskLabel(record.model.task_type, zh) }}</dd>
          </template>
          <template v-if="record.import_description">
            <dt>{{ zh ? '说明' : 'Description' }}</dt><dd class="package-import-result__description">{{ record.import_description }}</dd>
          </template>
        </dl>
      </section>
      <section class="package-import-result__section">
        <h3>{{ zh ? '版本信息' : 'Version information' }}</h3>
        <dl>
          <dt>{{ zh ? '本地版本' : 'Local version' }}</dt><dd>{{ localVersionName || '—' }}</dd>
          <template v-if="sourceVersion">
            <dt>{{ zh ? '来源包版本' : 'Source package version' }}</dt><dd>{{ sourceVersion }}</dd>
          </template>
          <template v-if="completed">
            <dt>{{ zh ? '登记时间' : 'Registered' }}</dt><dd><time :datetime="record.registered_at || record.updated_at">{{ formatSystemDateTime(record.registered_at || record.updated_at) }}</time></dd>
          </template>
        </dl>
      </section>
    </div>
    <div v-if="completed" class="package-import-result__grid">
      <section class="package-import-result__section">
        <h3>{{ zh ? '检查摘要' : 'Checks' }}</h3>
        <ul class="package-import-result__checks">
          <li v-for="label in checks" :key="label"><CircleCheck :size="16" aria-hidden="true" />{{ label }}</li>
        </ul>
      </section>
      <section class="package-import-result__section">
        <h3>{{ zh ? '已登记的模型产物' : 'Registered artifacts' }}</h3>
        <div v-if="artifactRows.length" class="resource-table package-import-result__table">
          <table><thead><tr><th scope="col">{{ zh ? '文件格式' : 'Format' }}</th><th scope="col">{{ zh ? '精度' : 'Precision' }}</th><th scope="col">{{ zh ? '登记状态' : 'Registration' }}</th></tr></thead>
            <tbody><tr v-for="(item,index) in artifactRows" :key="index"><th scope="row">{{ item.format }}</th><td>{{ item.precision }}</td><td><span class="package-import-result__registered"><CircleCheck :size="15" aria-hidden="true" />{{ zh ? '已登记' : 'Registered' }}</span></td></tr></tbody>
          </table>
        </div>
        <p v-else>{{ zh ? '此记录没有产物清单。' : 'This record has no artifact manifest.' }}</p>
      </section>
    </div>
    <details v-if="record.files?.length" class="package-import-result__files">
      <summary>
        <Files :size="17" aria-hidden="true" />
        <strong>{{ zh ? '包内文件' : 'Package files' }}</strong>
        <span>{{ zh ? `${record.files.length} 个文件` : `${record.files.length} files` }}</span>
        <ChevronDown :size="16" class="package-import-result__chevron" aria-hidden="true" />
      </summary>
      <ModelPackageFileTable :files="record.files" :zh="zh" full-path />
    </details>
  </section>
</template>

<script setup lang="ts">
import { useCatalogVersionLabel } from '../composables/useCatalogVersionLabel'
import { computed } from 'vue'
import { Check, ChevronDown, CircleCheck, FileArchive, Files, Trash2 } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import ModelPackageFileTable from './ModelPackageFileTable.vue'
import { formatPackageBytes, packageSourceVersionLabel } from '../model-package-presentation'
import { modelTaskLabel } from '../model-evaluation-types'
import { packageStatus, type ModelPackageRecord } from '../services/model-package.service'
const props = defineProps<{ record: ModelPackageRecord; projectId?: string; projectName: string; zh: boolean; allowDelete?: boolean }>()
const localVersionName = useCatalogVersionLabel(() => [props.projectId, props.record.model?.task_type, props.record.result?.model_version_id])
const completed = computed(() => props.record.state === 'completed')
const sourceVersion = computed(() => packageSourceVersionLabel(props.record))
defineEmits<{ delete: [] }>()
const checks = computed(() => props.zh ? ['文件完整性与路径', '模型结构', '类别顺序与目标'] : ['File integrity and paths', 'Model structure', 'Class order and target'])
const artifactRows = computed(() => {
  const formats: Record<string, string> = { onnx: 'ONNX', 'onnx-optimized': 'ONNX optimized', 'openvino-ir': 'OpenVINO', 'tensorrt-engine': 'TensorRT' }
  const rows = props.record.builds?.map(build => ({ format: formats[build.build_format] || build.build_format, precision: build.runtime_precision.toUpperCase() })) ?? []
  if (props.record.files?.some(entry => entry.owner === 'version' && /\.(pt|pth)$/i.test(entry.path))) rows.unshift({ format: 'PyTorch', precision: '—' })
  return rows
})
</script>

<style scoped>
.package-import-result { display:grid; gap:14px; min-width:0; }
.package-import-result__header { display:flex; align-items:center; gap:12px; flex-wrap:wrap; padding:14px 16px; border:1px solid var(--am-border); border-radius:6px; }
.package-import-result__header.is-complete { background:var(--am-success-surface); border-color:var(--am-success-border); }
.package-import-result__mark { flex:none; display:grid; place-items:center; width:42px; height:42px; border-radius:50%; background:var(--am-surface); color:var(--am-success-text); }
.package-import-result__identity { flex:1 1 160px; min-width:0; }
.package-import-result__identity h3 { font-size:var(--am-type-section); }
.package-import-result__archive { display:flex; align-items:center; flex-wrap:wrap; gap:3px 12px; margin-block-start:4px; color:var(--am-text-muted); font-size:var(--am-type-caption); }
.package-import-result__archive span { display:flex; align-items:baseline; gap:6px; min-width:0; overflow-wrap:anywhere; }
.package-import-result__archive svg { flex:none; align-self:center; }
.package-import-result__grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,295px),1fr)); gap:12px; min-width:0; }
.package-import-result__section { display:grid; align-content:start; gap:10px; min-width:0; padding:13px 14px; border:1px solid var(--am-border); border-radius:6px; }
.package-import-result :is(h3,p,dd,ul) { margin:0; overflow-wrap:anywhere; }
.package-import-result dl { display:grid; grid-template-columns:minmax(76px,32%) minmax(0,1fr); gap:7px 12px; margin:0; }
.package-import-result dt { color:var(--am-text-muted); }
.package-import-result__description { white-space:pre-wrap; }
.package-import-result__checks { display:grid; gap:8px; list-style:none; padding:0; }
.package-import-result__checks li,.package-import-result__registered { display:flex; align-items:center; gap:6px; }
.package-import-result :is(.package-import-result__checks,.package-import-result__registered) svg { flex:none; color:var(--am-success-text); }
.package-import-result__delete svg { color:var(--am-danger-text); }
.package-import-result__table table { table-layout:fixed; }
.package-import-result__table :is(th,td) { white-space:normal; overflow-wrap:anywhere; padding:7px 9px; }
.package-import-result__files { border:1px solid var(--am-border); border-radius:6px; }
.package-import-result__files summary { display:flex; align-items:center; gap:8px; min-height:42px; padding:8px 12px; list-style:none; cursor:pointer; }
.package-import-result__files summary::-webkit-details-marker { display:none; }
.package-import-result__files summary:hover { background:var(--am-hover-surface); }
.package-import-result__files summary:focus-visible { outline-offset:-3px; }
.package-import-result__files summary span { margin-inline-start:auto; color:var(--am-text-muted); font-size:var(--am-type-caption); }
.package-import-result__chevron { flex:none; color:var(--am-text-muted); }
.package-import-result__files[open] .package-import-result__chevron { transform:rotate(180deg); }
.package-import-result__files :deep(.package-file-table) { margin:0 12px 12px; }
</style>
