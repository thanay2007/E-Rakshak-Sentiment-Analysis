/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: {
          950: "#070A12",
          900: "#0A0E1A",
          800: "#0F1420",
          700: "#151B2C",
          600: "#1C2438",
        },
        accent: {
          DEFAULT: "#14B8C4",
          dim: "#0E7C85",
          glow: "#3DDCE8",
        },
        threat: {
          critical: "#EF4444",
          inflammatory: "#F59E0B",
          fake: "#A855F7",
          neutral: "#10B981",
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
