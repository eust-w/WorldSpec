import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1280, height: 720 },
    screenshot: "only-on-failure",
  },
  webServer: {
    command:
      "cd ../.. && cargo run --quiet -p worldspec-cli --offline -- compile --input examples/minimal-cube/world.json --target-profile examples/minimal-cube/target-profile-threejs.json --build-intent examples/minimal-cube/build-intent.json --output-dir /tmp/worldspec-threejs-playwright --schema-dir schemas/0.1 && cd web/threejs-preview && BUNDLE_DIR=/tmp/worldspec-threejs-playwright node server.mjs",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
