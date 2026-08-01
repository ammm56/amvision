<template>
  <section class="loading-panel" :class="{ 'loading-panel--compact': compact }" role="status" aria-live="polite">
    <div class="loading-panel__spinner" aria-hidden="true" />
    <div>
      <h2>{{ title }}</h2>
      <p>{{ description }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  description: string
  compact?: boolean
}>()
</script>

<style scoped>
.loading-panel {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 180px;
  padding: var(--am-space-2xl);
  border: 1px solid var(--line);
  border-radius: var(--am-radius-md);
  background: var(--surface);
}

.loading-panel h2 {
  margin: 0 0 8px;
  color: var(--text);
  font-size: 20px;
}

.loading-panel p {
  margin: 0;
  color: var(--muted);
  line-height: 1.6;
}

.loading-panel__spinner {
  position: relative;
  display: grid;
  place-items: center;
  width: 54px;
  height: 54px;
  flex: 0 0 auto;
  border-radius: var(--am-radius-md);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.loading-panel__spinner::before {
  content: '';
  position: absolute;
  width: 36px;
  height: 36px;
  border: 3px solid color-mix(in srgb, var(--accent) 18%, transparent);
  border-top-color: var(--accent);
  border-radius: 999px;
  animation: loading-panel-spin 0.9s linear infinite;
}

.loading-panel--compact {
  min-height: auto;
  padding: 14px 16px;
  border-radius: var(--am-radius-md);
  box-shadow: none;
}

.loading-panel--compact h2 {
  margin-bottom: 3px;
  font-size: 15px;
}

.loading-panel--compact p {
  font-size: 12px;
}

.loading-panel--compact .loading-panel__spinner {
  width: 40px;
  height: 40px;
  border-radius: var(--am-radius-md);
}

.loading-panel--compact .loading-panel__spinner::before {
  width: 28px;
  height: 28px;
  border-width: 2px;
}

@keyframes loading-panel-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .loading-panel__spinner::before {
    animation: none;
  }
}

@media (max-width: 640px) {
  .loading-panel {
    align-items: flex-start;
    padding: 22px;
  }
}
</style>
