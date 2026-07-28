import { createHash } from "node:crypto";
import { readFile, realpath, lstat, mkdir, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { arch, platform } from "node:os";
import { dirname, isAbsolute, join, resolve, sep } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const previewDirectory = dirname(fileURLToPath(import.meta.url));
const threePackage = JSON.parse(
  await readFile(join(previewDirectory, "node_modules/three/package.json"), "utf8"),
);

function parseArguments() {
  const result = {};
  for (let index = 2; index < process.argv.length; index += 2) {
    const key = process.argv[index];
    const value = process.argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) throw new Error("invalid arguments");
    result[key.slice(2)] = value;
  }
  for (const required of ["bundle", "target-profile", "output"]) {
    if (!result[required]) throw new Error(`--${required} is required`);
  }
  return result;
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function digest(payload) {
  return `sha256:${createHash("sha256").update(payload).digest("hex")}`;
}

function artifactRef(id, logicalPath, payload, mediaType, role) {
  return {
    id,
    digest: digest(payload),
    mediaType,
    path: logicalPath,
    sizeBytes: payload.length,
    role,
  };
}

function diagnostic(code, message) {
  return { code, severity: "error", message };
}

function testResult(id, result, evidenceArtifacts, metrics = {}, diagnostics = []) {
  return {
    id,
    version: "0.1.0",
    result,
    metrics,
    tolerances: {},
    evidenceArtifacts,
    diagnostics,
  };
}

function summarize(tests) {
  const summary = {
    passed: tests.filter((test) => test.result === "pass").length,
    failed: tests.filter((test) => test.result === "fail").length,
    unknown: tests.filter((test) => test.result === "unknown").length,
    notRun: tests.filter((test) => test.result === "not_run").length,
  };
  summary.overall =
    summary.failed > 0
      ? "fail"
      : summary.unknown > 0 || summary.notRun > 0
        ? "incomplete"
        : "pass";
  return summary;
}

async function freePort() {
  return await new Promise((accept, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => (error ? reject(error) : accept(port)));
    });
  });
}

async function waitForServer(url, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The process may still be starting.
    }
    await new Promise((accept) => setTimeout(accept, 100));
  }
  throw new Error(`preview server did not become ready: ${url}`);
}

async function verifyArtifacts(bundle, artifacts) {
  const resolvedBundle = await realpath(bundle);
  const errors = [];
  for (const artifact of artifacts) {
    if (isAbsolute(artifact.path) || artifact.path.split(/[\\/]/).includes("..")) {
      errors.push(`${artifact.id}: unsafe path`);
      continue;
    }
    const joined = join(resolvedBundle, artifact.path);
    try {
      const metadata = await lstat(joined);
      if (metadata.isSymbolicLink()) throw new Error("symlink is forbidden");
      const resolved = await realpath(joined);
      if (resolved !== resolvedBundle && !resolved.startsWith(`${resolvedBundle}${sep}`)) {
        throw new Error("path escapes bundle");
      }
      const payload = await readFile(resolved);
      if (digest(payload) !== artifact.digest || payload.length !== artifact.sizeBytes) {
        throw new Error("digest or size mismatch");
      }
    } catch (error) {
      errors.push(`${artifact.id}: ${String(error)}`);
    }
  }
  return errors;
}

