import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Load environment files (.env, .env.local) from the repository root
// so shared variables like VITE_API_BASE_URL and VITE_POWER_BI_URL are picked up.
// Only variables with the VITE_ prefix are exposed to the client bundle.
export default defineConfig({
  plugins: [react()],
  envDir: '../',
})
