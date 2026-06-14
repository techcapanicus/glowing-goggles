<script setup>
import { ref } from 'vue'

const props = defineProps({
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  initialToken: { type: String, default: '' },
})

const emit = defineEmits(['connect'])

const token = ref(props.initialToken)
const show = ref(false)

function submit () {
  if (token.value.trim()) emit('connect', token.value.trim())
}
</script>

<template>
  <v-container class="fill-height">
    <v-row
      justify="center"
      align="center"
    >
      <v-col
        cols="12"
        sm="8"
        md="6"
        lg="5"
      >
        <v-card
          class="pa-2"
          elevation="4"
        >
          <v-card-item>
            <div class="d-flex align-center mb-1">
              <v-icon
                icon="mdi-rocket-launch-outline"
                color="primary"
                size="32"
                class="mr-3"
              />
              <div>
                <v-card-title class="pa-0">
                  Connect to Semaphore
                </v-card-title>
                <v-card-subtitle class="pa-0">
                  My Country Mobile · CI/CD
                </v-card-subtitle>
              </div>
            </div>
          </v-card-item>

          <v-card-text>
            <p class="text-body-2 text-medium-emphasis mb-4">
              Paste a Semaphore API token (Bearer). Create one in Semaphore under
              your user settings → API Tokens. It is stored only in this browser.
            </p>

            <v-text-field
              v-model="token"
              :type="show ? 'text' : 'password'"
              label="API token"
              prepend-inner-icon="mdi-key-variant"
              :append-inner-icon="show ? 'mdi-eye-off' : 'mdi-eye'"
              variant="outlined"
              autofocus
              @click:append-inner="show = !show"
              @keyup.enter="submit"
            />

            <v-alert
              v-if="error"
              type="error"
              variant="tonal"
              density="compact"
              class="mt-2"
              :text="error"
            />
          </v-card-text>

          <v-card-actions class="px-4 pb-4">
            <v-spacer />
            <v-btn
              color="primary"
              variant="flat"
              size="large"
              :loading="loading"
              :disabled="!token.trim()"
              prepend-icon="mdi-login-variant"
              @click="submit"
            >
              Connect
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>
