import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api goes to the Spring Boot app; in production the app serves the built files itself.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8080" } },
  build: { outDir: "dist" },
});
