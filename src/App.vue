<script setup>
import { computed, onMounted, ref } from 'vue'
import { useTheme } from 'vuetify'
import { semaphore, SemaphoreError } from './api/semaphore'
import ConnectCard from './components/ConnectCard.vue'
import StatusChip from './components/StatusChip.vue'

const STORAGE_KEY = 'semaphore.token'
const envToken = import.meta.env.VITE_SEMAPHORE_TOKEN || ''

const theme = useTheme()

const token = ref('')
const connected = ref(false)
const connecting = ref(false)
const connectError = ref('')
const user = ref(null)

const projects = ref([])
const selectedProjectId = ref(null)
const templates = ref([])
const tasks = ref([])
const loadingProjects = ref(false)
const loadingDetail = ref(false)

const runDialog = ref(false)
const runTarget = ref(null)
const running = ref(false)

const snackbar = ref(false)
const snackbarText = ref('')
const snackbarColor = ref('primary')

const selectedProject = computed(() =>
  projects.value.find((p) => p.id === selectedProjectId.value) || null,
)

function notify (text, color = 'primary') {
  snackbarText.value = text
  snackbarColor.value = color
  snackbar.value = true
}

function templateName (id) {
  const t = templates.value.find((tpl) => tpl.id === id)
  return t ? t.name : `#${id}`
}

function formatDate (value) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString()
}

async function connect (apiToken) {
  connecting.value = true
  connectError.value = ''
  try {
    const me = await semaphore.getUser(apiToken)
    token.value = apiToken
    user.value = me
    connected.value = true
    localStorage.setItem(STORAGE_KEY, apiToken)
    await loadProjects()
  } catch (err) {
    connectError.value =
      err instanceof SemaphoreError ? err.message : `Failed to connect: ${err.message}`
  } finally {
    connecting.value = false
  }
}

function disconnect () {
  connected.value = false
  token.value = ''
  user.value = null
  projects.value = []
  templates.value = []
  tasks.value = []
  selectedProjectId.value = null
  localStorage.removeItem(STORAGE_KEY)
}

async function loadProjects () {
  loadingProjects.value = true
  try {
    const list = await semaphore.getProjects(token.value)
    projects.value = Array.isArray(list) ? list : []
    if (projects.value.length && !selectedProjectId.value) {
      await selectProject(projects.value[0].id)
    }
  } catch (err) {
    notify(err.message, 'error')
  } finally {
    loadingProjects.value = false
  }
}

async function selectProject (id) {
  selectedProjectId.value = id
  loadingDetail.value = true
  templates.value = []
  tasks.value = []
  try {
    const [tpls, tsk] = await Promise.all([
      semaphore.getTemplates(token.value, id),
      semaphore.getTasks(token.value, id),
    ])
    templates.value = Array.isArray(tpls) ? tpls : []
    tasks.value = Array.isArray(tsk) ? tsk : []
  } catch (err) {
    notify(err.message, 'error')
  } finally {
    loadingDetail.value = false
  }
}

function askRun (template) {
  runTarget.value = template
  runDialog.value = true
}

async function confirmRun () {
  if (!runTarget.value) return
  running.value = true
  try {
    await semaphore.runTask(token.value, selectedProjectId.value, runTarget.value.id)
    notify(`Started "${runTarget.value.name}"`, 'success')
    runDialog.value = false
    await selectProject(selectedProjectId.value)
  } catch (err) {
    notify(err.message, 'error')
  } finally {
    running.value = false
  }
}

function toggleTheme () {
  theme.global.name.value =
    theme.global.name.value === 'semaphoreDark' ? 'semaphoreLight' : 'semaphoreDark'
}

onMounted(() => {
  const saved = localStorage.getItem(STORAGE_KEY) || envToken
  if (saved) connect(saved)
})
</script>

