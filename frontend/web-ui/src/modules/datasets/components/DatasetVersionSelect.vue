<template>
  <div class="dataset-version-select">
    <SelectField
      :model-value="workspace.dataset_version_id"
      :aria-label="text('version')"
      :options="options"
      :disabled="loading && !versions.length"
      @update:model-value="select"
    />
    <span v-if="error" role="status" class="dataset-muted" :title="error">{{
      error
    }}</span>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import SelectField from '@/shared/ui/components/Select.vue'
import { useDatasetText } from '../dataset-workspace'
import {
  listDatasetVersionPage,
  type DatasetWorkspace,
  type DatasetVersion,
} from '../services/dataset-workspace.service'

const props = defineProps<{ workspace: DatasetWorkspace }>()
const emit = defineEmits<{ change: [id: string]; more: [] }>()
const text = useDatasetText()
const versions = ref<DatasetVersion[]>([]),
  total = ref(0),
  loading = ref(false),
  error = ref('')
let generation = 0
const options = computed(() => {
  // 当前版本可能不在最近 100 个内，保留当前值并提供完整版本列表入口。
  const rows = versions.value.some(
    (v) => v.dataset_version_id === props.workspace.dataset_version_id,
  )
    ? versions.value
    : [props.workspace, ...versions.value]
  return [
    ...rows.map((v) => ({
      value: v.dataset_version_id,
      label: `v${v.version_number}`,
    })),
    ...(total.value > versions.value.length || error.value
      ? [{ value: '__more__', label: text('versions') }]
      : []),
  ]
})
function select(value: string | number | boolean | null) {
  if (value === '__more__') emit('more')
  else if (
    typeof value === 'string' &&
    value !== props.workspace.dataset_version_id
  )
    emit('change', value)
}
watch(
  [() => props.workspace.project_id, () => props.workspace.dataset_id],
  async () => {
    const request = ++generation
    loading.value = true
    error.value = ''
    versions.value = []
    total.value = 0
    try {
      const result = await listDatasetVersionPage({
        project_id: props.workspace.project_id,
        dataset_id: props.workspace.dataset_id,
        limit: 100,
      })
      if (request !== generation) return
      versions.value = result.items
      total.value = result.total
    } catch {
      if (request === generation) error.value = text('versionListUnavailable')
    } finally {
      if (request === generation) loading.value = false
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => generation++)
</script>
<style scoped>
.dataset-version-select {
  width: 100px;
  flex-shrink: 0;
}
.dataset-version-select > span {
  display: block;
  font-size: 12px;
}
</style>
