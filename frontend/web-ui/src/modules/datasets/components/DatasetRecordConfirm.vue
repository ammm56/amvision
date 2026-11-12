<template>
  <ConfirmDialog size="medium" :title="title" :confirm-label="clean ? tr('清理文件','Clean files') : tr('删除记录','Delete record')" :cancel-label="tr('取消','Cancel')" confirm-variant="danger" :busy="busy" @confirm="emit('confirm')" @cancel="emit('cancel')">
    <template #title-icon><Trash2 class="record-confirm-icon" :size="20" /></template>
    <div class="record-confirm-subject"><FolderOpen :size="28" /><div><strong>{{ name }}<template v-if="version && version !== '—'"> · {{ version }}</template></strong><small v-if="file">{{ file }}</small></div></div>
    <div class="record-confirm-effects">
      <section><h3>{{ clean ? tr('将清理','Will be cleaned') : tr('将删除','Will be deleted') }}</h3><ul><li>{{ clean ? tr('导出文件和 ZIP','Export files and ZIP') : importing ? tr('导入记录','Import record') : tr('导出记录','Export record') }}</li><li v-if="importing">{{ tr('上传 ZIP 和导入暂存文件','Uploaded ZIP and temporary import files') }}</li></ul></section>
      <section><h3>{{ tr('将保留','Will be kept') }}</h3><ul><li>{{ tr('数据集版本、图片及标注','Dataset versions, images and annotations') }}</li><li v-if="clean">{{ tr('导出记录和报告','Export record and report') }}</li></ul></section>
    </div>
    <template #leading-actions><small>{{ tr('此操作不可撤销。','This action cannot be undone.') }}</small></template>
  </ConfirmDialog>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { FolderOpen, Trash2 } from '@lucide/vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
const props = defineProps<{ importing: boolean; clean: boolean; name: string; version?: string; file?: string | null; busy: boolean }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const { locale } = useI18n()
const tr = (zh: string,en: string) => locale.value.startsWith('zh') ? zh : en
const title = computed(() => props.clean ? tr('清理导出文件','Clean export files') : props.importing ? tr('删除导入记录','Delete import record') : tr('删除导出记录','Delete export record'))
</script>
<style scoped>
.record-confirm-icon { color:var(--am-danger-icon); vertical-align:middle; margin-inline-end:10px; }
.record-confirm-subject { display:flex; align-items:center; gap:14px; padding:12px 6px 20px; overflow-wrap:anywhere; }
.record-confirm-subject small { display:block; color:var(--am-text-muted); margin-top:5px; }
.record-confirm-effects { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:24px; border-block:1px solid var(--am-border); padding:16px 6px; }
.record-confirm-effects section + section { border-inline-start:1px solid var(--am-border); padding-inline-start:20px; }
.record-confirm-effects h3 { font-size:14px; margin:0; }
.record-confirm-effects ul { padding-inline-start:18px; line-height:1.7; margin:8px 0 0; }
</style>