<template>
  <v-app>
    <template v-if="!connected">
      <v-main>
        <ConnectCard
          :loading="connecting"
          :error="connectError"
          :initial-token="envToken"
          @connect="connect"
        />
      </v-main>
    </template>

    <template v-else>
      <v-app-bar
        color="primary"
        flat
      >
        <v-app-bar-title>
          <v-icon
            icon="mdi-rocket-launch-outline"
            class="mr-2"
          />
          MyCountry Semaphore
        </v-app-bar-title>
        <template #append>
          <v-chip
            v-if="user"
            variant="flat"
            color="white"
            class="mr-2"
            prepend-icon="mdi-account"
          >
            {{ user.name || user.username }}
          </v-chip>
          <v-btn
            :icon="theme.global.current.value.dark ? 'mdi-weather-sunny' : 'mdi-weather-night'"
            variant="text"
            @click="toggleTheme"
          />
          <v-btn
            icon="mdi-logout"
            variant="text"
            title="Disconnect"
            @click="disconnect"
          />
        </template>
      </v-app-bar>

      <v-navigation-drawer
        permanent
        width="280"
      >
        <v-list-subheader>PROJECTS</v-list-subheader>
        <v-progress-linear
          v-if="loadingProjects"
          indeterminate
          color="primary"
        />
        <v-list
          v-model:selected="selectedProjectId"
          nav
          density="comfortable"
        >
          <v-list-item
            v-for="project in projects"
            :key="project.id"
            :value="project.id"
            :active="project.id === selectedProjectId"
            prepend-icon="mdi-folder-outline"
            :title="project.name"
            @click="selectProject(project.id)"
          />
          <v-list-item
            v-if="!loadingProjects && !projects.length"
            title="No projects found"
            disabled
          />
        </v-list>
      </v-navigation-drawer>

      <v-main>
        <v-container fluid>
          <div
            v-if="selectedProject"
            class="d-flex align-center mb-4"
          >
            <h2 class="text-h5">
              {{ selectedProject.name }}
            </h2>
            <v-spacer />
            <v-btn
              variant="text"
              prepend-icon="mdi-refresh"
              :loading="loadingDetail"
              @click="selectProject(selectedProjectId)"
            >
              Refresh
            </v-btn>
          </div>

          <v-row>
            <v-col
              cols="12"
              md="6"
            >
              <v-card variant="outlined">
                <v-toolbar
                  density="compact"
                  color="transparent"
                >
                  <v-toolbar-title class="text-subtitle-1">
                    <v-icon
                      icon="mdi-file-document-multiple-outline"
                      class="mr-2"
                      size="small"
                    />
                    Task Templates
                  </v-toolbar-title>
                </v-toolbar>
                <v-divider />
                <v-list lines="two">
                  <v-list-item
                    v-for="tpl in templates"
                    :key="tpl.id"
                    :title="tpl.name"
                    :subtitle="tpl.playbook || tpl.type || ''"
                  >
                    <template #append>
                      <v-btn
                        size="small"
                        color="primary"
                        variant="tonal"
                        prepend-icon="mdi-play"
                        @click="askRun(tpl)"
                      >
                        Run
                      </v-btn>
                    </template>
                  </v-list-item>
                  <v-list-item
                    v-if="!loadingDetail && !templates.length"
                    title="No templates"
                    disabled
                  />
                </v-list>
              </v-card>
            </v-col>

            <v-col
              cols="12"
              md="6"
            >
              <v-card variant="outlined">
                <v-toolbar
                  density="compact"
                  color="transparent"
                >
                  <v-toolbar-title class="text-subtitle-1">
                    <v-icon
                      icon="mdi-history"
                      class="mr-2"
                      size="small"
                    />
                    Recent Tasks
                  </v-toolbar-title>
                </v-toolbar>
                <v-divider />
                <v-list lines="two">
                  <v-list-item
                    v-for="task in tasks"
                    :key="task.id"
                    :title="`#${task.id} · ${templateName(task.template_id)}`"
                    :subtitle="formatDate(task.created)"
                  >
                    <template #append>
                      <StatusChip :status="task.status" />
                    </template>
                  </v-list-item>
                  <v-list-item
                    v-if="!loadingDetail && !tasks.length"
                    title="No tasks yet"
                    disabled
                  />
                </v-list>
              </v-card>
            </v-col>
          </v-row>
        </v-container>
      </v-main>
    </template>

    <v-dialog
      v-model="runDialog"
      max-width="440"
    >
      <v-card>
        <v-card-title>Run task template?</v-card-title>
        <v-card-text>
          This will trigger
          <strong>{{ runTarget && runTarget.name }}</strong>
          in <strong>{{ selectedProject && selectedProject.name }}</strong>.
          This runs a real task on the Semaphore server.
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn
            variant="text"
            @click="runDialog = false"
          >
            Cancel
          </v-btn>
          <v-btn
            color="primary"
            variant="flat"
            :loading="running"
            @click="confirmRun"
          >
            Run now
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar
      v-model="snackbar"
      :color="snackbarColor"
      timeout="3000"
    >
      {{ snackbarText }}
    </v-snackbar>
  </v-app>
</template>
