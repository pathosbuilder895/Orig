/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["DM Sans", "system-ui", "sans-serif"],
        serif: ['"Source Serif 4"', "Georgia", "serif"],
      },
      colors: {
        ink: {
          950: "#0c1222",
          900: "#141c2c",
          800: "#1e2a3f",
          700: "#2a3a52",
        },
        paper: {
          50: "#faf8f5",
          100: "#f3efe8",
          200: "#e8e0d4",
        },
        accent: {
          DEFAULT: "#1e4d7b",
          muted: "#3d6a94",
          fg: "#e8f0f8",
        },
      },
      boxShadow: {
        card: "0 1px 3px rgba(12, 18, 34, 0.06), 0 8px 24px rgba(12, 18, 34, 0.06)",
        lift: "0 4px 24px rgba(12, 18, 34, 0.08)",
      },
    },
  },
  plugins: [],
};
