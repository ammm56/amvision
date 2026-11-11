<template>
  <SideDrawer
    :open="open"
    :title="
      label('版本引用', 'Version references') + ' · v' + version.version_number
    "
    :close-label="text('close')"
    @close="open = false"
    @after-leave="emit('close')"
  >
    <InlineError v-if="error" :message="error" />
    <Button v-if="error" size="sm" @click="retry++">{{
      label('重试', 'Retry')
    }}</Button>
    <p v-else-if="loading" role="status">{{ text('loading') }}</p>
    <ul v-else-if="items.length" class="reference-list">
      <li v-for="task in items" :key="task.task_id">
        <RouterLink :to="'/tasks/' + encodeURIComponent(task.task_id)">{{
          task.display_name || task.task_id
        }}</RouterLink>
        <small
          >{{
            task.task_kind.endsWith('-training')
              ? label('训练', 'Training')
              : label('评估', 'Evaluation')
          }}
          · {{ datasetDate(task.created_at) }}</small
        >
      </li>
    </ul>
    <p v-else>
      {{ label('无训练或评估引用', 'No training or evaluation references') }}
    </p>
    <template #footer v-if="offset || more">
      <Button size="sm" :disabled="loading || !offset" @click="offset -= 20">{{
        label('上一页', 'Previous')
      }}</Button>
      <Button size="sm" :disabled="loading || !more" @click="offset += 20">{{
        label('下一页', 'Next')
      }}</Button>
    </template>
  </SideDrawer>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { datasetDate, datasetError, useDatasetText } from '../dataset-workspace'
import {
  listVersionTaskReferences,
  type DatasetVersion,
  type VersionTaskReference,
} from '../services/dataset-workspace.service'
const props = defineProps<{ datasetId: string; version: DatasetVersion }>()
const emit = defineEmits<{ close: [] }>()
const { locale } = useI18n(),
  text = useDatasetText()
const label = (zh: string, en: string) =>
  locale.value.startsWith('zh') ? zh : en
const open = ref(true),
  offset = ref(0),
  more = ref(false),
  retry = ref(0)
const items = ref<VersionTaskReference[]>([]),
  loading = ref(false),
  error = ref('')
watch(
  () => [props.version.dataset_version_id, offset.value, retry.value],
  async (_, __, cleanup) => {
    const abort = new AbortController()
    cleanup(() => abort.abort())
    loading.value = true
    error.value = ''
    more.value = false
    try {
      const result = await listVersionTaskReferences(
        props.datasetId,
        props.version.dataset_version_id,
        offset.value,
        abort.signal,
      )
      if (!abort.signal.aborted) {
        items.value = result.items
        more.value = result.has_more
      }
    } catch (e) {
      if (!abort.signal.aborted) error.value = datasetError(e)
    } finally {
      if (!abort.signal.aborted) loading.value = false
    }
  },
  { immediate: true },
)
</script>
<style scoped>
.reference-list {
  list-style: none;
  display: grid;
  gap: 16px;
  padding: 0;
  margin: 0;
}
.reference-list li {
  display: grid;
  gap: 4px;
}
.reference-list a {
  overflow-wrap: anywhere;
  color: var(--am-text);
  font-weight: 500;
}
.reference-list small {
  color: var(--am-text-muted);
}
</style>
