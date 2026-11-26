<template>
  <component
    :is="ordered ? 'ol' : 'ul'"
    v-if="categories?.length"
    class="training-category-list"
    :class="{ 'training-category-list--ordered': ordered }"
    :start="ordered ? 0 : undefined"
    :aria-label="label"
    role="list"
    tabindex="0"
  >
    <li v-for="(name, index) in categories" :key="index" role="listitem">
      <span v-if="ordered" class="training-category-list__id">{{ index }}</span>
      <span>{{ name }}</span>
    </li>
  </component>
  <span v-else class="training-category-list__empty">—</span>
</template>

<script setup lang="ts">
defineProps<{
  categories?: readonly string[]
  label: string
  ordered?: boolean
}>()
</script>

<style scoped>
.training-category-list {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  align-content: flex-start;
  min-width: 0;
  max-block-size: 9rem;
  overflow-y: auto;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.training-category-list > li {
  min-width: 0;
  max-width: 100%;
  padding: 4px 8px;
  border: 1px solid var(--am-border);
  border-radius: 5px;
  background: var(--am-surface);
  color: var(--am-text);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.training-category-list--ordered {
  display: grid;
  gap: 0;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface);
}
.training-category-list--ordered > li {
  display: grid;
  grid-template-columns: minmax(2ch, max-content) minmax(0, 1fr);
  align-items: start;
  gap: 10px;
  padding: 6px 10px;
  border: 0;
  border-radius: 0;
  background: transparent;
  font-size: inherit;
}
.training-category-list--ordered > li + li { border-block-start: 1px solid var(--am-border); }
.training-category-list__id { color: var(--am-text-muted); font-variant-numeric: tabular-nums; }
.training-category-list__empty { color: var(--am-text-muted); }
</style>
