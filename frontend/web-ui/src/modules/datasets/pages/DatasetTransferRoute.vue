<template><DatasetTransferPage :key="route.fullPath" /></template>
<script setup lang="ts">
import { useRoute } from 'vue-router'
import DatasetTransferPage from './DatasetTransferPage.vue'
const route = useRoute()
</script>
