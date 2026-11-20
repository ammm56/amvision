<template>
  <div class="package-failure">
    <div class="package-failure__alert" role="alert">
      <CircleX :size="24" aria-hidden="true" />
      <div>
        <h3>{{ heading }}</h3>
        <p>{{ reason }}</p>
        <div class="package-failure__meta"><span>{{ record.file_name }}</span><time :datetime="record.updated_at">{{ formatSystemDateTime(record.updated_at, 'minutes') }}</time><span>{{ size }}</span></div>
      </div>
    </div>
    <div class="package-failure__cards">
      <section class="resource-section">
        <h3>{{ zh ? '来源信息' : 'Source information' }}</h3>
        <dl><dt>{{ zh ? '文件名' : 'File name' }}</dt><dd>{{ record.file_name || '—' }}</dd>
          <dt>{{ zh ? '文件大小' : 'File size' }}</dt><dd>{{ size }}</dd>
          <dt>{{ zh ? '任务类型' : 'Task type' }}</dt><dd>{{ task }}</dd>
          <dt>{{ zh ? '类别数量' : 'Classes' }}</dt><dd>{{ record.categories?.length ?? '—' }}</dd></dl>
      </section>
      <section class="resource-section">
        <h3>{{ zh ? '目标信息' : 'Destination' }}</h3>
        <dl><dt>{{ zh ? '项目' : 'Project' }}</dt><dd>{{ projectName }}</dd>
          <dt>{{ zh ? '目标模型' : 'Target model' }}</dt><dd>{{ record.plan?.name || '—' }}</dd>
          <dt>{{ zh ? '模型版本' : 'Model version' }}</dt><dd>{{ zh ? '未创建' : 'Not created' }}</dd>
          <template v-if="record.plan?.target_model_id"><dt>{{ zh ? '已有版本' : 'Existing versions' }}</dt><dd>{{ zh ? '保留' : 'Preserved' }}</dd></template></dl>
      </section>
      <section class="resource-section">
        <h3>{{ zh ? '导入阶段' : 'Import stages' }}</h3>
        <ol>
          <li v-for="(label, index) in stages" :key="label" :class="{ 'is-success': index === 0 || index < failureIndex, 'is-failed': index === failureIndex }">
            <component :is="index === 0 || index < failureIndex ? CircleCheck : index === failureIndex ? CircleX : Circle" :size="16" aria-hidden="true" />
            <span>{{ label }}</span><small>{{ stageStatus(index) }}</small>
          </li>
        </ol>
      </section>
    </div>
    <details class="resource-section" @toggle="copyMessage = ''">
      <summary>{{ zh ? '错误详情' : 'Error details' }}</summary>
      <div class="package-failure__details">
        <p>{{ reason }} · {{ record.operation_id }}</p>
        <Button size="sm" @click="copyDetails"><Copy :size="14" />{{ zh ? '复制错误信息' : 'Copy error details' }}</Button>
        <span v-if="copyMessage" aria-live="polite">{{ copyMessage }}</span>
      </div>
    </details>
    <p class="package-failure__note"><Info :size="16" aria-hidden="true" />{{ note }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Circle, CircleCheck, CircleX, Copy, Info } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import type { ModelPackageRecord } from '../services/model-package.service'

