<template>
  <div class="user-access-form">
    <details open>
      <summary>{{ t('userAccess.pagesTitle') }}</summary>
      <div v-if="model.pages === null" class="access-compatibility">
        <span>{{ t('userAccess.compatible') }}</span>
        <Button size="sm" variant="secondary" @click="customizePages">{{ t('userAccess.customize') }}</Button>
      </div>
      <template v-else>
        <div class="access-group-actions">
          <Button size="sm" variant="secondary" @click="model.pages = pageDefinitions.map(p => p.id)">{{ t('userAccess.selectAll') }}</Button>
          <Button size="sm" variant="secondary" @click="model.pages = []">{{ t('userAccess.clear') }}</Button>
        </div>
        <div class="access-checks">
          <label v-for="page in pageDefinitions" :key="page.id" class="checkbox-field">
            <input v-model="model.pages" type="checkbox" :value="page.id" />
            <span>{{ t(`userAccess.pages.${page.id}`) }}</span>
          </label>
        </div>
      </template>
    </details>
    <details open>
      <summary>{{ t('userAccess.operationsTitle') }}</summary>
      <label class="checkbox-field"><input type="checkbox" :checked="model.scopes.includes('*')" @change="toggleAll" /><span>{{ t('userAccess.allOperations') }}</span></label>
      <div class="access-group-actions">
        <Button size="sm" variant="secondary" :disabled="model.scopes.includes('*')" @click="model.scopes = [...new Set([...model.scopes, ...operationDefinitions.map(o => o.id)])]">{{ t('userAccess.selectAll') }}</Button>
        <Button size="sm" variant="secondary" :disabled="model.scopes.includes('*')" @click="model.scopes = unknownScopes">{{ t('userAccess.clear') }}</Button>
      </div>
      <div class="access-checks">
        <label v-for="operation in operationDefinitions" :key="operation.id" class="checkbox-field">
          <input v-model="model.scopes" type="checkbox" :value="operation.id" :disabled="model.scopes.includes('*')" />
          <span>{{ t(`userAccess.operations.${operation.id}`) }}</span>
        </label>
      </div>
      <p class="access-hint">{{ t('userAccess.filesHint') }}</p>
      <p v-if="unknownScopes.length" class="access-hint">{{ t('userAccess.unknown') }}: {{ unknownScopes.join(', ') }}</p>
    </details>
    <fieldset>
      <legend>{{ t('userAccess.projects') }}</legend>
      <div class="access-checks">
        <label class="checkbox-field"><input v-model="model.allProjects" type="radio" :value="false" :name="projectModeId" /><span>{{ t('userAccess.specifiedProjects') }}</span></label>
        <label class="checkbox-field"><input v-model="model.allProjects" type="radio" :value="true" :name="projectModeId" /><span>{{ t('userAccess.allProjects') }}</span></label>
      </div>
      <template v-if="!model.allProjects">
        <label class="field"><span>{{ t('userAccess.searchProjects') }}</span><input v-model.trim="projectSearch" type="search" /></label>
        <MultiSelect v-model="model.projectIds" :options="projectOptions" :placeholder="t('userAccess.selectProject')" />
      </template>
    </fieldset>
    <InlineError :message="issue ? t(`userAccess.${issue}`) : null" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '@/app/stores/session.store'
import { pageDefinitions } from '@/platform/auth/page-access'
import { hasScope } from '@/platform/auth/permissions'
import type { CurrentUser } from '@/shared/contracts'
import Button from '@/shared/ui/components/Button.vue'
import MultiSelect from '@/shared/ui/components/MultiSelect.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { operationDefinitions, userAccessIssue, type UserAccessDraft } from '../user-access-form'

const model = defineModel<UserAccessDraft>({ required: true })
const { t } = useI18n()
const session = useSessionStore()
const projectModeId = useId()
const projectSearch = ref('')
const issue = computed(() => userAccessIssue(model.value))
const unknownScopes = computed(() => model.value.scopes.filter(scope => scope !== '*' && !operationDefinitions.some(o => o.id === scope)))
const projectOptions = computed(() => {
  const projects = session.bootstrap?.visible_projects ?? []
  const result = projects.map(p => ({
    label: projects.filter(other => other.display_name === p.display_name).length > 1 ? `${p.display_name} (${p.project_id})` : p.display_name || p.project_id,
    value: p.project_id,
  }))
  for (const id of model.value.projectIds) if (!result.some(p => p.value === id)) result.push({ label: id, value: id })
  const query = projectSearch.value.toLocaleLowerCase()
  return result.filter(p => model.value.projectIds.includes(p.value) || `${p.label} ${p.value}`.toLocaleLowerCase().includes(query))
})
function customizePages(): void {
  const user = { scopes: model.value.scopes } as CurrentUser
  model.value.pages = pageDefinitions.filter(page => page.scopes.every(scope => hasScope(user, scope))).map(page => page.id)
}
function toggleAll(event: Event): void {
  model.value.scopes = (event.target as HTMLInputElement).checked ? ['*'] : []
}
</script>

<style scoped>
.user-access-form { display: grid; gap: var(--am-space-lg); }
details, fieldset { border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); padding: var(--am-space-md); min-width: 0; }
.checkbox-field input { accent-color: var(--am-action-primary); }
summary, legend { font-weight: 600; color: var(--am-text); }
summary { cursor: pointer; margin-bottom: var(--am-space-sm); }
.access-checks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--am-space-sm); margin-block: var(--am-space-sm); }
.access-group-actions, .access-compatibility { display: flex; align-items: center; gap: var(--am-space-sm); margin-bottom: var(--am-space-sm); flex-wrap: wrap; }
.access-hint { color: var(--am-text-muted); font-size: 12px; margin: 8px 0 0; }
@media (max-width: 640px) { .access-checks { grid-template-columns: 1fr; } }
</style>
