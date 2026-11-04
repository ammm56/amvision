<template>
  <DropdownMenuRoot><DropdownMenuTrigger as-child><Button size="sm" variant="ghost" :aria-label="text('more')" @click.stop><Ellipsis :size="18" /></Button></DropdownMenuTrigger><DropdownMenuPortal><DropdownMenuContent class="project-menu" :side-offset="4" align="end">
    <DropdownMenuItem class="project-menu__item" @select="emit('action', 'info')">{{ text('info') }}</DropdownMenuItem>
    <DropdownMenuItem v-if="editable" class="project-menu__item" @select="emit('action', 'edit')">{{ text('edit') }}</DropdownMenuItem>
    <DropdownMenuItem v-if="exportable" class="project-menu__item" @select="emit('action', 'sdk')">{{ text('sdk') }}</DropdownMenuItem>
    <DropdownMenuItem v-if="deletable" class="project-menu__item project-menu__item--danger" @select="emit('action', 'delete')">{{ text('remove') }}</DropdownMenuItem>
  </DropdownMenuContent></DropdownMenuPortal></DropdownMenuRoot>
</template>
<script setup lang="ts">
import { DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent, DropdownMenuItem } from 'reka-ui'
import { Ellipsis } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import { useProjectText } from '../project-workspace'
defineProps<{ editable: boolean; deletable: boolean; exportable: boolean }>()
const emit = defineEmits<{ action: [action: 'info' | 'edit' | 'sdk' | 'delete'] }>()
const text = useProjectText()
</script>
<style>
.project-menu { z-index: 100; padding: 6px; min-width: 174px; background: var(--am-surface-raised); border: 1px solid var(--am-border); border-radius: 8px; box-shadow: var(--am-shadow-modal); }
.project-menu__item { padding: 9px 12px; border-radius: 4px; cursor: pointer; color: var(--am-text); font-size: 13px; outline: none; }.project-menu__item[data-highlighted] { background: var(--am-hover-surface); }.project-menu__item--danger { color: var(--am-danger-icon); }
</style>
