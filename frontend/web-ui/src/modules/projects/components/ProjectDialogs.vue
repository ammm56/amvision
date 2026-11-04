<template>
  <ProjectMetadataDrawer v-if="action === 'create' || action === 'info' || action === 'edit'" :principal-id="session.currentUser?.principal_id" :mode="editingInfo ? 'edit' : action" :project="project" :editable="Boolean(project?.revision) && (session.hasScopes(['datasets:write']) || session.hasScopes(['workflows:write']))" @edit="editingInfo = true" @close="emit('close')" @saved="saved" />
  <ProjectSdkDialog v-else-if="action === 'sdk' && project" :project="project" @close="emit('close')" />
  <ProjectDeleteDialog v-else-if="action === 'delete' && project" :project="project" :operation-id="operationId" @close="emit('close')" @removed="removed" @started="remember('latest')" @unaccepted="clearPending" />
</template>
<script setup lang="ts">
import { ref } from 'vue'
import type { ProjectCatalogItem } from '@/shared/contracts'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import type { ProjectDeletionResult } from '../services/project.service'
import ProjectMetadataDrawer from './ProjectMetadataDrawer.vue'
import ProjectSdkDialog from './ProjectSdkDialog.vue'
import ProjectDeleteDialog from './ProjectDeleteDialog.vue'
import { savePendingDeletion, clearPendingDeletion } from '../project-recovery'
const props = defineProps<{ action: 'create' | 'info' | 'edit' | 'sdk' | 'delete'; project?: ProjectCatalogItem; operationId?: string }>()
const emit = defineEmits<{ close: []; changed: []; created: [project: ProjectCatalogItem] }>()
const store = useProjectStore(), session = useSessionStore()
const editingInfo = ref(false)
function saved(project: ProjectCatalogItem) {
  const index = store.projects.findIndex(item => item.project_id === project.project_id)
  if (index >= 0) store.projects[index] = project; else store.projects.push(project)
  emit('close'); emit('changed')
  if (props.action === 'create') emit('created', project)
  void session.loadBootstrap({ includeDevices: false }).catch(() => undefined)
}
function removed(result: ProjectDeletionResult) {
  if (result.state === 'failed') { clearPending(); return }
  if (result.state === 'deleting') return
  if (result.state === 'deleted') clearPending()
  else remember(result.operation_id)
  void store.refreshAfterDeletion(result.project_id)
  emit('changed')
}
function clearPending() {
  if (props.project) clearPendingDeletion(session.currentUser?.principal_id || '', props.project.project_id)
  emit('changed')
}
function remember(operationId: string) {
  if (props.project) savePendingDeletion(session.currentUser?.principal_id || '', { project: props.project, operation_id: operationId })
}
</script>
