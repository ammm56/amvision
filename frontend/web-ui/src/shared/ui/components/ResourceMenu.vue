<template>
  <DropdownMenuRoot>
    <DropdownMenuTrigger as-child><Button ref="trigger" size="sm" icon-only :aria-label="label" :title="label" @click.stop><Ellipsis :size="18" /></Button></DropdownMenuTrigger>
    <DropdownMenuPortal><DropdownMenuContent class="resource-menu" align="end" :side-offset="4" @close-auto-focus="afterClose">
      <DropdownMenuItem v-for="item in items" :key="item.id" class="resource-menu__item" :class="{'resource-menu__item--danger':item.danger}" :disabled="item.disabled" @select="pending = item.id"><component :is="item.icon" v-if="item.icon" :size="16" />{{ item.label }}</DropdownMenuItem>
    </DropdownMenuContent></DropdownMenuPortal>
  </DropdownMenuRoot>
</template>
<script setup lang="ts">
import { ref, type Component } from 'vue'
import { DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent, DropdownMenuItem } from 'reka-ui'
import { Ellipsis } from '@lucide/vue'
import Button from './Button.vue'
defineProps<{label:string;items:{id:string;label:string;icon?:Component;danger?:boolean;disabled?:boolean}[]}>()
const emit=defineEmits<{action:[id:string]}>(), trigger=ref<InstanceType<typeof Button>|null>(null)
let pending:string|undefined
function afterClose(event:Event) { if(!pending)return; event.preventDefault(); trigger.value?.$el.focus({preventScroll:true}); const id=pending; pending=undefined; emit('action',id) }
</script>
<style>
.resource-menu{z-index:100;padding:6px;min-width:148px;background:var(--am-surface-raised);border:1px solid var(--am-border);border-radius:8px;box-shadow:var(--am-shadow-modal)}
.resource-menu__item{display:flex;align-items:center;gap:8px;padding:9px 12px;border-radius:var(--am-radius-sm);cursor:pointer;color:var(--am-text);font-size:13px;outline:none}
.resource-menu__item[data-highlighted]{background:var(--am-hover-surface)}.resource-menu__item--danger{color:var(--am-danger-icon)}.resource-menu__item[data-disabled]{opacity:.45;pointer-events:none}
</style>
