<template>
  <section class="package-history">
    <div class="package-history__filters">
      <label><Search :size="16" aria-hidden="true" /><input v-model.trim="query" :placeholder="zh ? '搜索模型或文件名' : 'Search model or file name'" :aria-label="zh ? '搜索模型或文件名' : 'Search model or file name'" /></label>
      <Select v-model="filter" :options="statusOptions" :aria-label="zh ? '导出状态' : 'Export status'" />
      <Button :loading="busy && !downloading" @click="$emit('refresh')"><RefreshCw :size="16" />{{ zh ? '刷新' : 'Refresh' }}</Button>
    </div>
    <p class="package-history__count">{{ zh ? `共 ${visible.length} 条记录` : `${visible.length} records` }}</p>
    <div class="resource-table package-history__records" :aria-busy="busy">
      <table><thead><tr><th scope="col">{{ zh ? '文件' : 'File' }}</th><th scope="col">{{ zh ? '状态' : 'Status' }}</th><th scope="col">{{ zh ? '生成时间' : 'Generated' }}</th><th scope="col">{{ zh ? '操作' : 'Actions' }}</th></tr></thead>
        <tbody>
          <tr v-for="row in visible" :key="row.operation_id">
            <td :title="fileName(row)">{{ fileName(row) }}</td>
            <td><ModelPackageExportStatus :record="row" :zh="zh" /></td>
            <td>{{ row.completed_at ? formatSystemDateTime(row.completed_at, 'minutes') : '—' }}<small v-if="!row.completed_at && row.created_at" class="package-history__time">{{ zh ? '提交' : 'Submitted' }} {{ formatSystemDateTime(row.created_at, 'minutes') }}</small></td>
            <td><div class="package-history__actions">
              <Button variant="ghost" size="sm" class="ui-button--row-view" @click="$emit('open', row)">{{ zh ? '查看' : 'View' }}</Button>
              <Button variant="ghost" size="sm" class="package-history__link" :disabled="!canDownloadModelPackage(row) || busy" :loading="downloading === row.operation_id" @click="$emit('download', row)">{{ zh ? '下载' : 'Download' }}</Button>
            </div></td>
          </tr>
          <tr v-if="!visible.length"><td colspan="4">{{ busy ? (zh ? '正在加载…' : 'Loading…') : (zh ? '暂无符合条件的导出记录' : 'No matching exports') }}</td></tr>
        </tbody>
      </table>
    </div>
    <p class="package-history__note">{{ zh ? '仅完整性校验通过且文件存在时可下载。关闭面板不会取消生成任务。' : 'Downloads require a verified ZIP that still exists. Closing this panel does not cancel generation.' }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { RefreshCw, Search } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import Select from '@/shared/ui/components/Select.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { canDownloadModelPackage, packageExportFileLabel, packageExportState, packagePending, type ModelPackageRecord } from '../services/model-package.service'
import ModelPackageExportStatus from './ModelPackageExportStatus.vue'

const props = defineProps<{ records: ModelPackageRecord[]; zh: boolean; busy: boolean; downloading: string }>()
defineEmits<{ refresh: []; open: [record: ModelPackageRecord]; download: [record: ModelPackageRecord] }>()
const query = ref('')
const filter = ref<string | number | null>('')
const statusOptions = computed(() => [
  { label: props.zh ? '全部状态' : 'All statuses', value: '' },
  { label: props.zh ? '生成中' : 'Generating', value: 'pending' },
  { label: props.zh ? '已完成' : 'Completed', value: 'completed' },
  { label: props.zh ? '失败' : 'Failed', value: 'failed' },
  { label: props.zh ? '文件失效' : 'Unavailable files', value: 'invalid-file' },
])
const visible = computed(() => props.records.filter(row => {
  const state = packageExportState(row)
  const matches = !filter.value || filter.value === state || (filter.value === 'pending' && packagePending(state))
    || (filter.value === 'invalid-file' && !!packageExportFileLabel(row, props.zh))
  return matches && [fileName(row), row.model?.model_name].some(term => term?.toLowerCase().includes(query.value.toLowerCase()))
}))
function fileName(row: ModelPackageRecord): string { return row.file_name || row.export_options?.file_name || '—' }
</script>

<style scoped>
.package-history__filters { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.package-history__filters label { min-width:0; flex:1 1 155px; display:flex; align-items:center; gap:7px; padding:0 9px; border:1px solid var(--am-border); border-radius:6px; }
.package-history__filters input { flex:1; min-width:0; height:34px; border:0; outline:none; background:transparent; color:var(--am-text); }
.package-history__filters label:focus-within { outline:1px solid var(--am-border-strong); }
.package-history__count,.package-history__note,.package-history__time { color:var(--am-text-muted); }
.package-history__time { display:block; }
.package-history__records table { width:100%; table-layout:fixed; }
.package-history__records th:first-child { width:33%; }
.package-history__records th:last-child { width:22%; }
.package-history__records :is(th,td) { white-space:normal; overflow-wrap:anywhere; }
.package-history__actions { display:flex; gap:3px; flex-wrap:wrap; }
.package-history__link:not(:disabled) { color:var(--am-brand-primary); }
.package-history__note { line-height:1.5; }
</style>
