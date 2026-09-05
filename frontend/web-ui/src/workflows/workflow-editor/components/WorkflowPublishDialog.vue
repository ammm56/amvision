<template>
  <ConfirmDialog
    v-if="open"
    :title="t('workflowEditor.publishDialog.title')"
    :confirm-label="t('workflowEditor.publishDialog.confirm')"
    :cancel-label="t('common.cancel')"
    :busy="busy"
    confirm-variant="primary"
    initial-focus="first-field"
    @cancel="emit('cancel')"
    @confirm="emit('publish', releaseNotes.trim())"
  >
    <label class="workflow-dialog-field">
      <span>{{ t('workflowEditor.publishDialog.releaseNotes') }}</span>
      <textarea
        v-model="releaseNotes"
        data-dialog-initial-focus
        rows="5"
        maxlength="4096"
        :placeholder="t('workflowEditor.publishDialog.releaseNotesPlaceholder')"
      />
    </label>
    <InlineError v-if="errorMessage" :message="errorMessage" />
  </ConfirmDialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

const props = defineProps<{
  open: boolean
  busy: boolean
  errorMessage?: string | null
}>()

const emit = defineEmits<{
  cancel: []
  publish: [releaseNotes: string]
}>()

const { t } = useI18n()
const releaseNotes = ref('')

watch(
  () => props.open,
  (open) => {
    if (open) releaseNotes.value = ''
  },
  { immediate: true },
)
</script>

<style scoped>
.workflow-dialog-field {
  display: grid;
  gap: var(--am-space-sm);
}

.workflow-dialog-field > span {
  color: var(--am-text-strong);
  font-size: 13px;
  font-weight: 700;
}

.workflow-dialog-field textarea {
  width: 100%;
  min-height: 112px;
  resize: vertical;
}
</style>
