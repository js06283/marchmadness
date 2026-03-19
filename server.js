import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";

const { Pool } = pg;

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PORT = Number(process.env.PORT || 3000);
const DATABASE_URL = process.env.DATABASE_URL;

if (!DATABASE_URL) {
  throw new Error("DATABASE_URL is required.");
}

const pool = new Pool({
  connectionString: DATABASE_URL,
  ssl: process.env.PGSSLMODE === "disable" ? false : { rejectUnauthorized: false },
});

const app = express();
app.use(express.json({ limit: "1mb" }));

function validateFieldKey(fieldKey) {
  return /^[0-9]{4}-[a-z]+$/.test(fieldKey);
}

function validateResultsBody(results) {
  return Boolean(results && typeof results === "object" && typeof results.fieldKey === "string");
}

async function ensureSchema() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS ground_truth (
      field_key TEXT PRIMARY KEY,
      results_json JSONB NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);
}

app.get("/api/health", async (_request, response) => {
  await pool.query("SELECT 1");
  response.json({ ok: true });
});

app.get("/api/ground-truth/:fieldKey", async (request, response) => {
  const { fieldKey } = request.params;
  if (!validateFieldKey(fieldKey)) {
    response.status(400).json({ error: "Invalid field key." });
    return;
  }

  const result = await pool.query(
    "SELECT results_json, updated_at FROM ground_truth WHERE field_key = $1",
    [fieldKey],
  );

  if (result.rowCount === 0) {
    response.status(404).json({ error: "Ground truth not found." });
    return;
  }

  response.json({
    fieldKey,
    results: result.rows[0].results_json,
    updatedAt: result.rows[0].updated_at,
  });
});

app.put("/api/ground-truth/:fieldKey", async (request, response) => {
  const { fieldKey } = request.params;
  const { results } = request.body || {};

  if (!validateFieldKey(fieldKey)) {
    response.status(400).json({ error: "Invalid field key." });
    return;
  }
  if (!validateResultsBody(results) || results.fieldKey !== fieldKey) {
    response.status(400).json({ error: "Results body is invalid or fieldKey does not match." });
    return;
  }

  const result = await pool.query(
    `
      INSERT INTO ground_truth (field_key, results_json, updated_at)
      VALUES ($1, $2::jsonb, NOW())
      ON CONFLICT (field_key)
      DO UPDATE SET results_json = EXCLUDED.results_json, updated_at = NOW()
      RETURNING updated_at
    `,
    [fieldKey, JSON.stringify(results)],
  );

  response.json({
    ok: true,
    fieldKey,
    updatedAt: result.rows[0].updated_at,
  });
});

app.use("/site_data", express.static(path.join(__dirname, "site_data")));
app.use("/site", express.static(path.join(__dirname, "site")));
app.get("/", (_request, response) => {
  response.redirect("/site/");
});

await ensureSchema();
app.listen(PORT, () => {
  console.log(`Listening on ${PORT}`);
});
