<template>
  <section v-if="versions.length" class="resource-section">
    <div class="section-heading"><h2>{{ t('versions') }}</h2></div>
    <section v-for="group in groups" :key="group.id" class="version-group">
      <div class="section-heading"><strong>{{ group.id }}</strong><ResourceDeleteButton kind="dataset" :project-id="projectId" :resource-id="group.id" :label="t('dataset')" @accepted="$emit('changed')" /></div>
      <div class="resource-table"><table>
        <thead><tr><th>{{ t('versions') }}</th><th>{{ t('action') }}</th></tr></thead>
        <tbody><tr v-for="version in group.versions" :key="version.dataset_version_id">
          <td>{{ version.dataset_version_id }} · {{ version.task_type }} · {{ version.sample_count }}</td>
          <td><ResourceDeleteButton kind="dataset-version" :project-id="projectId" :resource-id="version.dataset_version_id" @accepted="$emit('changed')" /></td>
        </tr></tbody>
      </table></div>
    </section>
  </section>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DatasetVersionRelation } from '../services/dataset.service'
import ResourceDeleteButton from '@/shared/ui/components/ResourceDeleteButton.vue'
import { resourceDeletionMessages } from '@/shared/ui/components/resource-deletion-messages'
const props = defineProps<{ versions: DatasetVersionRelation[]; projectId: string }>()
defineEmits<{ changed: [] }>()
const { t } = useI18n({ messages: resourceDeletionMessages })
const groups = computed(() => {
  const items = new Map<string, DatasetVersionRelation[]>()
  for (const version of props.versions) {
    if (version.project_id !== props.projectId) continue
    const versions = items.get(version.dataset_id) ?? []
    versions.push(version)
    items.set(version.dataset_id, versions)
  }
  return [...items].map(([id, versions]) => ({ id, versions }))
})
</script>
<style scoped>
.version-group + .version-group { margin-top: 16px; }
</style>
