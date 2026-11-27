// Preloaded by bunfig.toml before every `bun test` run.
//
// Bun automatically loads `.env` into process.env, so without this file a
// developer's real owner id, Supabase key and SMTP settings would leak into
// tests. That makes results machine-dependent (56 tests failed locally only
// because PAIRROLE_USER_ID was set) and risks tests reaching live services.
// Tests that need a value must set it explicitly.
import { existsSync, readFileSync } from "node:fs"

const SENSITIVE_PREFIXES = ["PAIRROLE_", "SUPABASE_", "OPENAI_", "DAILY_REPORT_"]

function dotenvKeys(path: string): string[] {
  if (!existsSync(path)) return []
  return readFileSync(path, "utf8")
    .split(/\r?\n/)
    .map((line) => line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=/)?.[1])
    .filter((key): key is string => Boolean(key))
}

const fromDotenv = [".env", ".env.local", ".env.test", ".env.development"].flatMap(dotenvKeys)
for (const key of Object.keys(process.env)) {
  if (fromDotenv.includes(key) || SENSITIVE_PREFIXES.some((prefix) => key.startsWith(prefix))) {
    delete process.env[key]
  }
}
