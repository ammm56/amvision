<template>
  <SideDrawer :open="drawerOpen" size="compact" :title="text(item.kind === 'dataset-version' ? 'datasetVersion' : 'modelVersion')" :close-label="text('close')" @close="drawerOpen = false" @after-leave="emit('close')">
    <InlineError v-if="error" :message="error" />
    <p v-if="loading" role="status">{{ text('loading') }}</p>
    <dl v-else-if="!error" class="project-info">
      <dt>{{ text('resourceName') }}</dt><dd>{{ item.name }}</dd>
      <dt>ID</dt><dd><code>{{ item.resource_id }}</code></dd>
      <template v-for="row in rows" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></template>
    </dl>
    <template #footer><Button v-if="error" @click="load">{{ text('refresh') }}</Button><span v-else /><Button @click="drawerOpen = false">{{ text('close') }}</Button></template>
  </SideDrawer>
</template>
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getDatasetVersionRelation } from '@/modules/datasets/services/dataset.service'
import { getDeploymentSourceModelDetail } from '@/modules/models/services/model.service'
import type { ProjectOverviewItem } from '../services/project.service'
import { projectError, useProjectText } from '../project-workspace'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
const props = defineProps<{ projectId: string; item: ProjectOverviewItem }>()
const emit = defineEmits<{ close: [] }>()
const text = useProjectText()
const drawerOpen = ref(true)
const loading = ref(false), error = ref(''), rows = ref<Array<{ label: string; value: string | number }>>([])
let active = true
async function load() {
  if (loading.value) return
  loading.value = true; error.value = ''
  try {
    if (props.item.kind === 'dataset-version') {
      const value = await getDatasetVersionRelation(props.item.target_id!, props.item.resource_id)
      if (!active) return
      if (value.project_id !== props.projectId) throw new Error(text('noAccess'))
      rows.value = [{ label: 'Dataset ID', value: value.dataset_id }, { label: text('taskType'), value: value.task_type }, { label: text('sampleCount'), value: value.sample_count }, { label: text('categoryCount'), value: value.category_count }, { label: text('split'), value: value.split_names.join(' / ') || '—' }]
    } else {
      const value = await getDeploymentSourceModelDetail(props.projectId, props.item.target_id!)
      if (!active) return
      const version = value.versions.find(item => item.model_version_id === props.item.resource_id)
      if (!version) throw new Error(text('resourceGone'))
      rows.value = [{ label: 'Model ID', value: value.model_id }, { label: text('taskType'), value: value.task_type }, { label: text('modelType'), value: value.model_type }, { label: text('source'), value: version.source_kind }, { label: text('resourceFiles'), value: version.files.map(file => file.logical_name).join('\n') || '—' }]
    }
  } catch (cause) { if (active) error.value = projectError(cause) }
  finally { if (active) loading.value = false }
}
onMounted(load)
onBeforeUnmount(() => { active = false })
</script>
