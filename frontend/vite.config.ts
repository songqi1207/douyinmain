import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/business/",
  plugins: [
    {
      name: "business-base-trailing-slash",
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          const rawUrl = (request as { url?: string }).url || "";
          if (rawUrl === "/business" || rawUrl.indexOf("/business?") === 0) {
            response.statusCode = 307;
            response.setHeader("Location", rawUrl.replace(/^\/business/, "/business/"));
            response.end();
            return;
          }
          next();
        });
      },
    },
    react(),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000"
    }
  }
});
