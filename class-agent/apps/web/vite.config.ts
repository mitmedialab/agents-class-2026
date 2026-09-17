import basicSsl from "@vitejs/plugin-basic-ssl";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  envDir: "../..",
  plugins: [react(), basicSsl()],
  build: {
    rollupOptions: {
      output: {
        assetFileNames: (asset) =>
          asset.names.some((name) => name.endsWith(".mjs"))
            ? "assets/[name]-[hash].js"
            : "assets/[name]-[hash][extname]",
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
