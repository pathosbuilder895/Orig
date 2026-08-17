import { defineConfig, mergeConfig } from 'vitest/config';
import { defineConfig as defineViteConfig } from 'vite';
import react from '@vitejs/plugin-react';

const viteConfig = defineViteConfig({
  plugins: [react()],
});

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      globals: true,
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html', 'lcov'],
        reportsDirectory: './coverage',
        include: ['src/**/*.{ts,tsx}'],
        // No `thresholds` here on purpose: this config makes coverage
        // MEASURABLE. Picking an enforced CI floor is a separate decision.
        exclude: [
          '**/*.test.{ts,tsx}', // test files themselves
          '**/*.d.ts', // type-only declarations (incl. src/api/schema.d.ts, generated)
          'src/test/**', // test setup/harness
          'src/main.tsx', // entry bootstrap — createRoot().render() only
        ],
      },
    },
  }),
);
