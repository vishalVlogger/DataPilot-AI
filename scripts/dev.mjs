import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backend = path.join(root, "backend");
const frontend = path.join(root, "frontend");

if (!existsSync(path.join(frontend, "node_modules"))) {
  console.error("Frontend dependencies are missing. Run `npm --prefix frontend install` once, then retry.");
  process.exit(1);
}

console.log("[DataPilot] Applying database migrations...");
const migration = spawnSync("python", ["-m", "alembic", "upgrade", "head"], {
  cwd: backend,
  stdio: "inherit",
});
if (migration.error || migration.status !== 0) {
  console.error("[DataPilot] Database migration failed. Confirm Python dependencies and backend/.env are configured.");
  process.exit(migration.status ?? 1);
}

const services = [
  spawn("python", ["-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"], { cwd: backend, stdio: "inherit", detached: process.platform !== "win32" }),
  spawn("npm", ["run", "dev"], { cwd: frontend, stdio: "inherit", shell: process.platform === "win32", detached: process.platform !== "win32" }),
];

console.log("[DataPilot] Frontend: http://localhost:3000");
console.log("[DataPilot] Backend:  http://localhost:8000/docs");

let stopping = false;
function stop(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  for (const service of services) {
    if (!service.pid || service.killed) continue;
    if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(service.pid), "/T", "/F"], { stdio: "ignore" });
    else {
      try { process.kill(-service.pid, "SIGTERM"); } catch { /* The service already stopped. */ }
    }
  }
  setTimeout(() => process.exit(exitCode), 500).unref();
}

for (const service of services) {
  service.on("error", (error) => {
    console.error(`[DataPilot] Unable to start a development service: ${error.message}`);
    stop(1);
  });
  service.on("exit", (code, signal) => {
    if (!stopping) {
      console.error(`[DataPilot] A development service stopped (${signal ?? `exit ${code ?? 1}`}).`);
      stop(code ?? 1);
    }
  });
}

process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));
