// Sighting relay: takes a report from the website form, checks the Turnstile captcha
// and opens the same GitHub issue as the sighting issue form. A maintainer approves it
// with the `report-approved` label, as for any other sighting.
//
// Variables (wrangler.toml): REPO ("owner/repo"), ALLOWED_ORIGINS (comma separated).
// Secrets (npx wrangler secret put ...): GITHUB_TOKEN, TURNSTILE_SECRET.

// Answers as the issue form writes them, so pipeline/reports.py reads both the same way.
export const AMOUNTS = ["None (beach is clear)", "Light (scattered clumps)", "Moderate (a band along the shore)", "Heavy (thick mats)"];
const NOTE_MAX = 140;           // the issue form's limit
const BODY_MAX = 4000;          // bytes of JSON accepted from the form
const VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request, env);
    if (!cors) return json({ ok: false, error: "origin" }, 403);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (request.method !== "POST") return json({ ok: false, error: "method" }, 405, cors);

    const text = await request.text();
    if (text.length > BODY_MAX) return json({ ok: false, error: "invalid" }, 413, cors);
    let report;
    try {
      report = clean(JSON.parse(text));
    } catch (e) {
      console.error("refused field:", e.message);   // visible with `npx wrangler tail`
      return json({ ok: false, error: "invalid", detail: e.message }, 400, cors);
    }

    const verify = await fetch(VERIFY_URL, {
      method: "POST",
      body: new URLSearchParams({ secret: env.TURNSTILE_SECRET, response: report.token, remoteip: request.headers.get("CF-Connecting-IP") || "" }),
    }).then(r => r.json()).catch(() => ({ success: false }));
    if (!verify.success) {
      console.error("Turnstile refused:", (verify["error-codes"] || []).join(", ") || "no answer");
      return json({ ok: false, error: "captcha" }, 403, cors);
    }

    const res = await fetch(`https://api.github.com/repos/${env.REPO}/issues`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "opensargasso-report-relay",
      },
      body: JSON.stringify({ title: `Sighting: ${report.beach}`, body: issueBody(report), labels: ["sargassum-report"] }),
    });
    if (!res.ok) {
      // 401 usually means the token expired; 403 or 404 that it lacks access or approval
      console.error("GitHub refused:", res.status, (await res.text().catch(() => "")).slice(0, 300));
      return json({ ok: false, error: "server" }, 502, cors);
    }
    const issue = await res.json();
    return json({ ok: true, issue: issue.number }, 201, cors);
  },
};

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin") || "";
  const allowed = (env.ALLOWED_ORIGINS || "").split(",").map(s => s.trim()).filter(Boolean);
  if (!allowed.includes(origin)) return null;
  return { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST, OPTIONS",
           "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400", Vary: "Origin" };
}

function json(data, status, headers = {}) {
  return new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json" } });
}

/* Check every field and turn it into plain, single-line text. Throws with the reason.
   The pipeline validates the location and date again when the report is approved. */
export function clean(input) {
  const str = v => (typeof v === "string" ? v : v == null ? "" : String(v)).trim();
  const beach = str(input.beach);
  if (!/^[\p{L}\p{N} '’().,/-]{1,80}$/u.test(beach)) throw new Error("beach");
  const amount = Number(input.amount);
  if (!Number.isInteger(amount) || !AMOUNTS[amount]) throw new Error("amount");
  const coord = (v, max) => {
    const s = str(v).replace(",", ".");
    if (!s) return "";
    const x = Number(s);
    if (!/^-?\d{1,3}(\.\d{1,10})?$/.test(s) || Math.abs(x) > max) throw new Error("coordinates");
    return s;
  };
  const latitude = coord(input.latitude, 90), longitude = coord(input.longitude, 180);
  if (!latitude !== !longitude) throw new Error("coordinates");
  const observed = str(input.observed);
  if (observed && !/^\d{4}-\d{2}-\d{2}$/.test(observed)) throw new Error("date");
  const token = str(input.token);
  if (!token || token.length > 2048) throw new Error("captcha");
  return { beach, amount, latitude, longitude, observed, note: cleanNote(input.note), lang: /^(en|fr|nl)$/.test(str(input.lang)) ? str(input.lang) : "", token };
}

/* One line, no heading marks (a note starting with ### would add a field to the issue)
   and no @mentions (they would notify GitHub users). */
export function cleanNote(v) {
  return String(v == null ? "" : v)
    .replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim()
    .replace(/^#+\s*/, "").replace(/@/g, "@​")
    .slice(0, NOTE_MAX).trim();
}

/* The issue body exactly as GitHub renders the sighting issue form. */
export function issueBody(r) {
  const answer = v => v || "_No response_";
  return [
    ["Beach", r.beach], ["Latitude", answer(r.latitude)], ["Longitude", answer(r.longitude)],
    ["Amount", AMOUNTS[r.amount]], ["Observed on", answer(r.observed)], ["Note", answer(r.note)],
    ["Sent from", "website form" + (r.lang ? ` (${r.lang})` : "")],
  ].map(([label, value]) => `### ${label}\n\n${value}`).join("\n\n");
}
