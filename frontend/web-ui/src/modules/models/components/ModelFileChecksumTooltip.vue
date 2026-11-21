<template>
  <TooltipProvider :delay-duration="200">
    <TooltipRoot :open="open" disable-closing-trigger @update:open="$emit('update:open', $event)">
      <TooltipTrigger as-child>
        <Button variant="ghost" size="sm" icon-only :aria-label="zh ? '查看 SHA256' : 'View SHA256'"
          @click="$emit('update:open', true)" @keydown.esc="dismiss">
          <ShieldCheck :size="15" aria-hidden="true" />
        </Button>
      </TooltipTrigger>
      <TooltipPortal>
        <TooltipContent side="top" align="end" :side-offset="6" :collision-padding="10" :style="{ zIndex: 'var(--am-z-tooltip)' }">
          <span class="model-file-checksum">
            <strong>SHA-256</strong>
            <slot />
          </span>
        </TooltipContent>
      </TooltipPortal>
    </TooltipRoot>
  </TooltipProvider>
</template>

<script setup lang="ts">
import { ShieldCheck } from '@lucide/vue'
import { TooltipContent, TooltipPortal, TooltipProvider, TooltipRoot, TooltipTrigger } from 'reka-ui'
import Button from '@/shared/ui/components/Button.vue'

const props = defineProps<{ open: boolean; zh: boolean }>()
const emit = defineEmits<{ 'update:open': [open: boolean] }>()

function dismiss(event: KeyboardEvent): void {
  if (!props.open) return
  event.stopPropagation()
  event.preventDefault()
  emit('update:open', false)
}
</script>

<style scoped>
.model-file-checksum {
  display:grid;
  gap:4px;
  max-width:min(480px,calc(100vw - 24px));
  padding:8px 10px;
  border:1px solid var(--am-border-strong);
  border-radius:6px;
  background:var(--am-surface-raised);
  color:var(--am-text);
  box-shadow:var(--am-shadow-modal);
  font-size:12px;
  overflow-wrap:anywhere;
}
</style>
