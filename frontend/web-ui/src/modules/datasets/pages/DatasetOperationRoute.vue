<template>
  <DatasetRevisionPage
    v-if="$route.params.operation === 'samples'"
    :key="$route.path"
  />
  <DatasetOperationPage v-else :key="$route.path" />
</template>
<script setup lang="ts">
import DatasetOperationPage from './DatasetOperationPage.vue'
import DatasetRevisionPage from './DatasetRevisionPage.vue'
</script>
