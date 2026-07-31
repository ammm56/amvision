<template>
  <div class="user-menu" :class="{ 'user-menu--compact': compact }">
    <button
      ref="triggerRef"
      class="user-menu__trigger"
      type="button"
      :title="compact ? displayName : undefined"
      :aria-label="t('accountMenu.open')"
      aria-haspopup="dialog"
      :aria-expanded="menuOpen"
      :aria-controls="menuId"
      @click="toggleMenu"
    >
      <span class="user-menu__avatar" aria-hidden="true">{{ shortName }}</span>
      <span v-if="!compact" class="user-menu__trigger-name">{{ displayName }}</span>
    </button>

    <Teleport to="body">
      <Transition name="user-menu-popover">
        <div
          v-if="menuOpen"
          :id="menuId"
          ref="menuRef"
          class="user-menu__popover"
          role="dialog"
          :aria-label="t('accountMenu.account')"
          :style="menuPositionStyle"
          tabindex="-1"
        >
          <div class="user-menu__header">
            <span class="user-menu__avatar" aria-hidden="true">{{ shortName }}</span>
            <strong class="user-menu__header-name">{{ displayName }}</strong>
          </div>

          <section class="user-menu__section">
            <button
              class="user-menu__section-toggle"
              type="button"
              :aria-expanded="expandedSection === 'language'"
              :aria-controls="languagePanelId"
              @click="toggleSection('language')"
            >
              <Languages :size="17" />
              <span>{{ t('preferences.language') }}</span>
              <span class="user-menu__current-value">{{ currentLocaleLabel }}</span>
              <ChevronDown
                v-if="expandedSection === 'language'"
                class="user-menu__chevron"
                :size="16"
              />
              <ChevronRight v-else class="user-menu__chevron" :size="16" />
            </button>
            <div
              v-if="expandedSection === 'language'"
              :id="languagePanelId"
              class="user-menu__options"
              role="radiogroup"
              :aria-label="t('preferences.language')"
            >
              <button
                v-for="option in supportedLocaleOptions"
                :key="option.locale"
                class="user-menu__option"
                :class="{ 'is-selected': preferencesStore.locale === option.locale }"
                type="button"
                role="radio"
                :aria-checked="preferencesStore.locale === option.locale"
                @click="preferencesStore.setLocale(option.locale)"
              >
                <span>{{ option.label }}</span>
                <Check v-if="preferencesStore.locale === option.locale" :size="16" />
              </button>
            </div>
          </section>

          <section class="user-menu__section">
            <button
              class="user-menu__section-toggle"
              type="button"
              :aria-expanded="expandedSection === 'appearance'"
              :aria-controls="appearancePanelId"
              @click="toggleSection('appearance')"
            >
              <Palette :size="17" />
              <span>{{ t('preferences.appearance') }}</span>
              <span class="user-menu__current-value">{{ currentThemeLabel }}</span>
              <ChevronDown
                v-if="expandedSection === 'appearance'"
                class="user-menu__chevron"
                :size="16"
              />
              <ChevronRight v-else class="user-menu__chevron" :size="16" />
            </button>
            <div
              v-if="expandedSection === 'appearance'"
              :id="appearancePanelId"
              class="user-menu__options"
              role="radiogroup"
              :aria-label="t('preferences.appearance')"
            >
              <button
                v-for="theme in themeModes"
                :key="theme"
                class="user-menu__option"
                :class="{ 'is-selected': preferencesStore.theme === theme }"
                type="button"
                role="radio"
                :aria-checked="preferencesStore.theme === theme"
                @click="preferencesStore.setTheme(theme)"
              >
                <Sun v-if="theme === 'light'" :size="16" />
                <Moon v-else :size="16" />
                <span>{{ t(`preferences.${theme}`) }}</span>
                <Check v-if="preferencesStore.theme === theme" class="user-menu__option-check" :size="16" />
              </button>
            </div>
          </section>

          <button class="user-menu__logout" type="button" @click="logout">
            <LogOut :size="17" />
            <span>{{ t('accountMenu.logout') }}</span>
          </button>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Check, ChevronDown, ChevronRight, Languages, LogOut, Moon, Palette, Sun } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { usePreferencesStore, type ThemeMode } from '@/app/stores/preferences.store'
