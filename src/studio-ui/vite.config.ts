import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  const studioApiPort = env.VITE_STATEBUS_STUDIO_PORT || "50080";
  const studioUiPort = Number(env.VITE_STATEBUS_STUDIO_UI_PORT || "50173");
  return {
    plugins: [react()],
    server: {
      port: studioUiPort,
      proxy: {
        "/api": `http://127.0.0.1:${studioApiPort}`,
      },
    },
    build: {
      target: "es2022",
      sourcemap: true,
    },
  };
});
