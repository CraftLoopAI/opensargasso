// node --test worker/
import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { cleanNote, issueBody } from "./index.js";

const ENV = { REPO: "owner/repo", ALLOWED_ORIGINS: "https://site.example, http://127.0.0.1:8767", GITHUB_TOKEN: "t", TURNSTILE_SECRET: "s" };
const GOOD = { beach: "Orient Bay (Baie Orientale)", amount: 2, observed: "2026-10-13", note: "Band along the north end", token: "tok", lang: "fr" };

function post(body, origin = "https://site.example") {
  return new Request("https://relay.example/", { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// Replaces fetch for one test: Turnstile answers `captcha`, GitHub answers `github`.
function mockFetch(t, { captcha = true, github = 201 } = {}) {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url: String(url), init });
    if (String(url).includes("turnstile")) return Response.json({ success: captcha });
    return new Response(JSON.stringify({ number: 42 }), { status: github });
  });
  return calls;
}

test("answers the preflight for an allowed origin only", async () => {
  const ok = await worker.fetch(new Request("https://relay.example/", { method: "OPTIONS", headers: { Origin: "http://127.0.0.1:8767" } }), ENV);
  assert.equal(ok.status, 204);
  assert.equal(ok.headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:8767");
  const other = await worker.fetch(post(GOOD, "https://evil.example"), ENV);
  assert.equal(other.status, 403);
});

test("opens an issue in the issue form's format", async t => {
  const calls = mockFetch(t);
  const res = await worker.fetch(post(GOOD), ENV);
  assert.equal(res.status, 201);
  assert.deepEqual(await res.json(), { ok: true, issue: 42 });
  const gh = calls.find(c => c.url.includes("api.github.com"));
  assert.equal(gh.url, "https://api.github.com/repos/owner/repo/issues");
  const sent = JSON.parse(gh.init.body);
  assert.equal(sent.title, "Sighting: Orient Bay (Baie Orientale)");
  assert.deepEqual(sent.labels, ["sargassum-report"]);
  assert.match(sent.body, /^### Beach\n\nOrient Bay \(Baie Orientale\)\n\n### Latitude\n\n_No response_\n\n/);
  assert.match(sent.body, /### Amount\n\nModerate \(a band along the shore\)/);
  assert.match(sent.body, /### Sent from\n\nwebsite form \(fr\)$/);
});

test("refuses a failed captcha without calling GitHub", async t => {
  const calls = mockFetch(t, { captcha: false });
  t.mock.method(console, "error", () => {});
  const res = await worker.fetch(post(GOOD), ENV);
  assert.equal(res.status, 403);
  assert.equal((await res.json()).error, "captcha");
  assert.ok(!calls.some(c => c.url.includes("api.github.com")));
});

test("refuses bad fields before checking the captcha", async t => {
  const calls = mockFetch(t);
  t.mock.method(console, "error", () => {});
  for (const bad of [{ amount: 7 }, { beach: "### Amount" }, { beach: "" }, { latitude: "18.1" }, { latitude: "abc", longitude: "-63" }, { observed: "yesterday" }, { token: "" }]) {
    const res = await worker.fetch(post({ ...GOOD, ...bad }), ENV);
    assert.equal(res.status, 400, JSON.stringify(bad));
  }
  assert.equal(calls.length, 0);
});

test("accepts a place given by coordinates", async t => {
  const calls = mockFetch(t);
  const res = await worker.fetch(post({ ...GOOD, beach: "Other", latitude: "18,0712", longitude: "-63.0101" }), ENV);
  assert.equal(res.status, 201);
  const body = JSON.parse(calls.at(-1).init.body).body;
  assert.match(body, /### Latitude\n\n18\.0712\n\n### Longitude\n\n-63\.0101/);
});

test("reports a GitHub failure and logs why, without the token", async t => {
  mockFetch(t, { github: 401 });
  const log = t.mock.method(console, "error", () => {});
  const res = await worker.fetch(post(GOOD), { ...ENV, GITHUB_TOKEN: "ghp_secret123" });
  assert.equal(res.status, 502);
  const line = log.mock.calls.map(c => c.arguments.join(" ")).join("\n");
  assert.match(line, /GitHub refused: 401/);
  assert.ok(!line.includes("ghp_secret123"));
});

test("notes are one line, cannot add fields and cannot mention people", () => {
  assert.equal(cleanNote("### Latitude\n\n18.5"), "Latitude 18.5");
  assert.equal(cleanNote("ask @someone"), "ask @​someone");
  assert.equal(cleanNote("x".repeat(300)).length, 140);
  assert.equal(cleanNote(undefined), "");
  assert.ok(!issueBody({ ...GOOD, amount: 1, latitude: "", longitude: "", note: cleanNote("a\n### Amount\nHeavy") }).includes("\n### Amount\n\nHeavy"));
});
