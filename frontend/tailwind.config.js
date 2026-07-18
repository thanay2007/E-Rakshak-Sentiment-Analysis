/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        base: {
          950: "rgba(var(--color-base-950), <alpha-value>)",
          900: "rgba(var(--color-base-900), <alpha-value>)",
          800: "rgba(var(--color-base-800), <alpha-value>)",
          700: "rgba(var(--color-base-700), <alpha-value>)",
          600: "rgba(var(--color-base-600), <alpha-value>)",
        },
        slate: {
          100: "rgba(var(--color-slate-200), <alpha-value>)",
          200: "rgba(var(--color-slate-200), <alpha-value>)",
          300: "rgba(var(--color-slate-300), <alpha-value>)",
          400: "rgba(var(--color-slate-400), <alpha-value>)",
          500: "rgba(var(--color-slate-500), <alpha-value>)",
          600: "rgba(var(--color-slate-600), <alpha-value>)",
          700: "rgba(var(--color-slate-700), <alpha-value>)",
          800: "rgba(var(--color-slate-800), <alpha-value>)",
          900: "rgba(var(--color-slate-900), <alpha-value>)",
        },
        white: "rgba(var(--color-white), <alpha-value>)",
        black: "rgba(var(--color-black), <alpha-value>)",
        accent: {
          DEFAULT: "rgba(var(--color-accent), <alpha-value>)",
          dim: "rgba(var(--color-accent-dim), <alpha-value>)",
          glow: "rgba(var(--color-accent-glow), <alpha-value>)",
        },
        threat: {
          critical: "rgba(var(--color-threat-critical), <alpha-value>)",
          inflammatory: "rgba(var(--color-threat-inflammatory), <alpha-value>)",
          fake: "rgba(var(--color-threat-fake), <alpha-value>)",
          neutral: "rgba(var(--color-threat-neutral), <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        scan: "scan 9s linear infinite",
        "spin-slow": "spin 14s linear infinite",
      },
      keyframes: {
        scan: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100vh)" },
        },
      },
    },
  },
  plugins: [],
};
