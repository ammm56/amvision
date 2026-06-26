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
  padding: 28px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background:
    radial-gradient(circle at 12% 20%, color-mix(in srgb, var(--accent) 14%, transparent), transparent 28%),
    linear-gradient(135deg, var(--surface), var(--summary-bg));
  box-shadow: 0 18px 36px rgba(17, 24, 39, 0.08);
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
  border-radius: 18px;
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
  border-radius: 12px;
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
  border-radius: 12px;
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

@media (max-width: 640px) {
  .loading-panel {
    align-items: flex-start;
    padding: 22px;
  }
}
</style>
