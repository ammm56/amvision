<template>
  <span
    class="runtime-formats deployment-runtime-badge"
    :class="{ 'is-muted': muted }"
    role="img"
    :aria-label="tooltip || labelText"
    :title="tooltip || labelText"
  >
    <span class="runtime-formats__item" aria-hidden="true">
      <img v-if="backendLogo" class="runtime-formats__mark" :class="`is-${iconKey}`" :src="backendLogo" alt="" />
      <Cpu v-else-if="iconKey === 'rknn'" :size="17" />
      <BrainCircuit v-else-if="iconKey === 'coreml'" :size="17" />
      <FileBox v-else :size="17" />
      <Zap v-if="isOptimized" class="runtime-formats__optimized" :size="11" />
    </span>
    <span v-if="deviceKind && !backendOnly" class="runtime-formats__device" aria-hidden="true">
      <Cpu v-if="deviceKind === 'cpu'" :size="15" />
      <Monitor v-else-if="deviceKind === 'gpu'" :size="15" />
      <BrainCircuit v-else-if="deviceKind === 'npu'" :size="15" />
      <Sparkles v-else-if="deviceKind === 'auto'" :size="15" />
      <FileBox v-else :size="15" />
    </span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { BrainCircuit, Cpu, FileBox, Monitor, Sparkles, Zap } from '@lucide/vue'
// PyTorch、ONNX、NVIDIA 标记来自 Simple Icons。
import pytorchLogo from '@/modules/models/assets/pytorch.svg'
import onnxLogo from '@/modules/models/assets/onnx.svg'
import nvidiaLogo from '@/modules/models/assets/nvidia.svg'
// OpenVINO 标记来自 OpenVINO 官方仓库。
import openvinoLogo from '@/modules/models/assets/openvino.svg'
import {
  formatDeploymentBackend,
  formatDeploymentDeviceName,
  formatDeploymentPrecision,
} from '../deployment-presentation'

const props = defineProps<{
  backend?: string
  device?: string
  precision?: string
  buildFormat?: string
  backendOnly?: boolean
  muted?: boolean
  tooltip?: string
}>()

const logos: Partial<Record<string, string>> = {
  pytorch: pytorchLogo,
  onnx: onnxLogo,
  'onnx-optimized': onnxLogo,
  'openvino-ir': openvinoLogo,
  'tensorrt-engine': nvidiaLogo,
}

const isOptimized = computed(() => {
  const format = String(props.buildFormat ?? '').trim().toLowerCase()
  const backend = String(props.backend ?? '').trim().toLowerCase()
  return format === 'onnx-optimized' || backend === 'onnx-optimized'
})

const iconKey = computed(() => {
  if (isOptimized.value) return 'onnx-optimized'
  const backend = String(props.backend ?? '').trim().toLowerCase()
  const format = String(props.buildFormat ?? '').trim().toLowerCase()
  if (backend === 'openvino' || backend === 'openvino-ir' || format === 'openvino-ir') return 'openvino-ir'
  if (backend === 'onnxruntime' || backend === 'onnx' || format === 'onnx') return 'onnx'
  if (backend === 'tensorrt' || backend === 'tensorrt-engine' || format === 'tensorrt-engine') return 'tensorrt-engine'
  if (backend === 'pytorch' || format === 'pytorch') return 'pytorch'
  if (backend === 'rknn') return 'rknn'
  if (backend === 'coreml') return 'coreml'
  return 'fallback'
})

const backendLogo = computed(() => logos[iconKey.value])

const deviceKind = computed<'cpu' | 'gpu' | 'npu' | 'auto' | 'other' | null>(() => {
  const raw = String(props.device ?? '').trim()
  if (!raw || raw === '—') return null
  const lower = raw.toLowerCase()
  if (lower.startsWith('cpu')) return 'cpu'
  if (lower.startsWith('gpu') || lower.startsWith('cuda')) return 'gpu'
  if (lower.startsWith('npu')) return 'npu'
  if (lower === 'auto') return 'auto'
  return 'other'
})

const labelText = computed(() => {
  const fallbackBackend = iconKey.value === 'openvino-ir'
    ? 'openvino'
    : iconKey.value.startsWith('onnx')
      ? 'onnxruntime'
      : iconKey.value === 'tensorrt-engine'
        ? 'tensorrt'
        : 'pytorch'
  const backendText = formatDeploymentBackend(props.backend || fallbackBackend)
  const backendPart = isOptimized.value ? `${backendText} (Optimized)` : backendText
  const precisionText = formatDeploymentPrecision(props.precision)
  const head = precisionText ? `${backendPart} ${precisionText}` : backendPart
  const rawDevice = String(props.device ?? '').trim()
  const deviceText = rawDevice === '—' ? '' : formatDeploymentDeviceName(rawDevice)
  return deviceText ? `${head} · ${deviceText}` : head
})
</script>

<style scoped>
.runtime-formats {
  display: inline-flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 6px;
}

.runtime-formats__item,
.runtime-formats__device {
  display: inline-grid;
  position: relative;
  place-items: center;
  flex: none;
  min-width: 22px;
  min-height: 24px;
  color: var(--am-text);
}

.runtime-formats__device {
  min-width: 16px;
  color: var(--am-text-muted);
}

.runtime-formats__mark {
  display: block;
  width: 17px;
  height: 17px;
  object-fit: contain;
}

.runtime-formats__mark.is-openvino-ir {
  width: 44px;
  height: 14px;
  border-radius: 2px;
}

.runtime-formats__mark.is-tensorrt-engine {
  filter: brightness(0);
}

html[data-theme='dark'] .runtime-formats__mark:is(.is-onnx, .is-onnx-optimized) {
  filter: invert(1);
}

html[data-theme='dark'] .runtime-formats__mark.is-tensorrt-engine {
  filter: brightness(0) invert(1);
}

.deployment-runtime-badge.is-muted {
  opacity: 0.42;
}

.runtime-formats__optimized {
  position: absolute;
  inset-inline-end: -1px;
  bottom: 1px;
  color: var(--am-text);
  background: var(--am-surface-raised);
  border-radius: 2px;
}
</style>
