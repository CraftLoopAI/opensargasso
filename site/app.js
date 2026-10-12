(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var state = { lang: "en", day: 0, data: null, reports: [], base: 0, today: -1, sel: null, timer: null,
                map: null, layers: {}, markers: {} };
  var STALE_DAYS = 10, DAY_MS = 864e5, STEP_MS = 900;
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
  function fmtDate(iso) { if (!iso || iso === "sample") return "-"; var d = new Date(iso); return isNaN(d) ? iso : d.toLocaleDateString(state.lang, { year: "numeric", month: "short", day: "numeric" }); }
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
    $("h-outlook").textContent = t("outlook"); $("outlook-help").textContent = t("outlookHelp");
    $("h-reports").textContent = t("reports"); $("report-btn").textContent = t("reportBtn"); $("report-help").textContent = t("reportHelp");
    $("h-data").textContent = t("data");
    $("dl-json").textContent = t("json"); $("dl-reports").textContent = t("reportsFile"); $("to-methods").textContent = t("moreMethods");
    Array.prototype.forEach.call($("views").querySelectorAll("a"), function (a) { a.textContent = t("v_" + a.dataset.view); });
    $("views").setAttribute("aria-label", t("viewsLabel"));
    [["m-title", "mTitle"], ["m-intro", "mIntro"], ["m-h-sides", "mSides"], ["m-h-table", "mTable"], ["m-table-help", "mTableHelp"],
     ["csv", "csv"], ["csv-help", "csvHelp"], ["m-h-quality", "mQuality"], ["r-title", "rTitle"], ["r-intro", "rIntro"],
     ["r-h-files", "rFiles"], ["r-h-example", "rExample"], ["r-h-fields", "rFields"], ["r-h-method", "rMethod"],
     ["r-h-sources", "rSources"], ["r-h-run", "rRun"], ["r-h-cite", "rCite"], ["r-h-limits", "rLimits"]]
      .forEach(function (x) { $(x[0]).textContent = t(x[1]); });
    $("footer").textContent = t("footer");
    if ($("map").className === "nomap") $("map").textContent = t("nomap");
    $("days").setAttribute("aria-label", t("dayPicker"));
    var repo = (window.OPENSARGASSO || {}).repo || "";
    $("report-btn").href = "https://github.com/" + repo + "/issues/new?template=sargassum-report.yml";
    renderLegend();
  }

  function renderLegend() {
    var lg = $("legend"); lg.textContent = "";
    function item(cls) { var s = el("span", "lg " + (cls || "")); lg.appendChild(s); return s; }
    var sea = item(), ends = el("span", "ends");
    sea.appendChild(el("span", null, t("legendSea")));
    ends.appendChild(el("span", null, t("less"))); ends.appendChild(el("i", "ramp")); ends.appendChild(el("span", null, t("more")));
    sea.appendChild(ends);
    var ashore = item(); ashore.appendChild(el("i", "dot")); ashore.appendChild(document.createTextNode(t("legendAshore")));
    var lv = item(); lv.appendChild(el("span", null, t("legendBeach")));
    t("levels").forEach(function (name, r) { var s = el("span", "lvl"); s.appendChild(el("i", "chip l" + r)); s.appendChild(document.createTextNode(name)); lv.appendChild(s); });
    if (state.reports.length) { var rp = item(); rp.appendChild(el("i", "diamond")); rp.appendChild(document.createTextNode(t("legendReport"))); }
  }

  function renderHeadline() {
    var d = state.data;
    if (!d) { $("headline").textContent = t("title"); return; }
    var n = d.sites.filter(function (s) { return outlook(s).first >= 0; }).length;
    $("headline").textContent = n ? t("headline", { n: n, total: d.sites.length }) : t("headlineNone");
  }

  function renderNotices() {
    var d = state.data;
    $("sample").hidden = !(d && d.sample); $("sample").textContent = t("sample");
    var age = d && d.sources.afai.age_days;
    $("stale").hidden = !(age != null && age > STALE_DAYS); $("stale").textContent = t("stale", age);
  }

  /* ---------- day picker ---------- */
  function renderDays() {
    var strip = $("days"); strip.textContent = "";
    if (!state.data) return;
    var seen = el("span", "grp sat"), fc = el("span", "grp fc", t("forecast"));
    seen.innerHTML = ICON.satellite; seen.appendChild(el("span", "tx", t("seen")));
    [seen, fc].forEach(function (c) { c.setAttribute("aria-hidden", "true"); strip.appendChild(c); });
    for (var k = 0; k <= lastDay(); k++) {
      var b = el("button", k === state.today ? "today" : null); b.type = "button"; b.dataset.day = k;
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
    $("mapcap").textContent = k === 0 ? t("capSeen", { d: d }) : t(k === state.today ? "capToday" : "capForecast", { d: d });
  }

  function setDay(k) {
    state.day = Math.max(0, Math.min(lastDay(), k));
    syncDays(); renderCaption(); renderSites(); drawMap();
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
      head.appendChild(el("span", [k === day ? "sel" : "", k === state.today ? "today" : ""].join(" ").trim() || null, String(dayNum(k))));
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
      var c = el("span", "c" + (k === day ? " sel" : "")), i = el("i", "l" + r);
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

  function renderData() {
    [$("data"), $("m-data")].forEach(fillData);
  }
  function fillData(dl) {
    var d = state.data; dl.textContent = "";
    if (!d) return;
    function row(k, v) { dl.appendChild(el("dt", null, k)); dl.appendChild(el("dd", null, v)); }
    var s = d.sources;
    row(t("dGenerated"), fmtDate(d.generated));
    row(t("dAfai"), fmtDate(s.afai.time) + (s.afai.age_days != null ? " (" + ageText(s.afai.age_days) + ")" : ""));
    row(t("dCurrents"), s.currents.fallback ? t("fallback") : fmtDate(s.currents.time) + (s.currents.age_days != null ? " (" + ageText(s.currents.age_days) + ")" : ""));
    row(t("dWind"), t("constantWind"));
    row(t("dPixels"), d.stats.detected.toLocaleString(state.lang) + " (AFAI > " + d.settings.threshold + ")");
    row(t("dCloud"), Math.round(100 * d.stats.nodata / d.stats.pixels) + " %");
  }

  /* ---------- map ---------- */

  /* Sargassum as a soft density field instead of square cells. Each point adds a
     blurred disc about one satellite cell wide; the summed coverage is then colored
     with the sargassum ramp, so neighboring cells merge into mats. */
  function makeDensityLayer() {
    return L.Layer.extend({
      onAdd: function (map) {
        this._canvas = L.DomUtil.create("canvas", "leaflet-zoom-hide", this.getPane());
        map.on("moveend resize", this._draw, this);
        this._draw();
      },
      onRemove: function (map) { L.DomUtil.remove(this._canvas); map.off("moveend resize", this._draw, this); },
      setData: function (points, cellDeg, ramp) {
        this._pts = points; this._cell = cellDeg; this._ramp = ramp;
        if (this._map) this._draw();
        return this;
      },
      _draw: function () {
        var map = this._map, size = map.getSize(), c = this._canvas, pad = 0.25;
        var ox = Math.round(size.x * pad), oy = Math.round(size.y * pad), w = size.x + 2 * ox, h = size.y + 2 * oy;
        L.DomUtil.setPosition(c, map.containerPointToLayerPoint([-ox, -oy]));
        c.width = w; c.height = h; c.style.width = w + "px"; c.style.height = h + "px";
        var pts = this._pts || [], ctx = c.getContext("2d", { willReadFrequently: true });
        if (!pts.length || !this._ramp || !size.x || !size.y) return;
        var mid = map.getCenter(), a = map.latLngToContainerPoint(mid), b = map.latLngToContainerPoint([mid.lat, mid.lng + this._cell]);
        var r = Math.max(4, Math.min(22, Math.abs(b.x - a.x) * 0.42)), stamp = blurStamp(r);
        for (var i = 0; i < pts.length; i++) {
          var q = map.latLngToContainerPoint([pts[i][1], pts[i][0]]), x = q.x + ox, y = q.y + oy;
          if (x < -r || y < -r || x > w + r || y > h + r) continue;
          ctx.globalAlpha = pts[i][2]; ctx.drawImage(stamp, x - r, y - r);
        }
        var img = ctx.getImageData(0, 0, w, h), px = img.data, pal = rampPalette(this._ramp);
        for (var j = 3; j < px.length; j += 4) {
          var v = px[j];
          if (v) { var o = v * 4; px[j - 3] = pal[o]; px[j - 2] = pal[o + 1]; px[j - 1] = pal[o + 2]; px[j] = pal[o + 3]; }
        }
        ctx.putImageData(img, 0, 0);
      }
    });
  }
  function blurStamp(r) {
    var s = document.createElement("canvas"), x = s.getContext("2d"), g;
    s.width = s.height = Math.ceil(2 * r);
    g = x.createRadialGradient(r, r, 0, r, r, r);
    g.addColorStop(0, "rgba(0,0,0,1)"); g.addColorStop(0.4, "rgba(0,0,0,.7)"); g.addColorStop(0.75, "rgba(0,0,0,.25)"); g.addColorStop(1, "rgba(0,0,0,0)");
    x.fillStyle = g; x.fillRect(0, 0, s.width, s.height);
    return s;
  }
  function rampPalette(colors) {
    var c = document.createElement("canvas"), x = c.getContext("2d"), g;
    c.width = 256; c.height = 1;
    g = x.createLinearGradient(0, 0, 256, 0);
    [[0, 0, 0], [0.12, 0, 0.65], [0.35, 1, 0.85], [0.75, 2, 0.92], [1, 2, 0.95]].forEach(function (s) { g.addColorStop(s[0], rgba(colors[s[1]], s[2])); });
    x.fillStyle = g; x.fillRect(0, 0, 256, 1);
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
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    map.createPane("density").style.zIndex = 350;
    state.layers.density = new (makeDensityLayer())({ pane: "density" }).addTo(map);
    ["ashore", "sites", "reports"].forEach(function (k) { state.layers[k] = L.layerGroup().addTo(map); });
    if (window.ResizeObserver) new ResizeObserver(function () { map.invalidateSize(); }).observe($("map"));
    map.on("zoomend", drawMarkers);
  }

  function ramp() { return [css("--clear"), css("--r1"), css("--r2"), css("--r3")]; }
  function hash(a, b, i) { var x = Math.sin(a * 12.9898 + b * 78.233 + i * 37.719) * 43758.5453; return x - Math.floor(x); }

  function drawMap() {
    if (!state.map || !state.data) return;
    var d = state.data, day = state.day, cell = d.settings.cell_deg, pts;
    if (day === 0) {
      // Spread each detection the way the pipeline seeds particles (1 to 3 per pixel,
      // inside the cell), so day 0 and the forecast days share one look.
      pts = [];
      d.detections.forEach(function (c) {
        for (var i = 0, n = 1 + Math.min(2, Math.floor(c[2] / 0.001)); i < n; i++) {
          pts.push([c[0] + (hash(c[0], c[1], 2 * i) - 0.5) * cell, c[1] + (hash(c[0], c[1], 2 * i + 1) - 0.5) * cell, 0.45]);
        }
      });
    } else {
      pts = d.forecast[day].filter(function (p) { return p[2] === 0; }).map(function (p) { return [p[0], p[1], 0.45]; });
    }
    state.layers.density.setData(pts, cell, ramp().slice(1));
    drawMarkers();
  }

  function drawMarkers() {
    if (!state.map || !state.data) return;
    var d = state.data, day = state.day, Lr = state.layers, panel = css("--panel"), ink = css("--ink"), colors = ramp(), levels = t("levels");
    var zoom = state.map.getZoom(), size = zoom >= 12 ? 7 : zoom >= 11 ? 5.5 : 4;
    Lr.ashore.clearLayers(); Lr.sites.clearLayers(); Lr.reports.clearLayers(); state.markers = {};
    if (day > 0) d.forecast[day].forEach(function (p) {
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
  var VIEWS = ["beaches", "managers", "data"];
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
    var head = ["id", "name", "side", "lat", "lon"].concat(days, days.map(function (x) { return x + " " + t("csvParticles"); }));
    var rows = d.sites.map(function (s) {
      return [s.id, s.name, s.side || "", coord(s.lat), coord(s.lon)].concat(s.risk.map(function (r) { return levels[r]; }), s.count);
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
      [[t("dAfai"), s.afai, fmtDate(s.afai.time) + (s.afai.age_days != null ? " (" + ageText(s.afai.age_days) + ")" : "")],
       [t("dCurrents"), s.currents, s.currents.fallback ? t("fallback") : fmtDate(s.currents.time) + (s.currents.age_days != null ? " (" + ageText(s.currents.age_days) + ")" : "")],
       [t("dLand"), s.land, s.land.available ? "" : t("unavailable")],
       [t("dWind"), { name: t("constantWind") }, ""]].forEach(function (r) {
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
    ["l1", "l2", "l3", "l4", "l5"].forEach(function (k) { lim.appendChild(el("li", null, t(k))); });
  }

  function renderAll() {
    renderStatic(); renderNotices(); renderHeadline(); renderDays(); renderCaption();
    renderSites(); renderReports(); renderData(); renderPlay(); renderManagers(); renderDocs(); drawMap();
  }

  function getJSON(url) { return fetch(url, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(url + " " + r.status); return r.json(); }); }

  pickLang(); renderStatic(); renderHeadline(); renderPlay(); renderDocs(); showView();
  window.addEventListener("hashchange", function () { showView(); window.scrollTo(0, 0); });
  $("csv").addEventListener("click", downloadCSV);
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
