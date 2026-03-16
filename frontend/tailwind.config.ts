import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#111111",
        honey: "#f4b400",
        oat: "#f7f1e3",
        ember: "#b95c2e",
        pine: "#204038",
      },
      boxShadow: {
        panel: "0 18px 60px rgba(17, 17, 17, 0.10)",
      },
      borderRadius: {
        "4xl": "2rem",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
      },
    },
  },
  plugins: [],
};

export default config;
