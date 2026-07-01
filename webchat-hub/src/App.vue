<script setup>
import { computed, onMounted, ref } from 'vue'
import { useTheme } from 'vuetify'
import {
  expertflow,
  ExpertFlowError,
  mapBotChannels,
  mapWebchats,
} from './api/expertflow'
import ConnectCard from './components/ConnectCard.vue'
import CustomBotTester from './components/CustomBotTester.vue'
import WebchatCard from './components/WebchatCard.vue'
import WebchatPanel from './components/WebchatPanel.vue'

const STORAGE_KEY = 'webchat-hub.session'

const theme = useTheme()

const connected = ref(false)
const connecting = ref(false)
const connectError = ref('')
const loading = ref(false)

const tenantInput = ref('efcx4.expertflow.com')
const username = ref('admin')
const password = ref('admin')
const tenantBase = ref('')
const token = ref('')
const tenantId = ref('efcx4')

const bots = ref([])
const botsWithChannels = ref([])
const webchats = ref([])
const selectedWebchat = ref(null)
const selectedBot = ref(null)
const activeTab = ref('webchats')
const botFilter = ref('')

const snackbar = ref(false)
const snackbarText = ref('')

const filteredBots = computed(() => {
  const q = botFilter.value.trim().toLowerCase()
  if (!q) return botsWithChannels.value
  return botsWithChannels.value.filter((b) =>
    b.botName?.toLowerCase().includes(q) ||
    b.botType?.toLowerCase().includes(q) ||
    b.botUri?.toLowerCase().includes(q),
  )
})

const webBotCount = computed(() => webchats.value.length)
const customBots = computed(() =>
  botsWithChannels.value.filter((b) => b.botType === 'CUSTOM'),
)

function notify (text) {
  snackbarText.value = text
  snackbar.value = true
}

function saveSession () {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    tenantInput: tenantInput.value,
    username: username.value,
    tenantBase: tenantBase.value,
    token: token.value,
    tenantId: tenantId.value,
  }))
}

function clearSession () {
  localStorage.removeItem(STORAGE_KEY)
}

async function loadData () {
  loading.value = true
  try {
    const [botList, widgets, channels] = await Promise.all([
      expertflow.getBots(tenantBase.value, token.value, tenantId.value),
      expertflow.getWidgets(tenantBase.value),
      expertflow.getChannels(tenantBase.value, token.value),
    ])
    bots.value = Array.isArray(botList) ? botList : []
    webchats.value = mapWebchats(
      Array.isArray(widgets) ? widgets : [],
      Array.isArray(channels) ? channels : [],
      bots.value,
    )
    botsWithChannels.value = mapBotChannels(bots.value, channels)
    if (webchats.value.length && !selectedWebchat.value) {
      selectedWebchat.value = webchats.value[0]
    }
  } catch (err) {
    notify(err instanceof ExpertFlowError ? err.message : err.message)
  } finally {
    loading.value = false
  }
}

async function connect ({ tenant, username: user, password: pass }) {
  connecting.value = true
  connectError.value = ''
  try {
    const result = await expertflow.login(tenant, user, pass)
    token.value = result.token
    tenantBase.value = result.tenantBase
    tenantInput.value = tenant.replace(/^https?:\/\//, '')
    username.value = user
    password.value = pass
    tenantId.value = tenantInput.value.split('.')[0] || 'efcx4'
    connected.value = true
    saveSession()
    await loadData()
  } catch (err) {
    connectError.value = err instanceof ExpertFlowError ? err.message : err.message
  } finally {
    connecting.value = false
  }
}

function disconnect () {
  connected.value = false
  token.value = ''
  tenantBase.value = ''
  bots.value = []
  botsWithChannels.value = []
  webchats.value = []
  selectedWebchat.value = null
  selectedBot.value = null
  clearSession()
}

function openWebchat (entry) {
  selectedWebchat.value = entry
  activeTab.value = 'webchats'
}

function openBotWebchat (bot) {
  const match = webchats.value.find((w) => w.botId === bot.botId)
  if (match) {
    selectedWebchat.value = match
    activeTab.value = 'webchats'
  } else {
    selectedBot.value = bot
    activeTab.value = 'bots'
    notify(`No web widget mapped to ${bot.botName}`)
  }
}

function selectBot (bot) {
  selectedBot.value = bot
}

function channelIcon (type) {
  const map = {
    WEB: 'mdi-web',
    WHATSAPP: 'mdi-whatsapp',
    FACEBOOK: 'mdi-facebook',
    INSTAGRAM: 'mdi-instagram',
    TWITTER: 'mdi-twitter',
    LINKEDIN: 'mdi-linkedin',
    CX_VOICE: 'mdi-phone',
    WEB_RTC: 'mdi-video',
  }
  return map[type] || 'mdi-access-point'
}

function toggleTheme () {
  theme.global.name.value =
    theme.global.name.value === 'webchatDark' ? 'webchatLight' : 'webchatDark'
}

onMounted(async () => {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    if (saved?.token && saved?.tenantBase) {
      tenantInput.value = saved.tenantInput || tenantInput.value
      username.value = saved.username || username.value
      tenantBase.value = saved.tenantBase
      token.value = saved.token
      tenantId.value = saved.tenantId || tenantId.value
      connected.value = true
      await loadData()
    }
  } catch {
    clearSession()
  }
})
</script>

