/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          50: "#eef3f9",
          100: "#d8e3f0",
          600: "#274a77",
          700: "#1a3a5c",
          800: "#12283f",
          900: "#0b1b2c",
        },
        success: "#1c7c3c",
        danger: "#b3261e",
        warn: "#8a6d00",
        pending: "#6b7280",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
    },
  },
  plugins: [],
};
