<template><p role="status">{{ t(payloadType==='calibrated-profiles.v1'?'profilesOnly':payloadType==='calibrated-raster.v1'?'rasterOnly':'localOnly') }}</p></template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
defineProps<{payloadType:string}>()
const {t}=useI18n({useScope:'local',messages:{
  'zh-CN':{localOnly:'此输入仅接受同机点云调用',rasterOnly:'此输入仅接受同机标定栅格调用',profilesOnly:'此输入仅接受同机标定轮廓调用'},
  'en-US':{localOnly:'This input requires a same-host point cloud call',rasterOnly:'This input requires a same-host calibrated raster call',profilesOnly:'This input requires a same-host calibrated profile call'},
}})
</script>
