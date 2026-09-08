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
        // Ratchet, not aspiration: set from the measured floor of the
        // 2026-08 branch-coverage effort (part 7). Raise when real coverage
        // rises; never lower to admit a regression.
        thresholds: {
          branches: 100,
          statements: 99, // measured 99.07% (214/216) on 2026-08-20
          functions: 96, // measured 96.29% (52/54) on 2026-08-20
          lines: 98, // measured 98.96% (192/194) on 2026-08-20
        },
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
