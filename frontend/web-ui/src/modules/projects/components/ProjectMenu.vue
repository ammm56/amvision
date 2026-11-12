<template>
  <DropdownMenuRoot>
    <DropdownMenuTrigger as-child>
      <Button ref="trigger" size="sm" icon-only :aria-label="text('more')" :title="text('more')" @click.stop><Ellipsis :size="18" /></Button>
    </DropdownMenuTrigger>
    <DropdownMenuPortal>
      <DropdownMenuContent class="project-menu" :side-offset="4" align="end" @close-auto-focus="afterClose">
        <DropdownMenuItem class="project-menu__item" @select="pendingAction = 'info'"><Info :size="16" />{{ text('detailsAction') }}</DropdownMenuItem>
        <DropdownMenuItem v-if="editable" class="project-menu__item" @select="pendingAction = 'edit'"><Pencil :size="16" />{{ text('editAction') }}</DropdownMenuItem>
        <DropdownMenuSeparator v-if="deletable" class="project-menu__separator" />
        <DropdownMenuItem v-if="deletable" class="project-menu__item project-menu__item--danger" @select="pendingAction = 'delete'"><Trash2 :size="16" />{{ text('removeAction') }}</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenuRoot>
</template>
<script setup lang="ts">
import { DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from 'reka-ui'
import { Ellipsis, Info, Pencil, Trash2 } from '@lucide/vue'
import { ref } from 'vue'
import Button from '@/shared/ui/components/Button.vue'
import { useProjectText } from '../project-workspace'

defineProps<{ editable: boolean; deletable: boolean }>()
const emit = defineEmits<{ action: [action: 'info' | 'edit' | 'delete'] }>()
const text = useProjectText()
const trigger = ref<InstanceType<typeof Button> | null>(null)
let pendingAction: 'info' | 'edit' | 'delete' | undefined
function afterClose(event: Event) {
  if (!pendingAction) return
  // 菜单完成焦点释放后再打开模态面板，避免把新抽屉的焦点抢回背景。
  event.preventDefault()
  trigger.value?.$el.focus({ preventScroll: true })
  const action = pendingAction
  pendingAction = undefined
  emit('action', action)
}
</script>
<style>
.project-menu { z-index: 100; padding: 6px; min-width: 144px; background: var(--am-surface-raised); border: 1px solid var(--am-border); border-radius: 8px; box-shadow: var(--am-shadow-modal); }
.project-menu__item { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-radius: var(--am-radius-sm); cursor: pointer; color: var(--am-text); font-size: 13px; outline: none; }
.project-menu__item[data-highlighted] { background: var(--am-hover-surface); }
.project-menu__item--danger { color: var(--am-danger-icon); }
.project-menu__separator { height: 1px; background: var(--am-border); margin: 6px 0; }
</style>
