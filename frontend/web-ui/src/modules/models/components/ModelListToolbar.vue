<template>
  <div class="model-list-toolbar">
    <Button class="model-list-toolbar__base-models" variant="ghost" @click="$emit('open-base-models')">
      <Database :size="17" aria-hidden="true" />{{ zh ? '基础模型' : 'Base models' }}
    </Button>
    <slot name="leading" />
    <div v-if="search !== undefined" class="input-with-icon model-list-toolbar__search">
      <Search :size="16" aria-hidden="true" />
      <input :value="search" :aria-label="searchLabel" :placeholder="searchLabel" @input="$emit('update:search', ($event.target as HTMLInputElement).value)" />
      <Button v-if="search" variant="ghost" size="sm" icon-only :aria-label="zh ? '清除搜索关键词' : 'Clear search term'" @click="$emit('update:search', '')">
        <X :size="15" aria-hidden="true" />
      </Button>
    </div>
    <slot />
  </div>
</template>

<script setup lang="ts">
import { Database, Search, X } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'

defineProps<{ zh: boolean; search?: string; searchLabel?: string }>()
defineEmits<{ 'open-base-models': []; 'update:search': [value: string] }>()
</script>

<style scoped>
.model-list-toolbar { display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
.model-list-toolbar__base-models { color:var(--am-action-primary-strong); padding-inline-start:0; }
.model-list-toolbar__search { width:clamp(220px, 26vw, 380px); max-width:100%; margin-inline-end:auto; grid-auto-flow:column; }
@media (max-width:1200px) {
  .model-list-toolbar { gap:12px; }
  .model-list-toolbar__search { width:220px; }
}
</style>
