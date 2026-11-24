<template>
  <div class="resource-table package-class-table">
    <table>
      <thead><tr><th scope="col">{{ zh ? '索引' : 'Index' }}</th><th scope="col">{{ zh ? '类别名称' : 'Class name' }}</th></tr></thead>
      <tbody><tr v-for="(category, index) in categories" :key="index"><td>{{ index }}</td><td>{{ category }}</td></tr></tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
defineProps<{ categories: string[]; zh: boolean }>()
</script>

<style scoped>
.package-class-table { max-height:230px; overflow:auto; }
.package-class-table table { table-layout:fixed; }
.package-class-table :is(th,td) { padding-block:6px; white-space:normal; overflow-wrap:anywhere; }
.package-class-table thead th { position:sticky; top:0; background:var(--am-surface-muted); }
.package-class-table tr > :first-child { width:72px; font-variant-numeric:tabular-nums; }
</style>
