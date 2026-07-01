<script setup>
import { ref, watch } from 'vue'
import { expertflow } from '../api/expertflow'

const props = defineProps({
  bot: { type: Object, required: true },
})

const message = ref('Hello')
const sessionId = ref(`session-${Date.now()}`)
const loading = ref(false)
const result = ref(null)
const error = ref('')

watch(
  () => props.bot.botId,
  () => {
    result.value = null
    error.value = ''
  },
)

async function send () {
  if (!message.value.trim()) return
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await expertflow.testCustomBot(
      props.bot.botUri,
      message.value,
      sessionId.value,
    )
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <v-card variant="outlined">
    <v-card-title class="text-subtitle-1 d-flex align-center">
      <v-icon
        icon="mdi-flask-outline"
        class="mr-2"
        size="small"
      />
      Test CUSTOM bot webhook
    </v-card-title>
    <v-card-subtitle class="text-truncate">
      {{ bot.botUri }}
    </v-card-subtitle>
    <v-card-text>
      <v-text-field
        v-model="sessionId"
        label="Session ID"
        density="compact"
        class="mb-2"
      />
      <v-textarea
        v-model="message"
        label="Message"
        rows="2"
        auto-grow
        class="mb-2"
      />
      <v-btn
        color="primary"
        :loading="loading"
        prepend-icon="mdi-send"
        @click="send"
      >
        Send test message
      </v-btn>
      <v-alert
        v-if="error"
        type="error"
        variant="tonal"
        class="mt-3"
        density="compact"
      >
        {{ error }}
      </v-alert>
      <v-sheet
        v-if="result"
        class="mt-3 pa-3 rounded"
        color="surface-variant"
      >
        <div class="text-caption mb-1">
          HTTP {{ result.status }}
          <v-chip
            :color="result.ok ? 'success' : 'error'"
            size="x-small"
            class="ml-2"
          >
            {{ result.ok ? 'OK' : 'Error' }}
          </v-chip>
        </div>
        <pre class="response-body">{{ typeof result.body === 'string' ? result.body : JSON.stringify(result.body, null, 2) }}</pre>
      </v-sheet>
    </v-card-text>
  </v-card>
</template>

<style scoped>
.response-body {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  max-height: 240px;
  overflow: auto;
  margin: 0;
}
</style>
