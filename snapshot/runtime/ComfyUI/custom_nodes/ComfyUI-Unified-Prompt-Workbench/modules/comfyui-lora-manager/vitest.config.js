import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  resolve: {
    alias: {
      '/extensions/ComfyUI-Unified-Prompt-Workbench': fileURLToPath(new URL('../../web', import.meta.url))
    }
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['tests/frontend/setup.js'],
    include: [
      'tests/frontend/**/*.test.js',
      'tests/frontend/**/*.test.ts'
    ],
    coverage: {
      enabled: process.env.VITEST_COVERAGE === 'true',
      provider: 'v8',
      reporter: ['text', 'lcov', 'json-summary'],
      reportsDirectory: 'coverage/frontend'
    }
  }
});
