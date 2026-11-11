<template>
  <details open class="source-panel">
    <summary>{{ label('来源摘要', 'Source summary') }}</summary>
    <div class="source-grid">
      <div class="source-file">
        <FileArchive :size="27" />
        <div>
          <strong>{{ filename || sourceKind }}</strong>
          <small v-if="format !== '—'">{{ format }}</small>
          <dl>
            <dt>{{ label('来源方式', 'Source') }}</dt>
            <dd>{{ sourceKind }}</dd>
            <dt>{{ label('创建时间', 'Created') }}</dt>
            <dd>{{ datasetDate(workspace.created_at) }}</dd>
            <template v-if="workspace.metadata.parent_version_id"
              ><dt>{{ label('来源版本', 'Parent version') }}</dt>
              <dd>
                <button
                  v-if="workspace.parent_version_number"
                  @click="
                    emit(
                      'version',
                      String(workspace.metadata.parent_version_id),
                    )
                  "
                >
                  v{{ workspace.parent_version_number }}</button
                ><span v-else>{{ label('已不可用', 'Unavailable') }}</span>
              </dd></template
            >
            <template v-if="workspace.metadata.description"
              ><dt>{{ label('版本说明', 'Notes') }}</dt>
              <dd>{{ workspace.metadata.description }}</dd></template
            >
          </dl>
        </div>
      </div>
      <div v-if="workspace.metadata.source_import_id" class="source-record">
        <strong>{{ label('导入记录', 'Import record') }}</strong>
        <RouterLink
          v-if="source"
          :to="
            '/datasets/imports/' + encodeURIComponent(source.dataset_import_id)
          "
          ><List :size="15" />{{
            label('查看导入详情', 'View import details')
          }}
          ›</RouterLink
        >
        <span v-else-if="error"
          >{{ error }}
          <button @click="retry++">{{ label('重试', 'Retry') }}</button></span
        >
        <span v-else>{{
          pending
            ? text('loading')
            : label('导入记录不可用', 'Import record unavailable')
        }}</span>
      </div>
    </div>
    <p>
      <Info :size="15" />{{
        label(
          '训练和评估引用固定版本，不随新版本切换。',
          'Training and evaluation stay linked to their original version.',
        )
      }}
    </p>
  </details>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { FileArchive, Info, List } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { ApiError } from '@/shared/api/error'
import {
  datasetDate,
  datasetError,
  datasetFormatLabel,
  useDatasetText,
} from '../dataset-workspace'
import {
  getDatasetImportDetail,
  type DatasetImportDetail,
} from '../services/dataset.service'
import {
  getDatasetReport,
  type DatasetWorkspace,
} from '../services/dataset-workspace.service'
const props = defineProps<{ workspace: DatasetWorkspace }>(),
  emit = defineEmits<{ version: [id: string] }>()
const { locale } = useI18n(),
  text = useDatasetText(),
  label = (zh: string, en: string) => (locale.value.startsWith('zh') ? zh : en)
const source = ref<DatasetImportDetail | null>(null),
  pending = ref(false),
  error = ref(''),
  retry = ref(0)
const format = computed(() =>
  datasetFormatLabel(
    String(
      props.workspace.metadata.format_id ||
        props.workspace.metadata.format_type ||
        '',
    ),
  ),
)
const sourceKind = computed(() =>
  props.workspace.metadata.parent_version_id
    ? label('从版本创建', 'Created from version')
    : props.workspace.metadata.source_import_id
      ? label('ZIP 导入', 'ZIP import')
      : '—',
)
const filename = computed(() =>
  String(
    source.value?.source_file_name ||
      source.value?.metadata?.source_file_name ||
      source.value?.metadata?.original_file_name ||
      source.value?.package_path?.split(/[\\/]/).pop() ||
      '',
  ),
)
watch(
  () => [props.workspace, retry.value],
  async (_, __, cleanup) => {
    const ctrl = new AbortController()
    cleanup(() => ctrl.abort())
    const w = props.workspace
    source.value = null
    error.value = ''
    pending.value = false
    if (!w.metadata.source_import_id) return
    pending.value = true
    try {
      const report = await getDatasetReport(
        w.dataset_id,
        w.dataset_version_id,
        ctrl.signal,
      )
      if (!report.dataset_import_id || ctrl.signal.aborted) return
      const item = await getDatasetImportDetail(
        report.dataset_import_id,
        ctrl.signal,
      )
      if (
        !ctrl.signal.aborted &&
        item.dataset_id === w.dataset_id &&
        item.project_id === w.project_id
      )
        source.value = item
    } catch (e) {
      if (!ctrl.signal.aborted && !(e instanceof ApiError && e.status === 404))
        error.value = datasetError(e)
    } finally {
      if (!ctrl.signal.aborted) pending.value = false
    }
  },
  { immediate: true },
)
</script>
<style scoped>
.source-panel {
  padding: 18px 20px;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  min-width: 0;
}
.source-panel summary {
  font-weight: 600;
  cursor: pointer;
}
.source-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr);
  gap: 20px;
  margin: 18px 0;
}
.source-file {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  overflow-wrap: anywhere;
}
.source-file svg {
  flex: none;
}
.source-file small {
  padding: 2px 5px;
  background: var(--am-hover-surface);
  border-radius: 4px;
  color: var(--am-text-muted);
}
.source-file dl {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px 18px;
  font-size: 13px;
  margin: 14px 0 0;
}
.source-file dt,
.source-record span,
.source-panel p {
  color: var(--am-text-muted);
}
.source-file dd {
  margin: 0;
}
.source-record {
  display: grid;
  align-content: start;
  justify-items: start;
  gap: 12px;
  border-left: 1px solid var(--am-border);
  padding-left: 20px;
}
.source-record a,
.source-panel button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font: inherit;
  color: var(--am-brand-primary);
  border: 0;
  background: none;
  cursor: pointer;
}
.source-panel p {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  margin: 16px 0 0;
}
</style>
