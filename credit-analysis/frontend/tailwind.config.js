/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: "#0D2137",
        "navy-light": "#1E3A5F",
        blue: {
          600: "#1565C0",
          500: "#1976D2",
          100: "#EBF3FF",
        },
        accent: "#F4A93C",
        success: "#027A48",
        danger: "#B42318",
      },
      fontFamily: {
        sans: ["DM Sans", "system-ui", "sans-serif"],
        mono: ["DM Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
