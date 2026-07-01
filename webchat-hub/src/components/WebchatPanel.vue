<script setup>
import { ref, watch } from 'vue'
import { buildWidgetIframeUrl, buildWidgetScript } from '../api/expertflow'

const props = defineProps({
  entry: { type: Object, default: null },
  tenantBase: { type: String, required: true },
})

const iframeUrl = ref('')
const embedScript = ref('')
const copied = ref(false)

watch(
  () => props.entry,
  (entry) => {
    copied.value = false
    if (!entry?.serviceIdentifier || !entry?.widgetIdentifier) {
      iframeUrl.value = ''
      embedScript.value = ''
      return
    }
    iframeUrl.value = buildWidgetIframeUrl(
      props.tenantBase,
      entry.widgetIdentifier,
      entry.serviceIdentifier,
    )
    embedScript.value = buildWidgetScript(
      props.tenantBase,
      entry.widgetIdentifier,
      entry.serviceIdentifier,
    )
  },
  { immediate: true },
)

async function copyScript () {
  await navigator.clipboard.writeText(embedScript.value)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

function openStandalone () {
  if (iframeUrl.value) window.open(iframeUrl.value, '_blank')
}
</script>

<template>
  <v-card
    v-if="entry"
    variant="flat"
    class="chat-panel fill-height d-flex flex-column"
  >
    <v-toolbar
      density="compact"
      color="primary"
    >
      <v-toolbar-title class="text-subtitle-1">
        {{ entry.title }}
        <span class="text-caption ml-2 opacity-80">{{ entry.widgetIdentifier }}</span>
      </v-toolbar-title>
      <template #append>
        <v-btn
          icon="mdi-content-copy"
          variant="text"
          title="Copy embed script"
          @click="copyScript"
        />
        <v-btn
          icon="mdi-open-in-new"
          variant="text"
          title="Open in new tab"
          @click="openStandalone"
        />
      </template>
    </v-toolbar>

    <v-snackbar
      :model-value="copied"
      timeout="1500"
      location="top"
      color="success"
    >
      Embed script copied
    </v-snackbar>

    <div
      v-if="entry.bot"
      class="px-4 py-2 bg-surface-variant text-caption d-flex align-center ga-2"
    >
      <v-icon
        icon="mdi-robot-outline"
        size="small"
      />
      Bot: <strong>{{ entry.bot.botName }}</strong>
      <v-chip
        size="x-small"
        variant="tonal"
      >
        {{ entry.bot.botType }}
      </v-chip>
    </div>

    <div
      v-if="!entry.serviceIdentifier"
      class="pa-8 text-center text-medium-emphasis"
    >
      <v-icon
        icon="mdi-alert-circle-outline"
        size="48"
        class="mb-2"
      />
      <p>No WEB channel service identifier mapped to this widget.</p>
    </div>

    <iframe
      v-else
      :key="iframeUrl"
      :src="iframeUrl"
      class="chat-iframe flex-grow-1"
      title="ExpertFlow webchat"
      allow="microphone; camera"
    />
  </v-card>

  <v-card
    v-else
    variant="outlined"
    class="fill-height d-flex align-center justify-center text-medium-emphasis"
  >
    <div class="text-center pa-8">
      <v-icon
        icon="mdi-chat-outline"
        size="64"
        class="mb-4 opacity-50"
      />
      <p class="text-h6">
        Select a webchat
      </p>
      <p>Choose a widget from the list to start chatting with its bot.</p>
    </div>
  </v-card>
</template>

<style scoped>
.chat-panel {
  min-height: 520px;
  overflow: hidden;
}
.chat-iframe {
  border: none;
  width: 100%;
  min-height: 480px;
  background: #f5f5f5;
}
</style>
