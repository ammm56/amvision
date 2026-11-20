<template>
  <span v-if="formats.length || fallbackLabel" class="runtime-formats">
    <span v-for="format in formats" :key="format" class="runtime-formats__item" role="img" :aria-label="label(format)" :title="label(format)">
      <img v-if="logos[format]" class="runtime-formats__mark" :class="`is-${format}`" :src="logos[format]" alt="" />
      <Cpu v-else-if="format === 'rknn'" :size="17" aria-hidden="true" />
      <BrainCircuit v-else-if="format === 'coreml'" :size="17" aria-hidden="true" />
      <FileBox v-else :size="17" aria-hidden="true" />
      <Zap v-if="format === 'onnx-optimized'" class="runtime-formats__optimized" :size="11" aria-hidden="true" />
    </span>
    <span v-if="!formats.length && fallbackLabel" class="runtime-formats__item" role="img" :aria-label="fallbackLabel" :title="fallbackLabel">
      <FileBox :size="17" aria-hidden="true" />
    </span>
  </span>
  <span v-else>—</span>
</template>

<script setup lang="ts">
import { BrainCircuit, Cpu, FileBox, Zap } from '@lucide/vue'
// PyTorch、ONNX、NVIDIA 标记来自 Simple Icons。
import pytorchLogo from '../assets/pytorch.svg'
import onnxLogo from '../assets/onnx.svg'
import nvidiaLogo from '../assets/nvidia.svg'
// OpenVINO 标记来自 OpenVINO 官方仓库。
import openvinoLogo from '../assets/openvino.svg'

defineProps<{ formats: string[]; fallbackLabel?: string }>()

const logos: Partial<Record<string, string>> = {
  pytorch: pytorchLogo,
  onnx: onnxLogo,
  'onnx-optimized': onnxLogo,
  'openvino-ir': openvinoLogo,
  'tensorrt-engine': nvidiaLogo,
}
const labels: Partial<Record<string, string>> = {
  pytorch: 'PyTorch',
  onnx: 'ONNX',
  'onnx-optimized': 'ONNX optimized',
  'openvino-ir': 'OpenVINO',
  'tensorrt-engine': 'TensorRT',
  rknn: 'RKNN',
  coreml: 'Core ML',
}

function label(format: string): string {
  return labels[format] ?? format
}
</script>

<style scoped>
.runtime-formats { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 8px; }
.runtime-formats__item { display: inline-grid; position: relative; place-items: center; flex: none; min-width: 22px; min-height: 24px; color: var(--am-text); }
.runtime-formats__mark { display: block; width: 17px; height: 17px; object-fit: contain; }
.runtime-formats__mark.is-openvino-ir { width: 44px; height: 14px; border-radius: 2px; }
html[data-theme='dark'] .runtime-formats__mark:is(.is-onnx, .is-onnx-optimized) { filter: invert(1); }
.runtime-formats__optimized { position: absolute; inset-inline-end: -1px; bottom: 1px; color: var(--am-text); background: var(--am-surface-raised); border-radius: 2px; }
</style>
