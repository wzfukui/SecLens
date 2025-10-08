import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  root: resolve(__dirname, "."),
  build: {
    outDir: resolve(__dirname, "../app/static/dist"),
    emptyOutDir: false,
    sourcemap: true,
    rollupOptions: {
      input: resolve(__dirname, "src/main.ts"),
      output: {
        entryFileNames: "bundle.js",
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith(".css")) {
            return "bundle.css";
          }
          return "[name][extname]";
        },
        chunkFileNames: "chunks/[name].js"
      }
    }
  },
  publicDir: resolve(__dirname, "public"),
  resolve: {
    alias: {
      "@": resolve(__dirname, "src")
    }
  }
});
