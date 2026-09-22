<template>
  <component
    class="animated-brand"
    :class="{ 'animated-brand--plain': plain }"
    :is="to ? RouterLink : 'span'"
    :to="to"
    :role="to ? undefined : 'img'"
    :aria-label="plain ? 'amvar vision' : 'AMVAR Vision'"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
    @focusin="focused = true"
    @focusout="focused = false"
  >
    <span class="animated-brand__lockup" aria-hidden="true">
      <span class="animated-brand__prefix">{{ plain ? 'amvar' : 'AMVAR' }}</span>
      <Motion
        as="span"
        class="animated-brand__suffix"
        :initial="false"
        :animate="{ width: suffixWidth ?? 'auto' }"
        :transition="reducedMotion ? { duration: 0 } : spring"
      >
        <span ref="measureElement" class="animated-brand__measure">
          <span v-for="(character, index) in word" :key="index" class="animated-brand__character">{{ character }}</span>
        </span>
        <span v-if="reducedMotion" class="animated-brand__word">{{ words[0] }}</span>
        <AnimatePresence v-else mode="wait" :initial="false">
          <Motion :key="word" as="span" class="animated-brand__word">
            <span class="animated-brand__split">
              <Motion
                v-for="(character, index) in word"
                :key="index"
                as="span"
                class="animated-brand__character"
                :initial="{ y: '100%' }"
                :animate="{ y: 0 }"
                :exit="{ y: '-120%' }"
                :transition="{ ...spring, delay: (word.length - 1 - index) * 0.025 }"
              >{{ character }}</Motion>
            </span>
          </Motion>
        </AnimatePresence>
      </Motion>
    </span>
  </component>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, type WatchStopHandle } from 'vue'
import { RouterLink } from 'vue-router'
import { AnimatePresence, Motion, type MotionProps } from 'motion-v'
import { useResizeObserver } from '@vueuse/core'

const props = defineProps<{ to?: string; plain?: boolean }>()

// 品牌能力词缀仅用于展示，不表示当前路由或服务运行状态。
const words = computed(() => {
  const suffixes = ['Vision', 'Workflow', 'DeepLearn', 'Connect', 'Identify', 'Control', 'Motion', 'Label', 'Agent']
  return props.plain ? suffixes.map(value => value.toLowerCase()) : suffixes
})
// 按 Vue Bits Rotating Text 示例使用末字符优先的弹簧动画与先退出后进入。
// https://vue-bits.dev/text-animations/rotating-text
const spring = { type: 'spring', damping: 30, stiffness: 400 } satisfies MotionProps['transition']
const current = ref(0)
const word = computed(() => words.value[current.value])
const measureElement = ref<HTMLElement>()
const suffixWidth = ref<number>()
/** 测量当前词而非最长词；直接驱动真实宽度，使居中的文字组合逐帧平滑移动。 */
function updateWidth() {
  const width = measureElement.value?.getBoundingClientRect().width ?? 0
  if (width > 0) suffixWidth.value = width + (props.plain ? 0 : 12)
}
useResizeObserver(measureElement, updateWidth)
watch(word, updateWidth, { flush: 'post' })
const hovered = ref(false)
const focused = ref(false)
const hidden = ref(false)
const reducedMotion = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let motionQuery: MediaQueryList | undefined
let stopWatching: WatchStopHandle | undefined

/** 清理当前轮换，恢复时从完整间隔开始，不补播后台动画。 */
function clearRotation() {
  clearTimeout(timer)
  timer = undefined
}

function scheduleRotation() {
  clearRotation()
  if (reducedMotion.value) current.value = 0
  if (hovered.value || focused.value || hidden.value || reducedMotion.value) return
  timer = setTimeout(() => {
    current.value = (current.value + 1) % words.value.length
    scheduleRotation()
  }, 2000)
}

function readVisibility() { hidden.value = document.hidden }
function readMotionPreference() { reducedMotion.value = motionQuery?.matches ?? false }

onMounted(() => {
  updateWidth()
  motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  readVisibility()
  readMotionPreference()
  document.addEventListener('visibilitychange', readVisibility)
  motionQuery.addEventListener('change', readMotionPreference)
  stopWatching = watch([hovered, focused, hidden, reducedMotion], scheduleRotation, { immediate: true, flush: 'sync' })
})

onBeforeUnmount(() => {
  stopWatching?.()
  clearRotation()
  document.removeEventListener('visibilitychange', readVisibility)
  motionQuery?.removeEventListener('change', readMotionPreference)
})
</script>

<style scoped>
.animated-brand { display: inline-flex; align-items: center; min-width: 0; font-size: 16px; font-weight: 700; line-height: 28px; white-space: nowrap; }
.animated-brand__lockup { display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; }
.animated-brand__prefix { letter-spacing: -0.4px; }
.animated-brand__suffix { position: relative; display: inline-flex; flex: 0 0 auto; align-items: center; justify-content: center; height: 28px; overflow: hidden; border-radius: 6px; padding: 0 6px; background: var(--am-brand-primary); color: var(--am-brand-on-primary); }
.animated-brand--plain { font: inherit; }
.animated-brand--plain .animated-brand__prefix { letter-spacing: inherit; }
.animated-brand--plain .animated-brand__suffix { height: 1lh; border-radius: 0; padding: 0; background: none; color: inherit; }
.animated-brand__measure { position: absolute; display: inline-flex; width: max-content; visibility: hidden; pointer-events: none; }
.animated-brand__word { position: relative; display: inline-flex; align-items: center; justify-content: center; }
.animated-brand__split { display: inline-flex; overflow: hidden; }
.animated-brand__character { display: inline-block; }
</style>
