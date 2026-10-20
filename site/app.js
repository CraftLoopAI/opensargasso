(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var state = { lang: "en", day: 0, data: null, reports: [], base: 0, today: -1, sel: null, timer: null,
                map: null, layers: {}, markers: {} };
  var STALE_DAYS = 10, OUTDATED_DAYS = 2, DAY_MS = 864e5, STEP_MS = 900, UNCERTAIN_FROM = 4;  // persistence loses skill after day 3
  var WEEK_DAYS = 7, RECENT_DAYS = 3;  // the satellite composite's days; sightings this recent get the sargassum colors
  var ICON = {
    play: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9.5-5.5z" fill="currentColor"/></svg>',
    pause: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 2.5h3.2v11H3.5zM9.3 2.5h3.2v11H9.3z" fill="currentColor"/></svg>',
    satellite: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round">' +
      '<path d="M8.6 4.4l3 3-4.2 4.2-3-3z"/><path d="M6.8 5.2 4.2 2.6 2.6 4.2l2.6 2.6M10.8 9.2l2.6 2.6-1.6 1.6-2.6-2.6"/><path d="M2 10.5A3.5 3.5 0 0 0 5.5 14" stroke-linecap="round"/></svg>'
  };

  function t(key, v) {
    var s = (window.I18N[state.lang] || window.I18N.en)[key];
    if (typeof s !== "string" || v == null) return s;
    if (typeof v !== "object") v = { n: v };
    return s.replace(/\{(\w+)\}/g, function (m, k) { return k in v ? v[k] : m; });
  }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function fmtDate(iso) { if (!iso || iso === "sample") return "-"; var d = new Date(iso); return isNaN(d) ? iso : d.toLocaleDateString(state.lang, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }); }
  /* Ages are worked out now, in the browser, so they keep counting if the daily update stops. */
  function ageDays(iso) { var t0 = Date.parse(iso); return isNaN(t0) ? null : Math.max(0, Math.floor((Date.now() - t0) / DAY_MS)); }
  function ageSuffix(iso) { var n = ageDays(iso); return n == null ? "" : " (" + ageText(n) + ")"; }
  function expired() { return state.data && state.today > lastDay(); }
  function lastDay() { return state.data ? state.data.forecast.length - 1 : 7; }
  function reduceMotion() { return window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches; }

  /* Day 0 is the date of the satellite composite; day k is k days later. */
  function setDates(d) {
    var x = new Date(d.sources.afai.time);
    if (isNaN(x)) x = new Date(d.generated);
    state.base = Date.UTC(x.getUTCFullYear(), x.getUTCMonth(), x.getUTCDate());
    var now = new Date();
    state.today = Math.round((Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) - state.base) / DAY_MS);
  }
  function inRange(k) { return k >= 0 && k <= lastDay(); }
  function horizon() { return inRange(state.today) ? state.today : 0; }  // first day of "the coming week"
  function shortDay(k) { return fmtDay(k, { weekday: "short", day: "numeric", month: "short" }); }
  function ageText(n) { return n === 1 ? t("dayOld") : t("daysOld", n); }
  /* Files from before the wind forecast have no `fallback` flag: their wind was the constant one. */
  function windText(w) {
    if (!w || w.fallback !== false) return t("windFallback");
    return w.cached ? t("windCached", { d: fmtDate(w.until), f: fmtDate(w.cached) }) : t("windModel", { d: fmtDate(w.until) });  // cached: an earlier run's forecast
  }
  function fmtNum(v) { return v == null ? "?" : Number(v).toLocaleString(state.lang, { maximumFractionDigits: 6 }); }
  function sideName(side) { return (t("side") || {})[side] || side || ""; }
  function bySide(sites) {
    var groups = {}, order = [];
    sites.forEach(function (s) { var g = s.side || ""; if (!groups[g]) { groups[g] = []; order.push(g); } groups[g].push(s); });
    return order.map(function (g) { return { side: g, sites: groups[g] }; });
  }
  /* From today on: today's level, first day at Moderate or more, and the peak. */
  function outlook(s) {
    var from = horizon(), o = { now: s.risk[from], first: -1, peak: 0, peakDay: from };
    for (var k = from; k < s.risk.length; k++) {
      if (o.first < 0 && s.risk[k] >= 2) o.first = k;
      if (s.risk[k] > o.peak) { o.peak = s.risk[k]; o.peakDay = k; }
    }
    return o;
  }
  function fmtDay(k, opts) { opts.timeZone = "UTC"; return new Date(state.base + k * DAY_MS).toLocaleDateString(state.lang, opts); }
  function longDay(k) { return fmtDay(k, { weekday: "long", day: "numeric", month: "long" }); }
  function seenOn(k) { return fmtDay(-k, { day: "numeric", month: "short" }); }  // k days before the image date
  /* A detection's 4th value is how many days before the image date it was seen, or null. */
  function dated() { return !!state.data && state.data.detections.some(function (c) { return c[3] != null; }); }
  function recent(c) { return c[3] != null && c[3] < RECENT_DAYS; }
  function dayNum(k) { return new Date(state.base + k * DAY_MS).getUTCDate(); }

  function pickLang() {
    var saved = null; try { saved = localStorage.getItem("os-lang"); } catch (e) {}
    var nav = (navigator.language || "en").slice(0, 2);
    state.lang = window.I18N[saved] ? saved : window.I18N[nav] ? nav : "en";
  }

  function renderStatic() {
    document.documentElement.lang = state.lang;
    var nav = $("lang"), refocus = nav.contains(document.activeElement); nav.textContent = "";
    Object.keys(window.I18N).forEach(function (code) {
      var b = el("button", null, code.toUpperCase()); b.type = "button"; b.title = window.I18N[code].name;
      b.setAttribute("aria-pressed", code === state.lang ? "true" : "false");
      b.addEventListener("click", function () { state.lang = code; try { localStorage.setItem("os-lang", code); } catch (e) {} renderAll(); });
      nav.appendChild(b);
      if (refocus && code === state.lang) b.focus();
    });
    $("place").textContent = state.data ? state.data.region.name : "";
    $("tagline").textContent = t("tagline");
    $("h-outlook").textContent = t("outlook"); $("outlook-help").textContent = outlookHelp();
    $("h-reports").textContent = t("reports");
    $("h-data").textContent = t("data");
    $("dl-json").textContent = t("json"); $("dl-reports").textContent = t("reportsFile"); $("to-methods").textContent = t("moreMethods");
    Array.prototype.forEach.call($("views").querySelectorAll("a"), function (a) { a.textContent = t("v_" + a.dataset.view); });
    $("views").setAttribute("aria-label", t("viewsLabel"));
    [["m-title", "mTitle"], ["m-intro", "mIntro"], ["m-h-sides", "mSides"], ["m-h-table", "mTable"], ["m-table-help", "mTableHelp"],
     ["csv", "csv"], ["m-h-quality", "mQuality"], ["r-title", "rTitle"], ["r-intro", "rIntro"],
     ["r-h-files", "rFiles"], ["r-h-example", "rExample"], ["r-h-fields", "rFields"], ["r-h-method", "rMethod"],
     ["r-h-sources", "rSources"], ["r-h-run", "rRun"], ["r-h-cite", "rCite"], ["r-h-limits", "rLimits"]]
      .forEach(function (x) { $(x[0]).textContent = t(x[1]); });
    $("footer").textContent = t("footer");
    if ($("map").className === "nomap") $("map").textContent = t("nomap");
    $("days").setAttribute("aria-label", t("dayPicker"));
    $("csv-help").textContent = t("csvHelp", { radius: state.data ? fmtNum(state.data.settings.radius_km) : "?" });
    var repo = (window.OPENSARGASSO || {}).repo || "";
    $("report-btn").href = "https://github.com/" + repo + "/issues/new?template=sargassum-report.yml";
    renderReportForm();
    renderLegend();
  }

  function renderLegend() {
    var lg = $("legend"); lg.textContent = "";
    function item(cls) { var s = el("span", "lg " + (cls || "")); lg.appendChild(s); return s; }
    var sea = item(), ends = el("span", "ends"), split = state.day === 0 && dated();
    sea.appendChild(el("span", null, split ? t("legendRecent", { from: seenOn(RECENT_DAYS - 1), to: seenOn(0) }) : t(state.day === 0 ? "legendSeen" : "legendDrift")));
    ends.appendChild(el("span", null, t("less"))); ends.appendChild(el("i", "ramp")); ends.appendChild(el("span", null, t("more")));
    sea.appendChild(ends);
    if (split) { var old = item(); old.appendChild(el("span", null, t("legendOlder", { from: seenOn(WEEK_DAYS - 1), to: seenOn(RECENT_DAYS) }))); old.appendChild(el("i", "ramp old")); }
    if (state.day > 0) { var ashore = item(); ashore.appendChild(el("i", "dot")); ashore.appendChild(document.createTextNode(t("legendAshore"))); }
    var lv = item(); lv.appendChild(el("span", null, t(fromSir() || !state.data ? "legendBeachSir" : "legendBeachModel")));
    t("levels").forEach(function (name, r) { var s = el("span", "lvl"); s.appendChild(el("i", "chip l" + r)); s.appendChild(document.createTextNode(name)); lv.appendChild(s); });
    if (state.reports.length) { var rp = item(); rp.appendChild(el("i", "diamond")); rp.appendChild(document.createTextNode(t("legendReport"))); }
  }

  /* Beach levels come from NOAA SIR unless the pipeline fell back to the drift model. */
  function sirInfo() { var s = state.data && state.data.sources.sir; return s && s.fallback === false ? s : null; }
  function fromSir() { return !!sirInfo(); }
  function outlookHelp() { var s = sirInfo(); return s ? t("outlookSir", { d: fmtDate(s.date) }) : t("outlookModel"); }
  function unc(k) { return k >= UNCERTAIN_FROM; }

  function renderHeadline() {
    var d = state.data;
    if (!d) { $("headline").textContent = t("title"); return; }
    if (expired()) { $("headline").textContent = t("headlineExpired", { d: fmtDate(d.generated) }); return; }
    var n = d.sites.filter(function (s) { return outlook(s).first >= 0; }).length;
    var noaa = fromSir();
    $("headline").textContent = n ? t(noaa ? "headline" : "headlineModel", { n: n, total: d.sites.length }) : t(noaa ? "headlineNone" : "headlineModelNone");
  }

  function renderNotices() {
    var d = state.data;
    $("sample").hidden = !(d && d.sample); $("sample").textContent = t("sample");
    var age = d ? ageDays(d.sources.afai.time) : null, built = d ? ageDays(d.generated) : null;
    $("stale").hidden = !(age != null && age > STALE_DAYS); $("stale").textContent = t("stale", age);
    $("outdated").hidden = !(built != null && built >= OUTDATED_DAYS && !d.sample);
    $("outdated").textContent = d ? t("outdated", { d: fmtDate(d.generated) }) : "";
  }

  /* ---------- day picker ---------- */
  function renderDays() {
    var strip = $("days"); strip.textContent = "";
    if (!state.data) return;
    var seen = el("span", "grp sat"), fc = el("span", "grp fc", t("forecast"));
    seen.innerHTML = ICON.satellite; seen.appendChild(el("span", "tx", t("seen")));
    [seen, fc].forEach(function (c) { c.setAttribute("aria-hidden", "true"); strip.appendChild(c); });
    for (var k = 0; k <= lastDay(); k++) {
      var b = el("button", [k === state.today ? "today" : "", unc(k) ? "unc" : ""].join(" ").trim() || null); b.type = "button"; b.dataset.day = k;
      b.setAttribute("role", "radio");
      b.setAttribute("aria-label", longDay(k) + ", " + (k === 0 ? t("seen") : t("forecast")) + (k === state.today ? ", " + t("today") : ""));
      b.appendChild(el("span", "wd", fmtDay(k, { weekday: "short" }).replace(/\.$/, "")));
      b.appendChild(el("span", "dn", String(dayNum(k))));
      strip.appendChild(b);
    }
    syncDays();
  }

  function syncDays() {
    Array.prototype.forEach.call($("days").querySelectorAll("button"), function (b) {
      var on = +b.dataset.day === state.day;
      b.setAttribute("aria-checked", on ? "true" : "false"); b.tabIndex = on ? 0 : -1;
    });
  }

  function renderCaption() {
    if (!state.data) return;
    var k = state.day, d = longDay(k);
    $("mapcap").textContent = (k === 0 ? t("capSeen", { d: d }) : t(k === state.today ? "capToday" : "capForecast", { d: d })) +
      (unc(k) || (k > 0 && stormNear()) ? " (" + t("lessCertain") + ")" : "");
    renderLimits();
  }

  /* What the map cannot show, next to the map: the coast, cloud gaps this week, a storm nearby. */
  var CLOUDY = 0.2;  // share of the sea near the island hidden by clouds that earns a badge
  function stormNear() { var s = state.data && state.data.context && state.data.context.storms; return !!(s && s.active && s.active.length && ageDays(s.checked) <= 1); }
  // With a storm near, the constant trade wind (used when no forecast came) would push the drift the wrong way.
  function driftHidden() { return state.day > 0 && stormNear() && state.data.sources.wind.fallback !== false; }
  function renderLimits() {
    var box = $("maplimits"), d = state.data, near = d && d.stats.near; box.textContent = "";
    if (!d) return;
    function line(cls, text) { var p = el("p", cls, text); box.appendChild(p); return p; }
    if (driftHidden()) line("badge warn", t("limitDriftHidden"));
    else if (state.day > 0 && stormNear()) line("badge warn", t("limitStorm"));
    if (near && near.cloud_share != null && near.cloud_share >= CLOUDY) {
      line("badge", t("limitCloudy", { p: Math.round(100 * near.cloud_share), km: fmtNum(near.radius_km), place: d.region.name }));
    }
    var coast = line("small", t("limitCoast") + " "), why = el("button", "link", t("limitWhy")); why.type = "button";
    why.addEventListener("click", function () { location.hash = "learn"; setTimeout(function () { scrollToEl($("lh-satellite")); }, 150); });
    coast.appendChild(why);
  }

  function setDay(k) {
    state.day = Math.max(0, Math.min(lastDay(), k));
    syncDays(); renderCaption(); renderLegend(); renderSites(); drawMap();
  }

  function renderPlay() {
    var b = $("play"), on = !!state.timer;
    b.innerHTML = on ? ICON.pause : ICON.play;
    b.setAttribute("aria-label", t(on ? "pause" : "play")); b.title = t(on ? "pause" : "play");
    b.hidden = !state.data;
  }
  function stop() { if (state.timer) { clearInterval(state.timer); state.timer = null; renderPlay(); } }
  function play() {
    if (state.timer) { stop(); return; }
    if (state.day >= lastDay()) setDay(0);
    state.timer = setInterval(function () { setDay(state.day + 1); if (state.day >= lastDay()) stop(); }, STEP_MS);
    renderPlay();
  }

  /* ---------- beach outlook board ---------- */
  function renderSites() {
    var box = $("sites"), d = state.data, day = state.day, focused = document.activeElement && document.activeElement.dataset.site;
    box.textContent = "";
    if (!d) return;
    var head = el("div", "bd-head"); head.setAttribute("aria-hidden", "true");
    head.appendChild(el("span"));
    for (var k = 0; k <= lastDay(); k++) {
      head.appendChild(el("span", [k === day ? "sel" : "", k === state.today ? "today" : "", unc(k) ? "unc" : ""].join(" ").trim() || null, String(dayNum(k))));
    }
    head.appendChild(el("span", "lvh"));
    box.appendChild(head);
    bySide(d.sites).forEach(function (g) {
      if (g.side) box.appendChild(el("h3", null, sideName(g.side)));
      g.sites.forEach(function (s) { box.appendChild(siteRow(s, day)); });
    });
    if (focused) box.querySelector('[data-site="' + focused + '"]').focus({ preventScroll: true });
  }

  function siteRow(s, day) {
    var b = el("button", "bd-row" + (s.id === state.sel ? " on" : "")), levels = t("levels"); b.type = "button"; b.dataset.site = s.id;
    b.appendChild(el("span", "nm", s.name));
    var week = [];
    s.risk.forEach(function (r, k) {
      var c = el("span", "c" + (k === day ? " sel" : "") + (unc(k) ? " unc" : "")), i = el("i", "l" + r);
      c.title = longDay(k) + ": " + levels[r]; c.appendChild(i); b.appendChild(c);
      week.push(fmtDay(k, { weekday: "short" }).replace(/\.$/, "") + " " + dayNum(k) + ": " + levels[r]);
    });
    var lv = el("span", "lv"); lv.appendChild(el("i", "chip l" + s.risk[day])); lv.appendChild(document.createTextNode(levels[s.risk[day]]));
    b.appendChild(lv);
    b.appendChild(el("span", "vh", ". " + week.join(", ")));
    b.addEventListener("click", function () { focusSite(s); });
    return b;
  }

  function renderReports() {
    var ul = $("reports"); ul.textContent = "";
    if (!state.reports.length) { ul.appendChild(el("li", "empty", t("noReports"))); return; }
    state.reports.slice().sort(function (a, b) { return String(b.properties.observed).localeCompare(String(a.properties.observed)); }).slice(0, 50)
      .forEach(function (f) {
        var p = f.properties, c = f.geometry.coordinates, li = el("li");
        li.style.borderLeftColor = p.level ? "var(--r" + p.level + ")" : "var(--clear)";
        li.appendChild(el("b", null, (t("amounts")[p.level] || "") + ", " + (p.beach || c[1].toFixed(3) + ", " + c[0].toFixed(3))));
        if (p.note) li.appendChild(el("span", "note", p.note));
        li.appendChild(el("span", "small", fmtDate(p.observed)));
        ul.appendChild(li);
      });
  }

  /* ---------- sighting form ----------
     Posts to the relay in worker/, which opens the same GitHub issue as the issue form.
     Until config.js names the relay, the site links to the GitHub issue form instead. */
  var form = { widget: undefined, token: "" };
  function reportConfig() { var r = (window.OPENSARGASSO || {}).report || {}; return r.endpoint && r.turnstileSiteKey ? r : null; }
  function localIso(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }

  function renderReportForm() {
    var on = !!reportConfig(), gh = $("report-btn");
    gh.className = on ? "" : "btn"; gh.textContent = t(on ? "reportGithub" : "reportBtn");
    $("report-help").textContent = t(on ? "reportHelpForm" : "reportHelp");
    $("report-open").hidden = !on; $("report-open").textContent = t("reportBtn");
    if (!on) { $("report-form").hidden = true; return; }
    [["rf-l-beach", "rfBeach"], ["rf-l-lat", "rfLat"], ["rf-l-lon", "rfLon"], ["rf-locate", "rfLocate"], ["rf-l-amount", "rfAmount"],
     ["rf-l-date", "rfDate"], ["rf-l-note", "rfNote"], ["rf-send", "rfSend"], ["rf-privacy", "rfPrivacy"]]
      .forEach(function (x) { $(x[0]).textContent = t(x[1]); });
    var sel = $("rf-beach"), keep = sel.value; sel.textContent = "";
    sel.appendChild(el("option", null, t("rfChoose"))).value = "";
    (state.data ? state.data.sites : []).forEach(function (s) { sel.appendChild(el("option", null, s.name)).value = s.name; });
    sel.appendChild(el("option", null, t("rfOther"))).value = "Other";
    sel.value = keep;
    var box = $("rf-amounts"), picked = box.querySelector("input:checked"); box.textContent = "";
    t("amounts").forEach(function (name, k) {
      var lab = el("label"), r = el("input"); r.type = "radio"; r.name = "rf-amount"; r.value = k;
      if (picked && +picked.value === k) r.checked = true;
      lab.appendChild(r); lab.appendChild(el("i", k ? "chip-r" + k : "chip-clear")); lab.appendChild(document.createTextNode(name + ", " + t("amountHelp")[k]));
      box.appendChild(lab);
    });
    $("rf-date").max = localIso(new Date());
  }

  function toggleReport() {
    var f = $("report-form"), open = f.hidden;
    f.hidden = !open; $("report-open").setAttribute("aria-expanded", String(open));
    if (!open) return;
    if (!$("rf-beach").value && state.sel) { $("rf-beach").value = (state.data.sites.filter(function (s) { return s.id === state.sel; })[0] || {}).name || ""; showWhere(); }
    loadCaptcha(); $("rf-beach").focus();
  }
  function showWhere() { $("rf-where").hidden = $("rf-beach").value !== "Other"; }
  function reportStatus(msg, bad) { var p = $("rf-status"); p.textContent = msg || ""; p.className = "small" + (bad ? " err" : ""); }

  // Turnstile's script loads only when someone opens the form.
  function loadCaptcha() {
    if (form.widget !== undefined) return;
    form.widget = null;
    window.onTurnstileLoad = function () {
      form.widget = window.turnstile.render("#rf-captcha", {
        sitekey: reportConfig().turnstileSiteKey, language: state.lang, theme: "auto",
        callback: function (tok) { form.token = tok; },
        "expired-callback": function () { form.token = ""; }, "error-callback": function () { form.token = ""; }
      });
    };
    var s = document.createElement("script");
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?onload=onTurnstileLoad&render=explicit"; s.async = true;
    s.onerror = function () { form.widget = undefined; reportStatus(t("rfNoCaptcha"), true); };
    document.head.appendChild(s);
  }

  function locate() {
    if (!navigator.geolocation) { reportStatus(t("rfNoLocation"), true); return; }
    navigator.geolocation.getCurrentPosition(function (p) {
      $("rf-lat").value = p.coords.latitude.toFixed(5); $("rf-lon").value = p.coords.longitude.toFixed(5); reportStatus("");
    }, function () { reportStatus(t("rfNoLocation"), true); }, { enableHighAccuracy: true, timeout: 15000 });
  }

  function sendReport(e) {
    e.preventDefault();
    var amount = $("rf-amounts").querySelector("input:checked"), other = $("rf-beach").value === "Other";
    var r = { beach: $("rf-beach").value, latitude: other ? $("rf-lat").value.trim() : "", longitude: other ? $("rf-lon").value.trim() : "",
              amount: amount ? +amount.value : null, observed: $("rf-date").value, note: $("rf-note").value, token: form.token, lang: state.lang };
    var num = function (v) { return /^-?\d{1,3}([.,]\d{1,10})?$/.test(v); };  // as the relay accepts
    var problem = !r.beach ? "rfNeedBeach" : other && !(num(r.latitude) && num(r.longitude)) ? "rfNeedPlace" : r.amount === null ? "rfNeedAmount"
      : r.observed && r.observed > localIso(new Date()) ? "rfFuture" : !r.token ? "rfNeedCaptcha" : "";
    if (problem) { reportStatus(t(problem), true); return; }
    $("rf-send").disabled = true; reportStatus(t("rfSending"));
    fetch(reportConfig().endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(r) })
      .then(function (res) { return res.json().catch(function () { return {}; }).then(function (j) { return res.ok && j.ok ? "" : j.error || "server"; }); })
      .catch(function () { return "server"; })
      .then(function (err) {
        if (!err) { $("report-form").reset(); showWhere(); reportStatus(t("rfThanks")); }
        else reportStatus(t(err === "captcha" ? "rfCaptchaFailed" : err === "invalid" ? "rfInvalid" : "rfFailed"), true);
        $("rf-send").disabled = false; form.token = "";
        if (window.turnstile && form.widget) window.turnstile.reset(form.widget);
      });
  }

  /* ---------- health, official bulletins, storm banner ----------
     Relayed from official sources: texts in i18n.js, links in the region file, plus two daily
     checks by the pipeline (the newest USF outlook, Atlantic storms near the region). */
  function regionLinks() { return (state.data && state.data.region.links) || {}; }
  function linkTo(href, text) { var a = el("a", null, text); a.href = href; a.rel = "noopener"; return a; }
  function fmtMonth(ym) { var d = new Date(ym + "-01T00:00:00Z"); return isNaN(d) ? ym : d.toLocaleDateString(state.lang, { year: "numeric", month: "long", timeZone: "UTC" }); }
  function heading(tag, text, id) { var h = el(tag, null, text); if (id) h.id = id; return h; }
  function linkList(items, note) {
    var ul = el("ul", "links");
    items.forEach(function (x) { var li = el("li"); li.appendChild(linkTo(x.url, x.name)); var n = note(x); if (n) li.appendChild(el("span", "small", n)); ul.appendChild(li); });
    return ul;
  }

  function renderHealth() {
    var box = $("health"), L = regionLinks(); box.textContent = "";
    if (!state.data) return;
    box.appendChild(heading("h2", t("hHealth"), "h-health"));
    box.appendChild(el("p", null, t("healthIntro")));
    var tbl = el("table", "bands"), head = el("tr"), body = el("tbody"), thead = el("thead");
    head.appendChild(el("th", null, t("healthCol1"))); head.appendChild(el("th", null, t("healthCol2")));
    thead.appendChild(head); tbl.appendChild(thead);
    t("healthBands").forEach(function (b, k) {
      var tr = el("tr", "b" + k), th = el("th", null, b[0]); th.scope = "row";
      tr.appendChild(th); tr.appendChild(el("td", null, b[1])); body.appendChild(tr);
    });
    tbl.appendChild(body); box.appendChild(tbl);
    box.appendChild(el("p", "small", t("healthVulnerable")));
    box.appendChild(el("p", "callout", t("healthNoReadings", { place: state.data.region.name })));
    var tips = el("ul", "tips"); t("healthTips").forEach(function (x) { tips.appendChild(el("li", null, x)); }); box.appendChild(tips);
    box.appendChild(el("p", null, t("healthSymptoms")));
    if (L.emergency) {
      box.appendChild(heading("h3", t("healthEmergency")));
      var em = el("ul", "links");
      L.emergency.forEach(function (e) {
        em.appendChild(el("li", null, sideName(e.side) + ": " + e.numbers.map(function (n) { return n.n + " (" + (t("emergencyFor")[n.for] || n.for) + ")"; }).join(", ")));
      });
      box.appendChild(em);
    }
    if (L.health) { box.appendChild(heading("h3", t("healthAdvice"))); box.appendChild(linkList(L.health, function (h) { return sideName(h.side); })); }
    box.appendChild(el("p", "small", t("healthSource")));
  }

  function renderBulletins(box, headingId) {
    var L = regionLinks(), d = state.data; box.textContent = "";
    if (!d) return;
    box.appendChild(heading("h2", t("hBulletins"), headingId));
    box.appendChild(el("p", "small", t("bulletinsHelp")));
    var ul = el("ul", "links");
    (L.bulletins || []).forEach(function (b) {
      var li = el("li"); li.appendChild(linkTo(b.url, t("bName")[b.id] || b.id));
      li.appendChild(el("span", "small", t("bDesc")[b.id] || ""));
      if (b.id === "sir" && d.sources.sir && d.sources.sir.fallback === false) li.appendChild(el("span", "small", t("bLatest", { d: fmtDate(d.sources.sir.date) })));
      if (b.id === "usf" && d.context && d.context.usf) {
        var latest = el("span", "small"); latest.appendChild(linkTo(d.context.usf.url, t("bLatest", { d: fmtMonth(d.context.usf.month) }) + " (PDF)")); li.appendChild(latest);
      }
      ul.appendChild(li);
    });
    box.appendChild(ul);
    box.appendChild(heading("h3", t("hWarnings")));
    box.appendChild(el("p", "small", t("warningsHelp")));
    box.appendChild(linkList(L.warnings || [], function (w) { return w.side ? sideName(w.side) : ""; }));
    box.appendChild(el("p", "small", t("notWarning")));
  }

  // Only from a recent check: an old storm position would mislead more than no banner.
  function renderStorm() {
    var box = $("storm"), d = state.data, s = d && d.context && d.context.storms;
    var near = stormNear() ? s.active[0] : null;
    box.hidden = !near; box.textContent = "";
    if (!near) return;
    box.appendChild(el("b", null, t("stormBanner", { kind: t("stormKinds")[near.kind] || t("stormKind"), name: near.name,
      km: fmtNum(near.distance_km), place: d.region.name, when: fmtDate(near.updated || s.checked) })));
    box.appendChild(document.createTextNode(" " + t("stormFollow") + " "));
    var warn = (regionLinks().warnings || []).concat([{ name: t("stormTrack"), url: near.url }]);
    warn.forEach(function (w, i) { if (i) box.appendChild(document.createTextNode(", ")); box.appendChild(linkTo(w.url, w.name + (w.side ? " (" + sideName(w.side) + ")" : ""))); });
    box.appendChild(document.createTextNode(". " + t("stormTail")));
  }

  function renderData() {
    [$("data"), $("m-data")].forEach(fillData);
  }
  function fillData(dl) {
    var d = state.data; dl.textContent = "";
    if (!d) return;
    function row(k, v) { dl.appendChild(el("dt", null, k)); dl.appendChild(el("dd", null, v)); }
    var s = d.sources;
    row(t("dGenerated"), fmtDate(d.generated));
    var si = sirInfo();
    row(t("dLevels"), si ? t("levelsSir", { d: fmtDate(si.date) }) + ageSuffix(si.date) : t("levelsModel"));
    row(t("dAfai"), fmtDate(s.afai.time) + ageSuffix(s.afai.time));
    row(t("dCurrents"), s.currents.fallback ? t("fallback") : fmtDate(s.currents.time) + ageSuffix(s.currents.time));
    row(t("dWind"), windText(s.wind));
    row(t("dPixels"), d.stats.detected.toLocaleString(state.lang) + " (" + t("pixelsRule", { t: fmtNum(d.settings.threshold) }) + ")");
    row(t("dCloud"), Math.round(100 * d.stats.nodata / d.stats.pixels) + " %");
    if (d.stats.near && d.stats.near.cloud_share != null) row(t("dCloudNear", { km: fmtNum(d.stats.near.radius_km) }), Math.round(100 * d.stats.near.cloud_share) + " %");
  }

  /* ---------- map ---------- */

  /* Sargassum as a density field. Every satellite cell (or drift particle) adds a
     Gaussian about one cell wide; the sum is colored with the sargassum ramp. A lone
     cell draws about its own size, neighbors merge into mats and filaments, and
     denser areas draw darker. Sums are kept in floats, so there is no banding. */
  var EDGE = 0.75;  // field value at half a cell from a lone cell's center (with SIGMA)
  var SIGMA = 0.65; // kernel width in cells: wide enough to join diagonal neighbors
  var TOP = 3.2;    // field value at the end of the color ramp
  function makeDensityLayer() {
    return L.Layer.extend({
      initialize: function (options) { L.setOptions(this, options); },  // without this the `pane` option is ignored
      onAdd: function (map) {
        this._canvas = L.DomUtil.create("canvas", "leaflet-zoom-hide", this.getPane());
        map.on("moveend resize", this._draw, this);
        this._draw();
      },
      onRemove: function (map) { L.DomUtil.remove(this._canvas); map.off("moveend resize", this._draw, this); },
      // points: [lon, lat, mass] with mass in cells; spread widens the kernel (forecast particles)
      setData: function (points, cellDeg, ramp, spread) {
        this._pts = points; this._cell = cellDeg; this._ramp = ramp; this._spread = spread || 1;
        if (this._map) this._draw();
        return this;
      },
      _draw: function () {
        var map = this._map, size = map.getSize(), c = this._canvas, pad = 0.25;
        var ox = Math.round(size.x * pad), oy = Math.round(size.y * pad), w = size.x + 2 * ox, h = size.y + 2 * oy;
        L.DomUtil.setPosition(c, map.containerPointToLayerPoint([-ox, -oy]));
        c.width = w; c.height = h; c.style.width = w + "px"; c.style.height = h + "px";
        var pts = this._pts || [];
        if (!pts.length || !this._ramp || !size.x || !size.y) return;
        // map.project keeps fractions of a pixel; latLngToContainerPoint rounds them, and cells
        // 5.5 px apart then land 5 and 6 px apart, which shows as a grid in dense mats.
        var z = map.getZoom(), tl = map.getPixelBounds().min, mid = map.getCenter();
        var cellPx = map.project([mid.lat, mid.lng + this._cell], z).x - map.project(mid, z).x;
        var sigma = Math.max(0.7, cellPx * SIGMA * this._spread), r = Math.ceil(3 * sigma), s2 = 2 * sigma * sigma, cut = Math.exp(-r * r / s2);
        var field = new Float32Array(w * h), gx = new Float32Array(2 * r + 1), gy = new Float32Array(2 * r + 1);
        for (var i = 0; i < pts.length; i++) {
          var q = map.project([pts[i][1], pts[i][0]], z), fx = q.x - tl.x + ox, fy = q.y - tl.y + oy, x = Math.round(fx), y = Math.round(fy);
          if (x < -r || y < -r || x >= w + r || y >= h + r) continue;
          // Sampled at the exact position so cells on a lattice add up evenly, and lowered
          // to reach zero at the cutoff, where a step would show as a straight edge.
          for (var k = -r; k <= r; k++) {
            gx[k + r] = Math.max(0, Math.exp(-(x + k - fx) * (x + k - fx) / s2) - cut);
            gy[k + r] = pts[i][2] * Math.max(0, Math.exp(-(y + k - fy) * (y + k - fy) / s2) - cut);
          }
          var x0 = Math.max(0, x - r), x1 = Math.min(w - 1, x + r), y1 = Math.min(h - 1, y + r);
          for (var yy = Math.max(0, y - r); yy <= y1; yy++) {
            var v = gy[yy - y + r], row = yy * w;
            for (var xx = x0; xx <= x1; xx++) field[row + xx] += v * gx[xx - x + r];
          }
        }
        // The edge fades over a few screen pixels at any zoom, so shapes stay sharp when zoomed in.
        var band = EDGE * Math.min(0.4, 2.5 / sigma), lo = EDGE - band, hi = EDGE + band;
        var ctx = c.getContext("2d"), img = ctx.createImageData(w, h), px = img.data, pal = rampPalette(this._ramp);
        for (var j = 0; j < field.length; j++) {
          var v = field[j];
          if (v <= lo) continue;
          var o = Math.min(255, Math.round(Math.max(v, hi) / TOP * 255)) * 4;
          px[4 * j] = pal[o]; px[4 * j + 1] = pal[o + 1]; px[4 * j + 2] = pal[o + 2];
          px[4 * j + 3] = v < hi ? pal[o + 3] * (v - lo) / (hi - lo) : pal[o + 3];
        }
        ctx.putImageData(img, 0, 0);
      }
    });
  }
  /* Field value to color, light to dark with density: a lone cell peaks at 1, a
     filament one cell wide at about 1.6, a solid mat at about 2.65. */
  function rampPalette(colors) {
    var c = document.createElement("canvas"), x = c.getContext("2d"), grad;
    c.width = 256; c.height = 1;
    grad = x.createLinearGradient(0, 0, 256, 0);
    [[EDGE, 0, 0.75], [1.6, 1, 0.85], [2.3, 2, 0.9], [TOP, 2, 0.9]].forEach(function (s) { grad.addColorStop(s[0] / TOP, rgba(colors[s[1]], s[2])); });
    x.fillStyle = grad; x.fillRect(0, 0, 256, 1);
    return x.getImageData(0, 0, 256, 1).data;
  }
  function rgba(hex, a) {
    var n = parseInt(hex.replace("#", ""), 16);
    return "rgba(" + (n >> 16 & 255) + "," + (n >> 8 & 255) + "," + (n & 255) + "," + a + ")";
  }

  function initMap() {
    if (!window.L) { var m = $("map"); m.className = "nomap"; m.textContent = t("nomap"); return; }
    var d = state.data, map = state.map = L.map("map", { zoomSnap: 0.5, renderer: L.canvas({ padding: 0.5, tolerance: 6 }) });
    if (d && d.sites.length) {
      map.fitBounds(L.latLngBounds(d.sites.map(function (s) { return [s.lat, s.lon]; })), { padding: [28, 28] });
      map.setZoom(map.getZoom() - 1, { animate: false });
    } else {
      var v = d ? d.region.view : { center: [18.065, -63.07], zoom: 12 };
      map.setView(v.center, v.zoom);
    }
    var tiles = (window.OPENSARGASSO || {}).tiles;  // the basemap is set in config.js
    if (tiles) L.tileLayer(tiles.url, { maxZoom: tiles.maxZoom || 18, attribution: tiles.attribution }).addTo(map);
    map.createPane("density").style.zIndex = 350;
    state.layers.older = new (makeDensityLayer())({ pane: "density" }).addTo(map);  // under the recent sightings
    state.layers.density = new (makeDensityLayer())({ pane: "density" }).addTo(map);
    ["ashore", "sites", "reports"].forEach(function (k) { state.layers[k] = L.layerGroup().addTo(map); });
    if (window.ResizeObserver) new ResizeObserver(function () { map.invalidateSize(); }).observe($("map"));
    map.on("zoomend", drawMarkers);
  }

  function ramp() { return [css("--clear"), css("--r1"), css("--r2"), css("--r3")]; }
  function oldRamp() { return [css("--o1"), css("--o2"), css("--o3")]; }

  function drawMap() {
    if (!state.map || !state.data) return;
    var d = state.data, day = state.day, cell = d.settings.cell_deg, pts = [], old = [], spread = 1;
    if (day === 0) {
      // Each at its cell center. Patches seen earlier in the week are drawn in gray: they have likely moved.
      var split = dated();
      d.detections.forEach(function (c) { (!split || recent(c) ? pts : old).push([c[0], c[1], 1]); });
    } else {
      // Particles carry the detected area: each stands for n cells. When n > 1 its
      // kernel is widened so the same area spreads over a larger footprint.
      var n = d.detections.length / Math.max(1, d.forecast[0].length);
      spread = Math.sqrt(Math.max(1, n));
      pts = driftHidden() ? [] : d.forecast[day].filter(function (p) { return p[2] === 0; }).map(function (p) { return [p[0], p[1], Math.min(1, n)]; });
    }
    state.layers.older.setData(old, cell, oldRamp(), 1);
    state.layers.density.setData(pts, cell, ramp().slice(1), spread);
    drawMarkers();
  }

  function drawMarkers() {
    if (!state.map || !state.data) return;
    var d = state.data, day = state.day, Lr = state.layers, panel = css("--panel"), ink = css("--ink"), colors = ramp(), levels = t("levels");
    var zoom = state.map.getZoom(), size = zoom >= 12 ? 7 : zoom >= 11 ? 5.5 : 4;
    Lr.ashore.clearLayers(); Lr.sites.clearLayers(); Lr.reports.clearLayers(); state.markers = {};
    if (day > 0 && !driftHidden()) d.forecast[day].forEach(function (p) {
      if (p[2] === 1) L.circleMarker([p[1], p[0]], { radius: 2.5, color: panel, weight: 1, fillColor: colors[3], fillOpacity: 1, interactive: false }).addTo(Lr.ashore);
    });
    state.reports.forEach(function (f) {
      var c = f.geometry.coordinates, p = f.properties;
      L.marker([c[1], c[0]], { icon: L.divIcon({ className: "sighting l" + p.level, iconSize: [14, 14] }), keyboard: false })
        .bindTooltip(t("legendReport") + ": " + t("amounts")[p.level] + ", " + fmtDate(p.observed)).addTo(Lr.reports);
    });
    d.sites.forEach(function (s) {
      var r = s.risk[day], on = s.id === state.sel;
      state.markers[s.id] = L.circleMarker([s.lat, s.lon], {
        radius: on ? size + 3 : size, color: on ? ink : panel, weight: on ? 3 : size > 4 ? 2.5 : 1.5, fillColor: colors[r], fillOpacity: 1
      }).bindTooltip(s.name + ": " + levels[r], { direction: "top", offset: [0, -8] })
        .on("click", function () { focusSite(s, true); })
        .addTo(Lr.sites);
    });
    if (state.markers[state.sel]) state.markers[state.sel].openTooltip();
  }

  function focusSite(s, fromMap) {
    state.sel = s.id;
    renderSites(); drawMap();
    if (!state.map) return;
    if (!fromMap) {
      state.map.setView([s.lat, s.lon], Math.max(state.map.getZoom(), 13), { animate: !reduceMotion() });
      $("map").scrollIntoView({ block: "nearest", behavior: reduceMotion() ? "auto" : "smooth" });
    }
  }

  /* ---------- views ---------- */
  var VIEWS = ["beaches", "learn", "managers", "data"];
  function currentView() { var v = location.hash.slice(1); return VIEWS.indexOf(v) >= 0 ? v : "beaches"; }
  function showView() {
    var v = currentView();
    VIEWS.forEach(function (name) { $("view-" + name).hidden = name !== v; });
    Array.prototype.forEach.call($("views").querySelectorAll("a"), function (a) {
      if (a.dataset.view === v) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    if (v !== "beaches") stop();
    else if (!state.map && (state.data || state.failed)) { initMap(); drawMap(); }  // Leaflet needs a visible container
  }
  function goToBeach(s) {
    if (location.hash !== "#beaches") location.hash = "beaches";
    showView(); focusSite(s);
  }

  /* ---------- learn ----------
     Content in learn.js. The contents list scrolls with buttons: the address's # already picks the view. */
  function scrollToEl(node) { if (node) node.scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" }); }
  function renderLearn() {
    var all = window.LEARN || {}, L = all[state.lang] || all.en, box = $("l-sections"), toc = $("l-toc");
    box.textContent = ""; toc.textContent = "";
    if (!L) return;
    $("l-title").textContent = L.title; $("l-intro").textContent = L.intro;
    L.sections.forEach(function (s) {
      var sec = el("section", "lsec"), h = el("h2", null, s.title);
      h.id = "lh-" + s.id; sec.setAttribute("aria-labelledby", h.id); sec.appendChild(h);
      s.text.forEach(function (p) { sec.appendChild(el("p", null, p)); });
      if (s.action) {
        var go = el("button", "btn", s.action[0]); go.type = "button";
        go.addEventListener("click", function () {
          location.hash = s.action[1].slice(1);
          setTimeout(function () { scrollToEl($("h-reports")); }, 150);  // after the view switch scrolls to the top
        });
        sec.appendChild(go);
      }
      var src = el("p", "small src"); src.appendChild(document.createTextNode(L.sourcesLabel + ": "));
      s.sources.forEach(function (x, i) { if (i) src.appendChild(document.createTextNode("; ")); src.appendChild(linkTo(x[1], x[0])); });
      sec.appendChild(src); box.appendChild(sec);
      var item = el("button", "link", s.title); item.type = "button";
      item.addEventListener("click", function () { scrollToEl(sec); });
      toc.appendChild(item);
    });
  }

  /* ---------- coastal managers ---------- */
  function renderManagers() {
    var d = state.data, box = $("m-sides"), levels = t("levels"); box.textContent = "";
    if (!d) return;
    bySide(d.sites).forEach(function (g) {
      var card = el("section", "side-card"), o = g.sites.map(outlook);
      var hit = o.filter(function (x) { return x.first >= 0; });
      card.appendChild(el("h3", null, sideName(g.side)));
      card.appendChild(el("p", "lead", hit.length ? t("mSideLine", { n: hit.length, total: g.sites.length }) : t("mSideNone")));
      if (hit.length) {
        var first = Math.min.apply(null, hit.map(function (x) { return x.first; }));
        card.appendChild(el("p", null, first === horizon() ? t("mFirstNow") : t("mFirst", { d: shortDay(first) })));
      }
      var peak = Math.max.apply(null, o.map(function (x) { return x.peak; }));
      if (peak > 0) {
        var peakDay = Math.min.apply(null, o.filter(function (x) { return x.peak === peak; }).map(function (x) { return x.peakDay; }));
        card.appendChild(el("p", null, t("mPeak", { level: levels[peak], d: shortDay(peakDay) })));
      }
      card.appendChild(el("p", "small", t("mPerDay")));
      card.appendChild(dayBars(g.sites));
      box.appendChild(card);
    });
    var lg = $("m-legend"); lg.textContent = "";
    [3, 2, 1, 0].forEach(function (r) { var s = el("span", "lvl"); s.appendChild(el("i", "chip l" + r)); s.appendChild(document.createTextNode(levels[r])); lg.appendChild(s); });
    renderEarlyWarning();
  }

  /* One stacked bar per day: how many beaches on this side are at each level. */
  function dayBars(sites) {
    var wrap = el("div", "bars"), levels = t("levels");
    for (var k = 0; k <= lastDay(); k++) {
      var col = el("div", "daybar" + (k === state.today ? " today" : "")), bar = el("div", "bar"), counts = [0, 0, 0, 0];
      sites.forEach(function (s) { counts[s.risk[k]]++; });
      [3, 2, 1].forEach(function (r) {
        if (!counts[r]) return;
        var seg = el("i", "l" + r); seg.style.height = "calc(" + (100 * counts[r] / sites.length) + "% - 2px)"; bar.appendChild(seg);
      });
      var label = longDay(k) + ": " + [3, 2, 1, 0].map(function (r) { return counts[r] + " " + levels[r]; }).join(", ");
      bar.setAttribute("role", "img"); bar.setAttribute("aria-label", label); col.title = label;
      col.appendChild(bar); col.appendChild(el("span", "bar-lbl", String(dayNum(k))));
      wrap.appendChild(col);
    }
    return wrap;
  }

  function levelCell(r) {
    var td = el("td"), s = el("span", "lvl");
    s.appendChild(el("i", "chip l" + r)); s.appendChild(document.createTextNode(t("levels")[r])); td.appendChild(s);
    return td;
  }

  /* Beaches sorted by how soon they may reach Moderate, then by peak level. */
  function renderEarlyWarning() {
    var tb = $("m-table"), d = state.data, levels = t("levels"), from = horizon(); tb.textContent = "";
    // Explicit roles keep table semantics when the phone layout changes display.
    var head = el("tr"), cols = [["colBeach"], ["colSide", "side-col"], ["colToday"], ["colFirst"], ["colPeak"], ["colWeek", "wk-col"]];
    tb.setAttribute("role", "table"); head.setAttribute("role", "row");
    cols.forEach(function (c) {
      var th = el("th", c[1] || null, t(c[0])); th.scope = "col"; th.setAttribute("role", "columnheader"); head.appendChild(th);
    });
    function cell(td, col) { td.setAttribute("role", "cell"); td.dataset.label = t(cols[col][0]); return td; }
    var thead = el("thead"); thead.appendChild(head); tb.appendChild(thead);
    var tbody = el("tbody");
    d.sites.map(function (s) { return { s: s, o: outlook(s), n: s.count.slice(from).reduce(function (a, b) { return a + b; }, 0) }; })
      .sort(function (a, b) {
        return (a.o.first < 0) - (b.o.first < 0) || a.o.first - b.o.first || b.o.peak - a.o.peak || b.n - a.n || a.s.name.localeCompare(b.s.name);
      })
      .forEach(function (x) {
        var s = x.s, o = x.o, tr = el("tr"), name = el("th"), btn = el("button", "linkish", s.name);
        tr.setAttribute("role", "row"); name.scope = "row"; name.setAttribute("role", "rowheader");
        btn.type = "button"; btn.addEventListener("click", function () { goToBeach(s); });
        name.appendChild(btn); tr.appendChild(name);
        tr.appendChild(cell(el("td", "side-col", sideName(s.side)), 1));
        tr.appendChild(cell(levelCell(o.now), 2));
        tr.appendChild(cell(el("td", null, o.first < 0 ? t("notExpected") : o.first === from ? t("now") : shortDay(o.first)), 3));
        var pk = cell(levelCell(o.peak), 4);
        if (o.peak > 0) pk.appendChild(el("span", "small", shortDay(o.peakDay)));
        tr.appendChild(pk);
        var wk = cell(el("td", "wk-col"), 5), strip = el("span", "wk");
        s.risk.forEach(function (r, k) { var i = el("i", "l" + r + (k === from ? " now" : "")); i.title = longDay(k) + ": " + levels[r]; strip.appendChild(i); });
        wk.appendChild(strip); tr.appendChild(wk);
        tbody.appendChild(tr);
      });
    tb.appendChild(tbody);
  }

  function isoDay(k) { return new Date(state.base + k * DAY_MS).toISOString().slice(0, 10); }
  function csvCell(v, sep) { v = String(v); return v.indexOf(sep) >= 0 || /["\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
  function downloadCSV() {
    var d = state.data, levels = t("levels"), days = [];
    if (!d) return;
    // French and Dutch spreadsheets expect semicolons between fields and a decimal comma.
    var local = state.lang === "fr" || state.lang === "nl", sep = local ? ";" : ",";
    function coord(x) { return local ? String(x).replace(".", ",") : x; }
    for (var k = 0; k <= lastDay(); k++) days.push(isoDay(k));
    var head = ["id", "name", "side", "lat", "lon", "source"].concat(days, days.map(function (x) { return x + " " + t("csvParticles"); }));  // weighted model counts
    var rows = d.sites.map(function (s) {
      return [s.id, s.name, s.side || "", coord(s.lat), coord(s.lon), s.source || ""].concat(s.risk.map(function (r) { return levels[r]; }), s.count);
    });
    // The byte order mark lets spreadsheet programs read accented names correctly.
    var text = "\ufeff" + [head].concat(rows).map(function (r) { return r.map(function (v) { return csvCell(v, sep); }).join(sep); }).join("\r\n") + "\r\n";
    var a = el("a"); a.href = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
    a.download = "opensargasso-" + d.region.id + "-" + d.generated.slice(0, 10) + ".csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  /* ---------- data and methods ---------- */
  function renderDocs() {
    var d = state.data, base = location.href.replace(/[#?].*$/, "").replace(/[^/]*$/, ""), url = base + "data/latest.json";
    function table(id, rows) {
      var tb = $(id); tb.textContent = ""; tb.setAttribute("role", "table");  // roles survive the stacked phone layout
      rows.forEach(function (r) {
        var tr = el("tr"), th = el("th"); th.scope = "row"; tr.setAttribute("role", "row"); th.setAttribute("role", "rowheader");
        if (r.href) { var a = el("a"); a.href = r.href; a.appendChild(el("code", null, r.name)); th.appendChild(a); } else th.appendChild(el("code", null, r.name));
        var td = el("td", null, t(r.key)); td.setAttribute("role", "cell");
        tr.appendChild(th); tr.appendChild(td); tb.appendChild(tr);
      });
    }
    var day = d ? "data/history/" + d.generated.slice(0, 10) + ".json" : "data/history/YYYY-MM-DD.json";
    table("r-files", [{ name: "data/latest.json", href: "data/latest.json", key: "fLatest" },
                      { name: "data/history/index.json", href: "data/history/index.json", key: "fIndex" },
                      { name: day, href: d ? day : null, key: "fDay" },
                      { name: "data/reports.geojson", href: "data/reports.geojson", key: "fReports" }]);
    $("r-example").textContent = "$ curl -s " + url + "\n\n# Python\nimport json, urllib.request\n\n" +
      'data = json.load(urllib.request.urlopen("' + url + '"))\nfor site in data["sites"]:\n    print(site["name"], site["risk"])';
    table("r-fields", [["generated, sample", "fGenerated"], ["sources", "fSources"], ["settings", "fSettings"], ["stats", "fStats"],
                       ["detections", "fDetections"], ["forecast", "fForecast"], ["sites", "fSites"]].map(function (r) { return { name: r[0], key: r[1] }; }));

    var st = (d && d.settings) || {}, risk = st.risk || {}, ol = $("r-method"); ol.textContent = "";
    var vals = { block: fmtNum(st.background_block_deg), threshold: fmtNum(st.threshold), max: fmtNum(st.max_particles),
                 step: fmtNum(st.step_hours), days: fmtNum(st.days), windage: st.windage == null ? "?" : fmtNum(st.windage * 100),
                 radius: fmtNum(risk.radius_km != null ? risk.radius_km : st.radius_km), low: fmtNum(risk.low),
                 moderate: fmtNum(risk.moderate), high: fmtNum(risk.high) };
    ["st1", "st2", "st3", "st4", "st5"].forEach(function (k) { ol.appendChild(el("li", null, t(k, vals))); });

    var src = $("r-sources"); src.textContent = "";
    if (d) {
      var s = d.sources;
      [[t("dAfai"), s.afai, fmtDate(s.afai.time) + ageSuffix(s.afai.time)],
       [t("dCurrents"), s.currents, s.currents.fallback ? t("fallback") : fmtDate(s.currents.time) + ageSuffix(s.currents.time)],
       [t("dLevels"), s.sir || { name: "NOAA SIR" }, s.sir && s.sir.fallback === false ? t("reportOf", { d: fmtDate(s.sir.date) }) : t("levelsModel")],
       [t("dLand"), s.land, s.land.available ? "" : t("unavailable")],
       [t("dWind"), s.wind.fallback === false ? s.wind : { name: t("windFallback") },
        s.wind.fallback !== false ? "" : s.wind.cached ? windText(s.wind) : t("windUntil", { d: fmtDate(s.wind.until) })]].forEach(function (r) {
        var dd = el("dd");
        if (r[1].url) { var a = el("a", null, r[1].name); a.href = r[1].url; a.rel = "noopener"; dd.appendChild(a); } else dd.appendChild(document.createTextNode(r[1].name));
        if (r[2]) dd.appendChild(el("span", "small", r[2]));
        src.appendChild(el("dt", null, r[0])); src.appendChild(dd);
      });
    }

    var run = $("r-run"); run.textContent = "";
    if (d) {
      var stt = d.stats;
      [[t("rBuilt"), d.generated.replace("T", " ").replace("Z", " UTC")], [t("rVersion"), d.version],
       [t("sPixels"), fmtNum(stt.pixels)], [t("sValid"), fmtNum(stt.valid)], [t("sNoData"), fmtNum(stt.nodata)],
       [t("sLand"), fmtNum(stt.land)], [t("sDetected"), fmtNum(stt.detected)]].forEach(function (r) {
        run.appendChild(el("dt", null, r[0])); run.appendChild(el("dd", null, r[1]));
      });
    }

    var cite = $("r-cite"), repo = (window.OPENSARGASSO || {}).repo || ""; cite.textContent = "";
    cite.appendChild(el("li", null, t("refAfai")));
    var sir = el("li", null, t("refRisk") + " "), a = el("a", null, "cwcgom.aoml.noaa.gov/SIR"); a.href = "https://cwcgom.aoml.noaa.gov/SIR/"; a.rel = "noopener";
    sir.appendChild(a); cite.appendChild(sir);
    cite.appendChild(el("li", null, t("refUsf")));
    var me = el("li", null, t("citeAs", { region: d ? d.region.name : "", date: d ? fmtDate(d.generated) : "" }));
    if (repo && repo.indexOf("OWNER/") !== 0) {
      var gh = el("a", null, "github.com/" + repo); gh.href = "https://github.com/" + repo; me.appendChild(document.createTextNode(" ")); me.appendChild(gh);
    }
    cite.appendChild(me);

    var lim = $("r-limits"); lim.textContent = "";
    ["l1", "l2", "l3", "l4", "l5", "l6"].forEach(function (k) { lim.appendChild(el("li", null, t(k))); });
  }

  function renderAll() {
    renderStatic(); renderNotices(); renderHeadline(); renderDays(); renderCaption();
    renderSites(); renderReports(); renderData(); renderPlay(); renderManagers(); renderDocs(); drawMap();
    renderHealth(); renderBulletins($("bulletins"), "h-bulletins"); renderBulletins($("m-bulletins"), "m-h-bulletins"); renderStorm();
    renderLearn();
  }

  function getJSON(url) { return fetch(url, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(url + " " + r.status); return r.json(); }); }

  pickLang(); renderStatic(); renderHeadline(); renderPlay(); renderDocs(); renderLearn(); showView();
  window.addEventListener("hashchange", function () { showView(); window.scrollTo(0, 0); });
  $("csv").addEventListener("click", downloadCSV);
  $("report-open").addEventListener("click", toggleReport);
  $("rf-beach").addEventListener("change", showWhere);
  $("rf-locate").addEventListener("click", locate);
  $("report-form").addEventListener("submit", sendReport);
  $("report-form").addEventListener("change", function () { if ($("rf-status").className.indexOf("err") > -1) reportStatus(""); });
  $("play").addEventListener("click", play);
  $("days").addEventListener("click", function (e) {
    var b = e.target.closest("button"); if (!b) return;
    stop(); setDay(+b.dataset.day);
  });
  $("days").addEventListener("keydown", function (e) {
    var step = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[e.key], k = state.day;
    if (step) k += step; else if (e.key === "Home") k = 0; else if (e.key === "End") k = lastDay(); else return;
    e.preventDefault(); stop(); setDay(k);
    var b = $("days").querySelector('[data-day="' + state.day + '"]'); if (b) b.focus();
  });
  if (window.matchMedia) matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawMap);
  getJSON("data/latest.json").then(function (d) {
    state.data = d; setDates(d);
    state.day = inRange(state.today) ? state.today : 0;
    renderAll(); showView();
    return getJSON("data/reports.geojson").then(function (fc) {
      state.reports = (fc.features || []).filter(function (f) {
        var c = f && f.geometry && f.geometry.coordinates, p = f && f.properties;
        return c && isFinite(c[0]) && isFinite(c[1]) && p && p.level >= 0 && p.level <= 3;
      });
      renderReports(); renderLegend(); drawMap();
    }).catch(function () {});
  }).catch(function () { state.failed = true; showView(); $("error").hidden = false; $("error").textContent = t("error"); });
})();
