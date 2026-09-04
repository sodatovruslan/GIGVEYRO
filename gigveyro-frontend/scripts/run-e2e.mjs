import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const candidates = process.platform === "win32"
  ? [resolve(root, "GIGVEYRO_Backend/.venv/Scripts/python.exe"), "python"]
  : [resolve(root, "GIGVEYRO_Backend/.venv/bin/python"), "python3", "python"];
const python = candidates.find((candidate) => !candidate.includes("/") && !candidate.includes("\\") || existsSync(candidate));
if (!python) throw new Error("Python is required for the disposable E2E harness");

const result = spawnSync(
  python,
  [resolve(root, "GIGVEYRO_Backend/scripts/run_playwright_e2e.py"), ...process.argv.slice(2)],
  { cwd: resolve(root, "gigveyro-frontend"), stdio: "inherit", env: process.env },
);
process.exit(result.status ?? 1);
