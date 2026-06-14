import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi'

// Semaphore UI uses a Vuetify (Material Design) based interface; we mirror that
// stack here with a light/dark theme pair.
export default createVuetify({
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: { mdi },
  },
  theme: {
    defaultTheme: 'semaphoreLight',
    themes: {
      semaphoreLight: {
        dark: false,
        colors: {
          primary: '#2196F3',
          secondary: '#3F51B5',
          surface: '#FFFFFF',
          background: '#F5F7FA',
        },
      },
      semaphoreDark: {
        dark: true,
        colors: {
          primary: '#64B5F6',
          secondary: '#7986CB',
        },
      },
    },
  },
})
