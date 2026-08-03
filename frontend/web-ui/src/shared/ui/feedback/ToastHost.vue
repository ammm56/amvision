<template>
  <Teleport to="body">
    <TransitionGroup name="toast" tag="div" class="toast-host">
      <ToastNotice
        v-for="notice in feedbackStore.notices"
        :key="notice.id"
        :notice="notice"
        :close-label="t('common.close')"
        @dismiss="feedbackStore.dismiss(notice.id)"
      />
    </TransitionGroup>
  </Teleport>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { useFeedbackStore } from '@/app/stores/feedback.store'
import ToastNotice from './ToastNotice.vue'

const route = useRoute()
const feedbackStore = useFeedbackStore()
const { t } = useI18n()

watch(() => route.fullPath, () => feedbackStore.clear())
</script>

<style scoped>
.toast-host {
  position: fixed;
  top: var(--am-space-lg);
  right: var(--am-space-lg);
  z-index: calc(var(--am-z-modal) + 20);
  display: grid;
  justify-items: end;
  gap: var(--am-space-sm);
  pointer-events: none;
}

.toast-host > :deep(*) {
  pointer-events: auto;
}

.toast-enter-active,
.toast-leave-active,
.toast-move {
  transition:
    opacity var(--am-motion-normal) var(--am-ease-standard),
    transform var(--am-motion-normal) var(--am-ease-standard);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

@media (max-width: 640px) {
  .toast-host {
    top: var(--am-space-md);
    right: var(--am-space-md);
    left: var(--am-space-md);
    justify-items: stretch;
  }
}

@media (prefers-reduced-motion: reduce) {
  .toast-enter-active,
  .toast-leave-active,
  .toast-move {
    transition: none;
  }
}
</style>
