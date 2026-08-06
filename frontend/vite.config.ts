import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The API is same-origin in dev, so the frontend never needs to know the
    // backend's port and CORS stays a dev-only concern. 8000 is a crowded
    // default on a dev machine — override with FINEPRINT_API_PORT if 8001 is
    // taken too.
    proxy: {
      "/api": `http://localhost:${process.env.FINEPRINT_API_PORT ?? 8001}`,
    },
  },
});