import { useSessionStore } from '@/app/stores/session.store'
import { supportedLocaleOptions } from '@/platform/i18n'

type ExpandedSection = 'language' | 'appearance' | null

const props = withDefaults(
  defineProps<{
    compact?: boolean
  }>(),
  {
    compact: false,
  },
)

const router = useRouter()
const { t } = useI18n()
const preferencesStore = usePreferencesStore()
const sessionStore = useSessionStore()
const componentId = useId()
const menuId = `${componentId}-user-menu`
const languagePanelId = `${componentId}-language-panel`
const appearancePanelId = `${componentId}-appearance-panel`
const themeModes: ThemeMode[] = ['light', 'dark']

const triggerRef = ref<HTMLButtonElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)
const menuOpen = ref(false)
const expandedSection = ref<ExpandedSection>(null)
const menuPosition = ref({ left: 12, top: 12 })

const displayName = computed(() => sessionStore.displayName || t('auth.notSignedIn'))
const shortName = computed(() => Array.from(displayName.value.trim()).slice(0, 2).join('') || '?')
const currentLocaleLabel = computed(
  () => supportedLocaleOptions.find((option) => option.locale === preferencesStore.locale)?.label ?? preferencesStore.locale,
)
const currentThemeLabel = computed(() => t(`preferences.${preferencesStore.theme}`))
const menuPositionStyle = computed(() => ({
  left: `${menuPosition.value.left}px`,
  top: `${menuPosition.value.top}px`,
}))

function updateMenuPosition(): void {
  const trigger = triggerRef.value
  const menu = menuRef.value
  if (!trigger || !menu) return

  const viewportPadding = 12
  const gap = 8
  const triggerRect = trigger.getBoundingClientRect()
  const menuWidth = menu.offsetWidth
  const menuHeight = menu.offsetHeight
  const left = Math.min(
    Math.max(viewportPadding, triggerRect.left),
    Math.max(viewportPadding, window.innerWidth - menuWidth - viewportPadding),
  )
  const preferredTop = triggerRect.top - menuHeight - gap
  const top = Math.max(viewportPadding, Math.min(preferredTop, window.innerHeight - menuHeight - viewportPadding))

  menuPosition.value = { left, top }
}

async function openMenu(): Promise<void> {
  menuOpen.value = true
  await nextTick()
  updateMenuPosition()
  menuRef.value?.focus({ preventScroll: true })
}

function closeMenu(restoreFocus = false): void {
  menuOpen.value = false
  expandedSection.value = null
  if (restoreFocus) {
    void nextTick(() => triggerRef.value?.focus({ preventScroll: true }))
  }
}

function toggleMenu(): void {
  if (menuOpen.value) {
    closeMenu()
    return
  }
  void openMenu()
}

function toggleSection(section: Exclude<ExpandedSection, null>): void {
  expandedSection.value = expandedSection.value === section ? null : section
  void nextTick(updateMenuPosition)
}

function handlePointerDown(event: PointerEvent): void {
  if (!menuOpen.value || !(event.target instanceof Node)) return
  if (menuRef.value?.contains(event.target) || triggerRef.value?.contains(event.target)) return
  closeMenu()
}

function handleKeydown(event: KeyboardEvent): void {
  if (menuOpen.value && event.key === 'Escape') {
    event.preventDefault()
    closeMenu(true)
  }
}

async function logout(): Promise<void> {
  closeMenu()
  await sessionStore.logout()
  await router.replace('/login')
}

watch(
  () => props.compact,
  () => {
    if (menuOpen.value) void nextTick(updateMenuPosition)
  },
)

onMounted(() => {
  document.addEventListener('pointerdown', handlePointerDown)
  document.addEventListener('keydown', handleKeydown)
  window.addEventListener('resize', updateMenuPosition)
  window.addEventListener('scroll', updateMenuPosition, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handlePointerDown)
  document.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', updateMenuPosition)
  window.removeEventListener('scroll', updateMenuPosition, true)
})
</script>