<template>
  <v-app>
    <template v-if="!connected">
      <v-main>
        <ConnectCard
          v-model:tenant="tenantInput"
          v-model:username="username"
          v-model:password="password"
          :loading="connecting"
          :error="connectError"
          @connect="connect"
        />
      </v-main>
    </template>

    <template v-else>
      <v-app-bar
        color="primary"
        flat
      >
        <v-app-bar-title class="d-flex align-center">
          <v-icon
            icon="mdi-chat-processing-outline"
            class="mr-2"
          />
          ExpertFlow Webchat Hub
        </v-app-bar-title>
        <v-chip
          variant="flat"
          color="white"
          class="mr-2"
          prepend-icon="mdi-domain"
        >
          {{ tenantInput }}
        </v-chip>
        <template #append>
          <v-btn
            icon="mdi-refresh"
            variant="text"
            title="Refresh"
            :loading="loading"
            @click="loadData"
          />
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
        width="300"
      >
        <v-tabs
          v-model="activeTab"
          direction="vertical"
          color="primary"
          class="mt-2"
        >
          <v-tab value="webchats">
            <v-icon
              icon="mdi-chat"
              start
            />
            Webchats ({{ webBotCount }})
          </v-tab>
          <v-tab value="bots">
            <v-icon
              icon="mdi-robot-outline"
              start
            />
            All Bots ({{ bots.length }})
          </v-tab>
        </v-tabs>

        <v-divider class="my-2" />

        <v-window v-model="activeTab">
          <v-window-item value="webchats">
            <v-list
              density="compact"
              nav
            >
              <v-list-item
                v-for="entry in webchats"
                :key="entry.id + entry.widgetIdentifier"
                :active="selectedWebchat?.id === entry.id && selectedWebchat?.widgetIdentifier === entry.widgetIdentifier"
                :title="entry.title"
                :subtitle="entry.bot?.botName || 'No bot'"
                prepend-icon="mdi-chat-outline"
                @click="openWebchat(entry)"
              />
              <v-list-item
                v-if="!webchats.length && !loading"
                title="No web widgets found"
                disabled
              />
            </v-list>
          </v-window-item>

          <v-window-item value="bots">
            <v-text-field
              v-model="botFilter"
              density="compact"
              hide-details
              placeholder="Filter bots..."
              prepend-inner-icon="mdi-magnify"
              class="px-3 pt-2"
              variant="outlined"
            />
            <v-list
              density="compact"
              nav
              class="bot-list"
            >
              <v-list-item
                v-for="bot in filteredBots"
                :key="bot.botId"
                :active="selectedBot?.botId === bot.botId"
                :title="bot.botName"
                :subtitle="bot.botType"
                prepend-icon="mdi-robot-outline"
                @click="selectBot(bot)"
              >
                <template #append>
                  <v-btn
                    v-if="webchats.some(w => w.botId === bot.botId)"
                    icon="mdi-chat"
                    size="x-small"
                    variant="text"
                    title="Open webchat"
                    @click.stop="openBotWebchat(bot)"
                  />
                </template>
              </v-list-item>
            </v-list>
          </v-window-item>
        </v-window>
      </v-navigation-drawer>

      <v-main>
        <v-container
          fluid
          class="pa-4"
        >
          <v-window v-model="activeTab">
            <v-window-item value="webchats">
              <v-row>
                <v-col
                  cols="12"
                  lg="4"
                  class="d-none d-lg-flex flex-column ga-3"
                >
                  <WebchatCard
                    v-for="entry in webchats"
                    :key="entry.id + entry.widgetIdentifier"
                    :entry="entry"
                    :tenant-base="tenantBase"
                    :active="selectedWebchat?.widgetIdentifier === entry.widgetIdentifier"
                    @open="openWebchat"
                  />
                </v-col>
                <v-col
                  cols="12"
                  lg="8"
                >
                  <WebchatPanel
                    :entry="selectedWebchat"
                    :tenant-base="tenantBase"
                  />
                </v-col>
              </v-row>
            </v-window-item>

            <v-window-item value="bots">
              <v-row v-if="selectedBot">
                <v-col
                  cols="12"
                  md="5"
                >
                  <v-card variant="outlined">
                    <v-card-title>{{ selectedBot.botName }}</v-card-title>
                    <v-card-subtitle>{{ selectedBot.botType }}</v-card-subtitle>
                    <v-card-text>
                      <div class="text-caption text-medium-emphasis mb-1">
                        Bot URI
                      </div>
                      <code class="d-block mb-4 text-wrap">{{ selectedBot.botUri }}</code>

                      <div class="text-subtitle-2 mb-2">
                        Channel bindings
                      </div>
                      <v-list
                        v-if="selectedBot.channels?.length"
                        density="compact"
                      >
                        <v-list-item
                          v-for="ch in selectedBot.channels"
                          :key="ch.id"
                          :prepend-icon="channelIcon(ch.type)"
                          :title="ch.name"
                          :subtitle="`${ch.type} · ${ch.serviceIdentifier}`"
                        >
                          <template
                            v-if="ch.isWeb"
                            #append
                          >
                            <v-btn
                              size="small"
                              color="primary"
                              variant="tonal"
                              @click="openBotWebchat(selectedBot)"
                            >
                              Chat
                            </v-btn>
                          </template>
                        </v-list-item>
                      </v-list>
                      <p
                        v-else
                        class="text-medium-emphasis"
                      >
                        Not bound to any channel.
                      </p>
                    </v-card-text>
                  </v-card>
                </v-col>
                <v-col
                  cols="12"
                  md="7"
                >
                  <CustomBotTester
                    v-if="selectedBot.botType === 'CUSTOM'"
                    :bot="selectedBot"
                  />
                  <v-card
                    v-else-if="webchats.some(w => w.botId === selectedBot.botId)"
                    variant="outlined"
                  >
                    <v-card-text class="text-center pa-8">
                      <v-icon
                        icon="mdi-chat"
                        size="48"
                        color="primary"
                        class="mb-3"
                      />
                      <p>This RASA bot is available via web widget.</p>
                      <v-btn
                        color="primary"
                        @click="openBotWebchat(selectedBot)"
                      >
                        Open webchat
                      </v-btn>
                    </v-card-text>
                  </v-card>
                  <v-card
                    v-else
                    variant="outlined"
                  >
                    <v-card-text class="text-medium-emphasis pa-6">
                      <v-icon
                        icon="mdi-information-outline"
                        class="mr-2"
                      />
                      This {{ selectedBot.botType }} bot has no web widget. It may be
                      reachable via voice or social channels listed on the left, or
                      directly at its bot URI for RASA endpoints.
                    </v-card-text>
                  </v-card>
                </v-col>
              </v-row>

              <v-card
                v-else
                variant="outlined"
                class="pa-8 text-center text-medium-emphasis"
              >
                <v-icon
                  icon="mdi-robot-outline"
                  size="64"
                  class="mb-4 opacity-50"
                />
                <p class="text-h6">
                  Select a bot
                </p>
                <p>{{ bots.length }} bots · {{ customBots.length }} CUSTOM · {{ webBotCount }} web widgets</p>
              </v-card>
            </v-window-item>
          </v-window>
        </v-container>
      </v-main>
    </template>

    <v-snackbar
      v-model="snackbar"
      timeout="3000"
    >
      {{ snackbarText }}
    </v-snackbar>
  </v-app>
</template>

<style scoped>
.bot-list {
  max-height: calc(100vh - 220px);
  overflow-y: auto;
}
code {
  font-size: 12px;
  background: rgba(0, 0, 0, 0.06);
  padding: 8px;
  border-radius: 4px;
}
</style>