const props = defineProps<{ zh: boolean; projectName: string; record: ModelPackageRecord }>()
const fileSize = computed(() => props.record.total_bytes ?? props.record.upload_bytes)
const size = computed(() => fileSize.value == null ? '—' : `${(fileSize.value / 2 ** 20).toFixed(1)} MB`)
const task = computed(() => {
  const type = props.record.model?.task_type || ''
  const labels: Record<string, string> = { detection: '目标检测', classification: '图像分类', segmentation: '分割', pose: '姿态估计', obb: '旋转框检测', anomaly: '异常检测' }
  return (props.zh && labels[type]) || type || '—'
})
const stages = computed(() => props.zh ? ['文件上传', '模型包检查', '写入模型文件', '登记模型版本'] : ['Upload file', 'Check package', 'Write model files', 'Register version'])
const failureIndex = computed(() => ({ package_check: 1, file_write: 2, registration: 3, unknown: -1 })[props.record.failure_stage ?? 'unknown'])
const heading = computed(() => failureIndex.value === 3 ? (props.zh ? '模型登记失败' : 'Model registration failed') : (props.zh ? '模型导入失败' : 'Model import failed'))
const reason = computed(() => {
  if (props.record.failure_code === 'storage_full') return props.zh ? '存储空间不足，请释放空间后重试。' : 'Storage is full. Free up space and retry.'
  if (failureIndex.value === 1) return props.zh ? '提交时未能再次校验模型包或目标。' : 'The package or destination could not be verified at submission.'
  if (failureIndex.value === 2) return props.zh ? '无法写入模型文件。' : 'The model files could not be written.'
  if (failureIndex.value === 3) return props.zh ? '未能登记新的模型版本。' : 'The new model version could not be registered.'
  return props.zh ? '未能完成导入，记录中没有失败阶段。' : 'The import did not finish and the failing stage was not recorded.'
})
const note = computed(() => props.zh
  ? `未创建新版本，已有模型和版本未修改。${props.record.can_recheck ? '' : '暂存文件已不可用，需重新上传。'}`
  : `No new version was created. Existing models and versions were unchanged.${props.record.can_recheck ? '' : ' Upload the package again to continue.'}`)
const copyMessage = ref('')
function stageStatus(index: number): string {
  if (index === 0 || index < failureIndex.value) return props.zh ? '完成' : 'Complete'
  if (index === failureIndex.value) return props.zh ? '失败' : 'Failed'
  if (failureIndex.value < 0) return props.zh ? '未记录' : 'Not recorded'
  return props.zh ? '未执行' : 'Not run'
}
async function copyDetails(): Promise<void> {
  try {
    await navigator.clipboard.writeText([heading.value, reason.value, props.record.file_name, props.record.updated_at, props.record.operation_id].filter(Boolean).join('\n'))
    copyMessage.value = props.zh ? '已复制' : 'Copied'
  } catch {
    copyMessage.value = props.zh ? '无法复制，请选中上方文字。' : 'Could not copy. Select the text above.'
  }
}
</script>

<style scoped>
.package-failure { display:grid; gap:14px; min-width:0; }
.package-failure :is(h3,p,dl,ol) { margin:0; }
.package-failure h3 { margin-bottom:10px; }
.package-failure__alert { display:flex; align-items:flex-start; gap:14px; border:1px solid var(--am-danger-border); padding:18px; border-radius:8px; color:var(--am-danger-text); background:var(--am-danger-surface); }
.package-failure__alert > svg, .package-failure__note svg { flex:none; }
.package-failure__alert h3 { margin-bottom:4px; }
.package-failure__meta { display:flex; flex-wrap:wrap; gap:6px 16px; margin-top:10px; font-size:0.9em; overflow-wrap:anywhere; }
.package-failure__cards { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.package-failure .resource-section { min-width:0; padding:16px; }
.package-failure dl { display:grid; grid-template-columns:max-content minmax(0,1fr); gap:8px 12px; }
.package-failure :is(dt,small) { color:var(--am-text-muted); }
.package-failure dd { margin:0; overflow-wrap:anywhere; }
.package-failure ol { display:grid; gap:8px; list-style:none; padding:0; }
.package-failure li { display:grid; grid-template-columns:16px minmax(0,1fr) max-content; align-items:center; gap:8px; color:var(--am-text-muted); }
.package-failure li.is-success svg { color:var(--am-success-icon); }
.package-failure li.is-failed :is(svg,small) { color:var(--am-danger-text); }
.package-failure summary { cursor:pointer; font-weight:600; }
.package-failure__details { display:flex; align-items:center; flex-wrap:wrap; gap:10px; margin-top:12px; overflow-wrap:anywhere; }
.package-failure__note { display:flex; align-items:center; gap:8px; color:var(--am-text-muted); }
@media (max-width:760px) { .package-failure__cards { grid-template-columns:1fr; } }
</style>