async function main() {
  const arguments_ = parseArguments();
  const bundle = await realpath(resolve(arguments_.bundle));
  const manifest = JSON.parse(await readFile(join(bundle, "build-manifest.json"), "utf8"));
  const target = JSON.parse(await readFile(resolve(arguments_["target-profile"]), "utf8"));
  if (target.target !== "threejs") throw new Error("TargetProfile.target must be threejs");
  const manifestDigest = digest(Buffer.from(canonical(manifest)));
  const targetDigest = digest(Buffer.from(canonical(target)));
  const runnerDigest = digest(await readFile(fileURLToPath(import.meta.url)));
  const runner = {
    name: "worldspec-threejs-conformance",
    version: "0.1.0",
    digest: runnerDigest,
  };
  const artifactErrors = await verifyArtifacts(bundle, manifest.artifacts);
  const evidenceDirectory = join(bundle, "conformance");
  await mkdir(evidenceDirectory, { recursive: true });
  const evidencePath = "conformance/threejs-evidence.json";
  const screenshotPath = "conformance/threejs-preview.png";
  const actualOs = platform();
  const actualArchitecture = arch();
  let executionEvidence = "not_executed";
  let browserResult = null;
  let browserError = null;
  let screenshot = null;
  let server = null;
  let browser = null;
  try {
    const port = await freePort();
    server = spawn(process.execPath, [join(previewDirectory, "server.mjs")], {
      cwd: previewDirectory,
      env: { ...process.env, BUNDLE_DIR: bundle, PORT: String(port) },
      stdio: ["ignore", "pipe", "pipe"],
    });
    await waitForServer(`http://127.0.0.1:${port}`);
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle" });
    await page.locator("#status").waitFor({ state: "visible" });
    await page.waitForFunction(
      () => window.__WORLDSPEC_PREVIEW__?.ready === true,
      undefined,
      { timeout: 30_000 },
    );
    browserResult = await page.evaluate(() => window.__WORLDSPEC_PREVIEW__);
    screenshot = await page.screenshot({ fullPage: true });
    await writeFile(join(bundle, screenshotPath), screenshot);
    executionEvidence = "executed";
  } catch (error) {
    browserError = String(error);
  } finally {
    if (browser) await browser.close();
    if (server) server.kill("SIGTERM");
  }

  const sceneManifestArtifact = manifest.artifacts.find(
    (artifact) => artifact.path === "scene-manifest.json",
  );
  let sceneManifest = null;
  if (sceneManifestArtifact && !artifactErrors.length) {
    sceneManifest = JSON.parse(await readFile(join(bundle, sceneManifestArtifact.path), "utf8"));
  }
  const evidenceDocument = {
    kind: "worldspec.threejs.conformance-evidence",
    specVersion: "0.1.0",
    buildManifestDigest: manifestDigest,
    targetProfileDigest: targetDigest,
    runner,
    host: {
      os: actualOs,
      architecture: actualArchitecture,
      node: process.version,
      three: threePackage.version,
    },
    artifactErrors,
    browserResult,
    browserError,
  };
  const evidencePayload = Buffer.from(canonical(evidenceDocument));
  await writeFile(join(bundle, evidencePath), evidencePayload);
  const evidence = artifactRef(
    "artifact://conformance/threejs/evidence",
    evidencePath,
    evidencePayload,
    "application/vnd.worldspec.conformance-evidence+json",
    "conformance_evidence",
  );
  const evidenceArtifacts = [evidence];
  if (screenshot) {
    evidenceArtifacts.push(
      artifactRef(
        "artifact://conformance/threejs/screenshot",
        screenshotPath,
        screenshot,
        "image/png",
        "conformance_screenshot",
      ),
    );
  }

  const tests = [
    testResult(
      "test://worldspec/artifact-integrity",
      artifactErrors.length ? "fail" : "pass",
      [evidence],
      { artifactCount: manifest.artifacts.length },
      artifactErrors.map((message) => diagnostic("ARTIFACT_INTEGRITY_FAILED", message)),
    ),
  ];
  const environmentMatches =
    actualOs === String(target.platform.os).toLowerCase() &&
    actualArchitecture === String(target.platform.architecture).toLowerCase() &&
    threePackage.version === target.runtimeVersion;
  tests.push(
    testResult(
      "test://worldspec/profile-environment",
      environmentMatches ? "pass" : "fail",
      [evidence],
      {
        expectedOs: target.platform.os,
        actualOs,
        expectedArchitecture: target.platform.architecture,
        actualArchitecture,
        expectedRuntimeVersion: target.runtimeVersion,
        actualRuntimeVersion: threePackage.version,
      },
      environmentMatches
        ? []
        : [
            diagnostic(
              "TARGET_PROFILE_ENVIRONMENT_MISMATCH",
              "actual OS, architecture, or Three.js version differs from TargetProfile",
            ),
          ],
    ),
  );
  const browserPassed =
    executionEvidence === "executed" &&
    browserResult?.ready === true &&
    String(browserResult?.renderer).includes("WebGL");
  const coordinatePassed =
    browserPassed &&
    sceneManifest?.coordinateMapping?.source?.up === "+Z" &&
    sceneManifest?.coordinateMapping?.source?.forward === "+X" &&
    sceneManifest?.coordinateMapping?.target?.up === "+Y" &&
    sceneManifest?.coordinateMapping?.target?.forward === "-Z" &&
    sceneManifest?.coordinateMapping?.rootRotationXDegrees === -90 &&
    browserResult?.bounds?.size?.every(Number.isFinite);
  const known = {
    "test://worldspec/browser-load": testResult(
      "test://worldspec/browser-load",
      browserPassed ? "pass" : executionEvidence === "executed" ? "fail" : "not_run",
      evidenceArtifacts,
      browserResult || {},
      browserPassed
        ? []
        : [diagnostic("THREEJS_BROWSER_LOAD_FAILED", browserError || "preview was not ready")],
    ),
    "test://worldspec/coordinate-mapping": testResult(
      "test://worldspec/coordinate-mapping",
      coordinatePassed ? "pass" : executionEvidence === "executed" ? "fail" : "not_run",
      evidenceArtifacts,
      {
        coordinateMapping: sceneManifest?.coordinateMapping || null,
        bounds: browserResult?.bounds || null,
      },
      coordinatePassed
        ? []
        : [
            diagnostic(
              "THREEJS_COORDINATE_MAPPING_FAILED",
              "canonical +Z/+X mapping or finite rendered bounds were not verified",
            ),
          ],
    ),
  };
  for (const required of target.certificationTests) {
    tests.push(
      known[required] ||
        testResult(required, "not_run", [evidence], {}, [
          diagnostic(
            "CONFORMANCE_TEST_UNIMPLEMENTED",
            "the Three.js v0.1 runner does not implement this test",
          ),
        ]),
    );
  }
  const report = {
    id: `conformance://local/threejs/${manifestDigest.slice("sha256:".length)}`,
    reportVersion: "0.1.0",
    buildManifestDigest: manifestDigest,
    targetProfileDigest: targetDigest,
    target: "threejs",
    executionEvidence,
    runner,
    environment: {
      os: actualOs,
      architecture: actualArchitecture,
      runtime: "threejs",
      runtimeVersion: threePackage.version,
      hardware: browserResult?.renderer || "unknown",
    },
    testedArtifacts: manifest.artifacts,
    tests,
    summary: summarize(tests),
    generatedAt: new Date().toISOString(),
  };
  const output = resolve(arguments_.output);
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify(report.summary));
  process.exitCode = report.summary.overall === "pass" ? 0 : 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 2;
});
