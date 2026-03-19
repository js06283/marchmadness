import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const ROOT = __dirname;
const FINAL_OUTPUT_DIR = path.join(ROOT, "final_output");
const SITE_DATA_DIR = path.join(ROOT, "site_data");
const SITE_DATA_FILE = path.join(SITE_DATA_DIR, "brackets.json");

function loadJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function fieldKey(year, gender) {
  return `${year}-${gender}`;
}

function inferGroupName(filePath, brackets) {
  const stem = path.basename(filePath, ".json");
  if (stem.startsWith("brackets-gpt-")) {
    return "GPT";
  }
  if (stem.startsWith("brackets-heuristic-")) {
    const parts = stem.split("-");
    if (parts.length >= 6) {
      const tagParts = parts.slice(4, -1);
      if (tagParts.length) {
        return tagParts.join(" ").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
      }
    }
    return "Heuristic";
  }

  const generator = brackets[0]?.generator;
  if (generator === "gpt") {
    return "GPT";
  }
  if (generator === "heuristic") {
    return "Heuristic";
  }
  return path.basename(filePath);
}

function normalizeBracket(bracket, fileName, bracketIndex) {
  return {
    id: `${fileName}::bracket-${bracketIndex}`,
    file_name: fileName,
    index: bracketIndex,
    title: bracket.title || `Bracket ${bracketIndex}`,
    generator: bracket.generator || "unknown",
    year: bracket.year,
    gender: bracket.gender,
    champion: bracket.champion,
    runner_up: bracket.runner_up,
    final_four: bracket.final_four || [],
    summary: bracket.summary || "",
    regions: bracket.regions || {},
    raw: bracket,
  };
}

function loadFields() {
  const fields = {};
  for (const fileName of fs.readdirSync(ROOT).sort()) {
    if (!/^field-.*\.json$/.test(fileName)) {
      continue;
    }
    const data = loadJson(path.join(ROOT, fileName));
    if (typeof data.year === "number" && typeof data.gender === "string") {
      fields[fieldKey(data.year, data.gender)] = data;
    }
  }
  return fields;
}

function buildPayload() {
  const fields = loadFields();
  const files = [];

  for (const fileName of fs.existsSync(FINAL_OUTPUT_DIR) ? fs.readdirSync(FINAL_OUTPUT_DIR).sort() : []) {
    if (!fileName.endsWith(".json")) {
      continue;
    }
    const filePath = path.join(FINAL_OUTPUT_DIR, fileName);
    const data = loadJson(filePath);
    if (!Array.isArray(data)) {
      continue;
    }

    const brackets = data
      .filter((item) => item && typeof item === "object" && !Array.isArray(item))
      .map((item, index) => normalizeBracket(item, fileName, index + 1));
    if (!brackets.length) {
      continue;
    }

    const first = brackets[0];
    files.push({
      file_name: fileName,
      group_name: inferGroupName(filePath, brackets),
      path: filePath,
      year: first.year,
      gender: first.gender,
      generator: first.generator,
      count: brackets.length,
      field_key: fieldKey(first.year, first.gender),
      brackets,
    });
  }

  return {
    generated_at: new Date().toISOString(),
    files,
    fields,
  };
}

fs.mkdirSync(SITE_DATA_DIR, { recursive: true });
fs.writeFileSync(SITE_DATA_FILE, `${JSON.stringify(buildPayload(), null, 2)}\n`, "utf8");
console.log(`Wrote ${SITE_DATA_FILE}`);
