<template>
  <Button v-if="allowed" size="sm" variant="ghost" :disabled="disabled || busy" @click="openDialog">{{ label || (kind === 'dataset-import' ? t('removeImport') : t('remove')) }}</Button>
  <Teleport to="body">
    <ConfirmDialog v-if="target" :title="target.kind === 'dataset-import' ? t('removeImportTitle') : t('confirm')" :message="target.resourceId" :details="target.kind === 'dataset-import' ? t('removeImportDetails') : t('detail')" :confirm-label="target.kind === 'dataset-import' ? t('removeImport') : t('remove')" :cancel-label="t('cancel')" :busy="busy" @cancel="target = null" @confirm="remove">
      <InlineError :message="error" />
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '@/app/stores/session.store'
import { submitResourceDeletion, type DeletionKind } from '@/shared/api/resource-deletion'
import { getErrorMessage } from '@/shared/api/error'
import Button from './Button.vue'
import ConfirmDialog from './ConfirmDialog.vue'
import InlineError from '../feedback/InlineError.vue'
import { resourceDeletionMessages } from './resource-deletion-messages'

const props = defineProps<{ kind: DeletionKind; resourceId: string; projectId: string; disabled?: boolean; label?: string }>()
const emit = defineEmits<{ accepted: [] }>()
const { t } = useI18n({ messages: resourceDeletionMessages })
const session = useSessionStore()
const allowed = computed(() => Boolean(props.projectId) && session.hasScopes([props.kind === 'task' ? 'tasks:write' : 'datasets:write']))
const target = ref<{ kind: DeletionKind; resourceId: string; projectId: string } | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)
function openDialog() {
  error.value = null
  target.value = { kind: props.kind, resourceId: props.resourceId, projectId: props.projectId }
}
async function remove() {
  const selected = target.value
  if (!selected || busy.value) return
  busy.value = true
  error.value = null
  try {
    await submitResourceDeletion(selected.kind, selected.resourceId, selected.projectId)
    target.value = null
    emit('accepted')
  } catch (cause) {
    error.value = getErrorMessage(cause)
  } finally {
    busy.value = false
  }
}
</script>
