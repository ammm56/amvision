<template><p role="status">{{ t('localOnly') }}</p></template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const {t}=useI18n({useScope:'local',messages:{
  'zh-CN':{localOnly:'此输入仅接受同机点云调用'},
  'en-US':{localOnly:'This input requires a same-host point cloud call'},
}})
</script>
