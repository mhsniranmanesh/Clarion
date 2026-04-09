import fs from "node:fs";
import path from "node:path";
import type { ProjectContext } from "../types.js";

const DEFAULT_CONTEXT_FILES = [
  "CLAUDE.md",
  "README.md",
  "package.json",
];

export function loadProjectContext(
  projectDir: string,
  contextFiles: string[] = DEFAULT_CONTEXT_FILES,
): ProjectContext {
  const projectName = path.basename(projectDir);
  const files: ProjectContext["files"] = [];

  for (const file of contextFiles) {
    const filePath = path.resolve(projectDir, file);
    if (fs.existsSync(filePath)) {
      const content = fs.readFileSync(filePath, "utf-8");
      // Limit each file to ~2000 chars to keep context lean
      files.push({
        path: file,
        content: content.slice(0, 2000),
      });
    }
  }

  return { projectName, files };
}
