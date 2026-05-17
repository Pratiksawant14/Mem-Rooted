/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
    "./lib/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "#0a0a0f",
        surface: "#111118",
        "surface-elevated": "#1a1a24",
        border: "#2a2a3a",
        primary: "#7c6af7",
        "primary-hover": "#8d7df8",
        "primary-glow": "rgba(124,106,247,0.25)",
        "primary-dim": "rgba(124,106,247,0.13)",
        "text-primary": "#f0f0ff",
        "text-secondary": "#8888aa",
        "text-muted": "#55556a",
        anchor: "#f7c96a",
        domain: "#6af7c9",
        cluster: "#6aaff7",
        instance: "#a06af7",
        "decay-healthy": "#6af77a",
        "decay-warning": "#f7d06a",
        "decay-critical": "#f76a6a",
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "12px",
        sm: "8px",
        lg: "16px",
      },
    },
  },
  plugins: [],
};
