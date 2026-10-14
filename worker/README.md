# Sighting relay

The website's sighting form posts here. The Worker checks the Cloudflare Turnstile captcha, validates the report and opens the same GitHub issue as the sighting issue form, labeled `sargassum-report`. A maintainer approves it with `report-approved` as usual, and `.github/workflows/report.yml` publishes it. Reporters need no GitHub account.

Until the relay is set up, the site shows the GitHub issue form button instead.

## Before you start

- **Node.js**, a current or long-term support version, for `npx wrangler`.
- **A free Cloudflare account.** The free plan allows 100,000 Worker requests a day, and Turnstile is free.
- **Which GitHub account opens the issues.** Every website report appears on GitHub as opened by the account that owns the token. To keep your personal name off them, create a separate free GitHub account for the relay, give it write access to the repository, and make the token from that account.

## Set it up

1. **Turnstile.** In the Cloudflare dashboard, open Turnstile and add a widget:
   - Widget name: any label you will recognize in the dashboard, for example `OpenSargasso sightings`. Visitors do not see it.
   - Hostnames: the host the site is served from, without `https://` or a path. With GitHub Pages' default address, `https://craftloopai.github.io/opensargasso/`, that is `craftloopai.github.io`. Once Pages is enabled, confirm the address under the repository's Settings, Pages; if you give the site its own domain, use that domain here and in `ALLOWED_ORIGINS`.
   - Widget mode: **Managed**. Visitors see a checkbox only when Cloudflare is unsure about them.

   Note the site key and the secret key.
2. **GitHub token.** Signed in as the account that will open the issues, go to GitHub, Settings, Developer settings, Personal access tokens, Fine-grained tokens, and generate a new token:
   - Resource owner `CraftLoopAI`; repository access: only `opensargasso`.
   - Permissions: **Issues: read and write**. GitHub adds read access to metadata itself.
   - Expiration: the default is 30 days. Choose the longest the organization allows, and put the expiry date in your calendar (see [Renewing the token](#renewing-the-token)).

   If the CraftLoopAI organization requires approval for fine-grained tokens, the token stays pending until an organization owner approves it (organization Settings, Personal access tokens, Pending requests). The account needs write access to the repository, or GitHub drops the `sargassum-report` label from new issues and approving them publishes nothing.
3. **Deploy**, from this folder:
   ```bash
   npx wrangler login                          # opens the browser to sign in to Cloudflare
   npx wrangler secret put GITHUB_TOKEN        # paste the token
   npx wrangler secret put TURNSTILE_SECRET    # paste the Turnstile secret key
   npx wrangler deploy
   ```
   On your first deploy, Wrangler asks you to choose a `workers.dev` subdomain for your Cloudflare account. It then prints the Worker's address, for example `https://opensargasso-report.<subdomain>.workers.dev`.
4. **Site.** In `site/config.js`, set `report.endpoint` to that address and `report.turnstileSiteKey` to the Turnstile site key.
5. **Check.** Send a test report from the site. An issue titled "Sighting: ..." should appear with the `sargassum-report` label. Close it without approving. If it does not appear, see [When something goes wrong](#when-something-goes-wrong).

`ALLOWED_ORIGINS` in `wrangler.toml` lists the sites that may post, as the browser sends them: scheme and host (and port, if any), without a path or trailing slash. For the default Pages address that is `https://craftloopai.github.io`, not `https://craftloopai.github.io/opensargasso/`. If the site moves to its own domain, put it there and in the Turnstile widget's hostnames, then deploy again.

## Renewing the token

When the token expires, every report fails with "The report could not be sent". Before the expiry date:

1. Create a new token the same way.
2. From this folder, run `npx wrangler secret put GITHUB_TOKEN` and paste it. It takes effect right away; no new deploy is needed.
3. Delete the old token on GitHub.

## Testing locally

Run the Worker on your computer against a test repository, so test reports do not land in the real one.

1. In this folder, create `.dev.vars` (git ignores it) with test values. These override `wrangler.toml` while testing:
   ```
   REPO=your-name/a-test-repository
   GITHUB_TOKEN=a token for that repository
   TURNSTILE_SECRET=1x0000000000000000000000000000000AA
   ALLOWED_ORIGINS=http://localhost:8000
   ```
   The Turnstile secret above is Cloudflare's test key that always passes.
2. Run `npx wrangler dev`. The Worker answers at `http://localhost:8787`.
3. In another terminal, from the repository root, run `python -m http.server 8000 --directory site`.
4. In `site/config.js`, set `report.endpoint` to `http://localhost:8787` and `report.turnstileSiteKey` to `1x00000000000000000000AA`, the test site key that always passes. Undo this before committing.
5. Open `http://localhost:8000`, send a report, and check the test repository's issues.

## When something goes wrong

Run `npx wrangler tail` in this folder and send a report: it shows each request live, with the reason when GitHub or Turnstile refuses.

| What the form says | Likely cause |
|---|---|
| The report could not be sent | The token expired, was not approved by the organization, or lost access (the log shows GitHub's answer); or the page's address is missing from `ALLOWED_ORIGINS` (the browser console mentions CORS); or `report.endpoint` in `site/config.js` is wrong |
| The spam check failed | The Turnstile secret does not belong to the site key, or the site's hostname is not in the widget's list |
| The spam check could not load | The browser blocks `challenges.cloudflare.com`, for example through a content blocker |
| Part of the report was not accepted | A field failed the relay's checks; the log shows which |

An issue that appears without the `sargassum-report` label means the token's account has no write access to the repository.

## What it accepts

Beach name, or Other with latitude and longitude; amount 0 to 3; observed date as YYYY-MM-DD or empty; a note of up to 140 characters, made one line, without heading marks or @mentions. The pipeline checks the location and the date again when the report is approved (`pipeline/reports.py`).

## Privacy

Approved reports, including the note, are public. Turnstile and the Worker run on Cloudflare, which sees the reporter's IP address; the Worker does not store anything, and its log shows only why a request failed. The issue is opened by the token's account, so reporters stay anonymous on GitHub.

## Tests

```bash
node --test worker/
```
