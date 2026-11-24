<template>
  <div class="resource-table package-file-table">
    <table>
      <thead>
        <tr><th scope="col">{{ zh ? '文件名称' : 'File name' }}</th><th scope="col">{{ zh ? '大小' : 'Size' }}</th></tr>
      </thead>
      <tbody>
        <tr v-for="entry in files" :key="`${entry.owner}/${entry.path}`">
          <td :title="entry.path"><span><File :size="15" aria-hidden="true" />{{ fullPath ? entry.path : entry.path.split('/').at(-1) }}</span></td>
          <td>{{ formatPackageBytes(entry.byte_size) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { File } from '@lucide/vue'
import { formatPackageBytes } from '../model-package-presentation'
import type { ModelPackageRecord } from '../services/model-package.service'

defineProps<{ files: NonNullable<ModelPackageRecord['files']>; zh: boolean; fullPath?: boolean }>()
</script>

<style scoped>
.package-file-table table { table-layout:fixed; }
.package-file-table :is(th,td) { white-space:normal; padding:7px 10px; }
.package-file-table tr > :last-child { width:88px; text-align:end; font-variant-numeric:tabular-nums; }
.package-file-table td span { display:flex; align-items:baseline; gap:7px; overflow-wrap:anywhere; }
.package-file-table svg { flex:none; align-self:center; color:var(--am-text-muted); }
</style>
