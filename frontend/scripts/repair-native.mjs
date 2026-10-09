// Restore platform binaries that have gone missing from node_modules.
//
// This repo lives under OneDrive, which deletes .node/.exe files inside
// node_modules without any error. npm does not notice: the package folder and
// its package.json are still there, only the binary is gone. Vite then dies with
// "Cannot find native binding" or "Cannot find module ...rollup.win32-x64-msvc.node".
//
// A platform package (one with an `os`/`cpu` field, such as @rollup/rollup-win32-x64-msvc
// or @esbuild/win32-x64) is broken when its `main` file is missing, or, with no
// `main`, when nothing but docs is left in it. Each broken one is re-downloaded
// at the exact version installed and unpacked over its folder in place, so a
// nested copy is restored where it lives rather than hoisted to the top level.
//
// Usage:  node scripts/repair-native.mjs            check, and repair what is broken
//         node scripts/repair-native.mjs --check    check only; exit 1 if anything is broken

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const checkOnly = process.argv.includes("--check");
const DOCS = /^(package\.json|readme.*|license.*|changelog.*)$/i;

// npm's own rules: a list matches if it names this value, or only excludes others.
function matches(list, value) {
  if (!list || list.length === 0) return true;
  if (list.includes(value)) return true;
  return list.every((v) => v.startsWith("!")) && !list.includes(`!${value}`);
}

function* packageDirs(nodeModules) {
  let entries;
  try { entries = fs.readdirSync(nodeModules); } catch { return; }
  for (const name of entries) {
    if (name.startsWith(".")) continue;
    const dir = path.join(nodeModules, name);
    if (name.startsWith("@")) {
      for (const sub of fs.readdirSync(dir)) {
        yield path.join(dir, sub);
        yield* packageDirs(path.join(dir, sub, "node_modules"));
      }
    } else {
      yield dir;
      yield* packageDirs(path.join(dir, "node_modules"));
    }
  }
}

function isBroken(dir, pkg) {
  if (pkg.main) return !fs.existsSync(path.join(dir, pkg.main));
  return fs.readdirSync(dir).every((f) => DOCS.test(f));
}

const broken = [];
for (const dir of packageDirs(path.join(root, "node_modules"))) {
  let pkg;
  try { pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8")); } catch { continue; }
  if (!pkg.os && !pkg.cpu) continue;
  if (!matches(pkg.os, process.platform) || !matches(pkg.cpu, process.arch)) continue;
  if (isBroken(dir, pkg)) broken.push({ dir, spec: `${pkg.name}@${pkg.version}` });
}

if (broken.length === 0) {
  console.log("    all platform binaries present");
  process.exit(0);
}
console.log("    broken: " + broken.map((b) => b.spec).join(", "));
if (checkOnly) process.exit(1);

// npm is a batch file on Windows, which execFileSync can only run through a shell.
const shell = process.platform === "win32";
let failed = 0;
for (const { dir, spec } of broken) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "repair-native-"));
  try {
    console.log(`    restoring ${spec}`);
    const tgz = execFileSync("npm", ["pack", spec, "--silent", "--pack-destination", tmp],
      { cwd: tmp, shell, encoding: "utf8" }).trim().split(/\r?\n/).pop();
    // Relative names on purpose: GNU tar (Git Bash puts it ahead of Windows'
    // own on PATH) reads the "C:" in an absolute path as a remote host name.
    execFileSync("tar", ["-xzf", tgz], { cwd: tmp });
    fs.cpSync(path.join(tmp, "package"), dir, { recursive: true, force: true });
  } catch (err) {
    failed += 1;
    console.error(`    could not restore ${spec}: ${err.message}`);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

const still = broken.filter(({ dir }) => {
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
  return isBroken(dir, pkg);
});
if (failed || still.length) {
  console.error("    still broken: " + still.map((b) => b.spec).join(", "));
  process.exit(1);
}
console.log("    repaired; all platform binaries present");
