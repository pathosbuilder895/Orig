export {};

declare module 'vitest' {
  interface Assertion {
    toHaveNoViolations(): void;
  }
}
