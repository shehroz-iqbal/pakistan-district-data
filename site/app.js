/* Pakistan district data: dashboard.
 *
 * Reads three files written by the pipeline (pipeline/export.py):
 *   data/dashboard.json         indicator definitions and every value
 *   data/districts_2023.geojson map shapes (one per district; Karachi's seven as one)
 *   data/provinces_2023.geojson province outlines
 * Everything is drawn with D3 (vendor/d3.min.js); no other dependencies.
 */
(function () {
  "use strict";

  const PROVINCE_ORDER = ["PB", "SD", "KP", "BA", "IS"];
  const SHORT = { PB: "Punjab", SD: "Sindh", KP: "Khyber Pakhtunkhwa", BA: "Balochistan", IS: "Islamabad" };
  const DEFAULT_DISTRICT = "pb_lahore";

  const state = { indicator: "literacy_rate", province: "", selected: DEFAULT_DISTRICT,
                  sort: { key: "value", dir: "desc" } };

  let DATA, SHAPES, PROVINCES;
  let IND = {};           // indicator_id -> definition
  let MAPPABLE = [];      // indicators that are rates/ratios (counts don't belong on a choropleth)
  let DISTRICTS = [];     // [{id, name, province, mapUnit}]
  let RANKS = {};         // indicator_id -> {district_id: rank}
  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- formatting
  const comma = d3.format(",");
  function fmt(value, ind, long) {
    if (value == null || Number.isNaN(value)) return "–";
    const d = ind.decimals;
    switch (ind.unit) {
      case "people": return comma(Math.round(value));
      case "km²": return comma(Math.round(value)) + " km²";
      case "people per km²": return comma(Math.round(value)) + (long ? " per km²" : "");
      case "% per year": return value.toFixed(d) + "%" + (long ? " a year" : "");
      case "percentage points": return value.toFixed(d) + (long ? " percentage points" : " pts");
      case "males per 100 females": return value.toFixed(d) + (long ? " males per 100 females" : "");
      case "persons": return value.toFixed(d);
      default: return value.toFixed(d) + "%"; // every other unit is a percentage
    }
  }
  function compact(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 1 : 2) + "m";
    if (n >= 1e3) return Math.round(n / 1e3) + "k";
    return String(n);
  }
  function ordinal(n) {
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "text") node.textContent = v;
      else if (k === "class") node.className = v;
      else node.setAttribute(k, v);
    }
    for (const c of children || []) node.append(c);
    return node;
  }
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const place = (id) => DATA.places[id];
  const value = (id, ind) => (place(id) && place(id).values[ind]);

  // ---------------------------------------------------------------- boot
  Promise.all([
    fetch("data/dashboard.json").then((r) => r.json()),
    fetch("data/districts_2023.geojson").then((r) => r.json()),
    fetch("data/provinces_2023.geojson").then((r) => r.json()),
  ]).then(([data, shapes, provinces]) => {
    DATA = data; SHAPES = shapes; PROVINCES = provinces;
    // The files follow RFC 7946 (outer rings counter-clockwise); d3-geo wants the reverse.
    for (const f of [...SHAPES.features, ...PROVINCES.features]) rewind(f.geometry);
    for (const ind of DATA.indicators) IND[ind.indicator_id] = ind;
    MAPPABLE = DATA.indicators.filter((i) => !["people", "km²"].includes(i.unit));
    DISTRICTS = Object.entries(DATA.places)
      .filter(([, p]) => p.level === "district")
      .map(([id, p]) => ({ id, name: p.name, province: p.province, mapUnit: p.map_unit }))
      .sort((a, b) => a.name.localeCompare(b.name));
    for (const ind of DATA.indicators) {
      const sorted = DISTRICTS.map((d) => [d.id, value(d.id, ind.indicator_id)])
        .sort((a, b) => b[1] - a[1]);
      RANKS[ind.indicator_id] = Object.fromEntries(sorted.map(([id], i) => [id, i + 1]));
    }
    readHash();
    buildChrome();
    buildMap();
    renderAll();
    new ResizeObserver(() => { layoutMap(); renderStrip(); }).observe($("map-wrap"));
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderAll);
    addEventListener("hashchange", () => {
      readHash();
      state.province = ""; $("province").value = ""; $("search").value = "";
      renderAll();
      zoomToUnit(mapUnitOf(state.selected));
    });
  }).catch((err) => {
    $("map-title").textContent = "Could not load the data.";
    $("map-sub").textContent = "Open this page through a web server (for example `make serve`), not as a file. " + err;
  });

  function rewind(geom) {
    const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.type === "MultiPolygon" ? geom.coordinates : [];
    for (const rings of polys) for (const ring of rings) ring.reverse();
  }

  // Selected state lives in the URL hash so a view can be shared: #literacy_rate/pb_lahore
  function readHash() {
    const [ind, sel] = decodeURIComponent(location.hash.slice(1)).split("/");
    if (ind && IND[ind] && MAPPABLE.includes(IND[ind])) state.indicator = ind;
    if (sel && DATA.places[sel] && ["district", "map_unit"].includes(DATA.places[sel].level)) state.selected = sel;
  }
  function writeHash() {
    history.replaceState(null, "", `#${state.indicator}/${state.selected}`);
  }

  // ---------------------------------------------------------------- page chrome
  function buildChrome() {
    const qa = DATA.qa_summary || "";
    const badge = $("qa-badge");
    const m = qa.match(/(\d+) of (\d+)/);
    badge.textContent = m ? `${m[1]} of ${m[2]} data checks pass` : "Data checks";
    if (m && m[1] !== m[2]) badge.classList.add("fail");
    const pinned = new Date(DATA.sources_pinned + "T00:00:00");
    $("pinned").textContent = "Sources pinned " + pinned.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
    const repo = repoUrl();
    if (repo) { const a = $("repo-link"); a.href = repo; a.hidden = false; }

    const select = $("indicator");
    const themes = d3.group(MAPPABLE, (i) => i.theme);
    for (const [theme, inds] of themes) {
      const group = el("optgroup", { label: theme });
      for (const i of inds) group.append(el("option", { value: i.indicator_id, text: i.label }));
      select.append(group);
    }
    select.value = state.indicator;
    select.addEventListener("change", () => { state.indicator = select.value; renderAll(); });

    const prov = $("province");
    for (const code of PROVINCE_ORDER) prov.append(el("option", { value: code, text: DATA.provinces[code] }));
    prov.addEventListener("change", () => { setProvince(prov.value); });

    const list = $("district-list");
    for (const d of DISTRICTS) list.append(el("option", { value: d.name }));
    const search = $("search");
    search.addEventListener("input", () => {
      const hit = DISTRICTS.find((d) => d.name.toLowerCase() === search.value.trim().toLowerCase());
      if (hit) { select_(hit.id, true, true); } else { renderTable(); }
    });

    // Clicking a header sorts by it; clicking again reverses. Text and rank start
    // ascending (A-Z, 1st first); numbers start descending (largest first).
    const firstDir = { rank: "asc", name: "asc", province: "asc", population: "desc", value: "desc" };
    document.querySelectorAll("#table th").forEach((th) => th.addEventListener("click", () => {
      const key = th.dataset.sort;
      const dir = state.sort.key === key ? (state.sort.dir === "asc" ? "desc" : "asc") : firstDir[key];
      state.sort = { key, dir };
      renderTable();
    }));
  }

  function repoUrl() {
    const host = location.hostname;
    if (!host.endsWith(".github.io")) return null;
    const user = host.split(".")[0];
    const repo = location.pathname.split("/").filter(Boolean)[0] || `${user}.github.io`;
    return `https://github.com/${user}/${repo}`;
  }

  function setProvince(code) {
    state.province = code;
    $("province").value = code;
    renderAll();
    zoomToProvince(code);
  }

  function select_(id, zoom, fromSearch) {
    state.selected = id;
    if (!fromSearch) $("search").value = "";
    // Picking a district outside the province filter lifts the filter.
    if (state.province && place(id).province !== state.province) {
      state.province = "";
      $("province").value = "";
      renderAll();
    } else {
      renderSelection();
    }
    if (zoom) zoomToUnit(mapUnitOf(id));
  }
  const mapUnitOf = (id) => (place(id).level === "district" ? place(id).map_unit : id);

  function renderAll() {
    $("indicator").value = state.indicator;
    renderKpis();
    renderMapColours();
    renderLegend();
    renderStrip();
    renderSelection();
    renderNotes();
  }
  function renderSelection() {
    renderMapSelection();
    renderProfile();
    renderStripSelection();
    renderTable();
    writeHash();
  }

  // ---------------------------------------------------------------- KPI row
  function renderKpis() {
    const ind = IND[state.indicator];
    const box = $("kpis");
    box.replaceChildren();
    const tiles = [["PK", "Pakistan"], ...PROVINCE_ORDER.map((c) => [c, SHORT[c]])];
    for (const [code, label] of tiles) {
      const tile = el("button", { type: "button", class: "kpi" + (code === "PK" ? " national" : "") +
        ((state.province === code || (code === "PK" && !state.province)) ? " active" : "") }, [
        el("div", { class: "label", text: label }),
        el("div", { class: "value", text: fmt(value(code, state.indicator), ind) }),
      ]);
      tile.addEventListener("click", () => setProvince(code === "PK" || state.province === code ? "" : code));
      tile.setAttribute("aria-label", `${label}: ${fmt(value(code, state.indicator), ind, true)}. Show ${code === "PK" ? "all of Pakistan" : label} on the map.`);
      box.append(tile);
    }
  }

  // ---------------------------------------------------------------- map
  let svg, gRoot, gUnits, gProv, gSel, gLabels, projection, path, zoom, width = 600, height = 560;

  function buildMap() {
    svg = d3.select("#map");
    gRoot = svg.append("g");
    gUnits = gRoot.append("g");
    gProv = gRoot.append("g");
    gSel = gRoot.append("g");
    gLabels = gRoot.append("g");
    projection = d3.geoConicEqualArea().parallels([25, 36]).rotate([-69.5, 0]);
    path = d3.geoPath(projection);

    gUnits.selectAll("path").data(SHAPES.features).join("path")
      .attr("class", (f) => "unit" + (f.properties.in_census_tables ? "" : " nodata"))
      .on("pointermove", (event, f) => showTip(event, f.properties.map_unit_id))
      .on("pointerleave", hideTip)
      .on("click", (event, f) => { if (f.properties.in_census_tables) select_(f.properties.map_unit_id, false); });
    gProv.selectAll("path").data(PROVINCES.features).join("path").attr("class", "province-line");
    gLabels.selectAll("text").data(PROVINCES.features).join("text")
      .attr("class", "map-label").attr("text-anchor", "middle")
      .text((f) => ({ ajk: "AJK", gb: "Gilgit-Baltistan", IS: "" }[f.properties.province_code] ?? f.properties.name));

    zoom = d3.zoom().scaleExtent([1, 18]).on("zoom", (event) => {
      gRoot.attr("transform", event.transform);
      gLabels.selectAll("text").style("font-size", 11 / event.transform.k + "px");
    });
    svg.call(zoom).on("dblclick.zoom", null);
    $("zoom-in").addEventListener("click", () => svg.transition().duration(300).call(zoom.scaleBy, 1.6));
    $("zoom-out").addEventListener("click", () => svg.transition().duration(300).call(zoom.scaleBy, 1 / 1.6));
    $("zoom-reset").addEventListener("click", () => setProvince(""));
    layoutMap();
  }

  function layoutMap() {
    const box = $("map-wrap").getBoundingClientRect();
    width = Math.max(280, box.width); height = Math.max(260, box.height);
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    projection.fitExtent([[8, 8], [width - 8, height - 8]], SHAPES);
    gUnits.selectAll("path").attr("d", path);
    gProv.selectAll("path").attr("d", path);
    gLabels.selectAll("text").attr("transform", (f) => {
      const [x, y] = path.centroid(f);
      const nudge = { KP: [8, 10], PB: [10, 6], gb: [0, -4] }[f.properties.province_code] || [0, 0];
      return `translate(${x + nudge[0]},${y + nudge[1]})`;
    });
    zoom.extent([[0, 0], [width, height]]).translateExtent([[-width * 0.25, -height * 0.25], [width * 1.25, height * 1.25]]);
    renderMapSelection();
  }

  function classScale() {
    const vals = DISTRICTS.map((d) => value(d.id, state.indicator)).filter((v) => v != null);
    const colours = ["--c1", "--c2", "--c3", "--c4", "--c5"].map(cssVar);
    return d3.scaleQuantile().domain(vals).range(colours);
  }

  function renderMapColours() {
    const scale = classScale();
    const nodata = cssVar("--nodata");
    gUnits.selectAll("path")
      .attr("fill", (f) => {
        if (!f.properties.in_census_tables) return nodata;
        const v = value(f.properties.map_unit_id, state.indicator);
        return v == null ? nodata : scale(v);
      })
      .classed("dim", (f) => !!state.province && f.properties.province_code !== state.province);
    $("map-title").textContent = IND[state.indicator].label + ", by district";
    $("map-sub").textContent = "Darker means a higher value. Colours split the 136 districts into five equal-sized groups.";
  }

  function renderMapSelection() {
    if (!gSel) return;
    const unit = state.selected ? mapUnitOf(state.selected) : null;
    const feats = SHAPES.features.filter((f) => f.properties.map_unit_id === unit);
    gSel.selectAll("path").data(feats).join("path").attr("class", "selected").attr("d", path);
  }

  function zoomTo(features) {
    if (!features.length) { svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity); return; }
    const [[x0, y0], [x1, y1]] = path.bounds({ type: "FeatureCollection", features });
    const k = Math.min(12, 0.85 / Math.max((x1 - x0) / width, (y1 - y0) / height));
    const t = d3.zoomIdentity.translate(width / 2, height / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
    svg.transition().duration(600).call(zoom.transform, t);
  }
  function zoomToProvince(code) {
    zoomTo(code ? SHAPES.features.filter((f) => f.properties.province_code === code) : []);
  }
  function zoomToUnit(unit) {
    const f = SHAPES.features.find((x) => x.properties.map_unit_id === unit);
    if (!f) return;
    const [[x0, y0], [x1, y1]] = path.bounds(f);
    const t = d3.zoomTransform(svg.node());
    const [sx0, sy0] = t.apply([x0, y0]);
    const [sx1, sy1] = t.apply([x1, y1]);
    const inView = sx0 >= 0 && sy0 >= 0 && sx1 <= width && sy1 <= height;
    const bigEnough = Math.max(sx1 - sx0, sy1 - sy0) >= 18;
    if (inView && bigEnough) return; // already easy to see: leave the map alone
    // Centre it, zoomed so the shape spans about a fifth of the map.
    const k = Math.min(12, Math.max(t.k, 0.2 / Math.max((x1 - x0) / width, (y1 - y0) / height)));
    const next = d3.zoomIdentity.translate(width / 2, height / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
    svg.transition().duration(600).call(zoom.transform, next);
  }

  // ---------------------------------------------------------------- legend
  function renderLegend() {
    const ind = IND[state.indicator];
    const scale = classScale();
    const vals = scale.domain();
    const edges = [d3.min(vals), ...scale.quantiles(), d3.max(vals)];
    const box = $("legend");
    box.replaceChildren();
    // Five swatches with the class boundaries printed at the joins.
    const swatches = el("div", { class: "swatches", "aria-hidden": "true" });
    for (const colour of scale.range()) {
      const sw = el("span"); sw.style.background = colour; swatches.append(sw);
    }
    const ticks = el("div", { class: "ticks", "aria-hidden": "true" });
    edges.forEach((edge, i) => {
      const t = el("span", { text: fmt(edge, ind) });
      t.style.left = (i * 100) / (edges.length - 1) + "%";
      ticks.append(t);
    });
    const described = edges.slice(0, -1).map((e, i) => `${fmt(e, ind)} to ${fmt(edges[i + 1], ind)}`).join("; ");
    box.append(el("div", { class: "scale", role: "img", "aria-label": `Five colour classes, lightest to darkest: ${described}.` },
                  [swatches, ticks]));
    box.append(el("span", { class: "nd" }, [el("i"), document.createTextNode("Not in these census tables (AJK, Gilgit-Baltistan)")]));
    box.append(el("span", { class: "note", text: "Karachi's seven districts are drawn as one shape; the table and profile list each one." }));
  }

  // ---------------------------------------------------------------- tooltip
  const tip = () => $("tooltip");
  function showTip(event, id) {
    const t = tip();
    t.replaceChildren();
    const p = place(id);
    if (!p) {
      const f = SHAPES.features.find((x) => x.properties.map_unit_id === id);
      t.append(el("div", { class: "tn", text: f ? f.properties.name : id }),
               el("div", { class: "tm", text: "Not covered by the PBS census tables used here." }));
    } else {
      const ind = IND[state.indicator];
      t.append(el("div", { class: "tv", text: fmt(p.values[state.indicator], ind, true) }),
               el("div", { class: "tn", text: p.name }));
      if (p.level === "map_unit") {
        t.append(el("div", { class: "tm", text: `${DATA.provinces[p.province]} · ${p.districts.length} districts combined. Click to list them.` }));
      } else {
        const rank = RANKS[state.indicator][id];
        t.append(el("div", { class: "tm", text: `${DATA.provinces[p.province]} · ${ordinal(rank)} highest of ${DISTRICTS.length} districts` }));
      }
    }
    t.hidden = false;
    const pad = 14, w = t.offsetWidth, h = t.offsetHeight;
    let x = event.clientX + pad, y = event.clientY + pad;
    if (x + w > innerWidth - 8) x = event.clientX - w - pad;
    if (y + h > innerHeight - 8) y = event.clientY - h - pad;
    t.style.left = Math.max(8, x) + "px"; t.style.top = Math.max(8, y) + "px";
  }
  function hideTip() { tip().hidden = true; }

  // ---------------------------------------------------------------- profile
  function renderProfile() {
    const box = $("profile");
    box.replaceChildren();
    const id = state.selected;
    const p = place(id);
    if (!p) return;
    const provCode = p.province;
    const header = el("header", {}, [el("h2", { text: p.name }),
      el("p", { class: "sub", text: p.level === "map_unit" ? `${DATA.provinces[provCode]} · ${p.districts.length} districts combined`
                                                            : DATA.provinces[provCode] + (p.map_unit !== id ? " · Karachi division" : "") })]);
    const facts = el("div", { class: "facts" });
    const factPairs = [["population", "Population"], ["area", "Area"], ["density", "Density"], ["growth_rate", "Growth"]];
    for (const [k, label] of factPairs) {
      const v = p.values[k];
      facts.append(el("span", {}, [document.createTextNode(label + " "), el("b", { text: k === "population" ? compact(v) : fmt(v, IND[k], k !== "area") })]));
    }
    header.append(facts);
    if (p.level === "map_unit") {
      const ul = el("ul", { class: "members" });
      for (const d of p.districts) {
        const b = el("button", { type: "button", text: place(d).name });
        b.addEventListener("click", () => select_(d, false));
        ul.append(el("li", {}, [b]));
      }
      header.append(ul);
    }
    header.append(el("div", { class: "key" }, [
      el("span", {}, [el("i", { class: "k-dot" }), document.createTextNode(" " + (p.level === "map_unit" ? "Karachi" : "This district"))]),
      el("span", {}, [el("i", { class: "k-prov" }), document.createTextNode(" " + SHORT[provCode])]),
      el("span", {}, [el("i", { class: "k-pk" }), document.createTextNode(" Pakistan")]),
      el("span", { text: "Each line ranks all 136 districts, lowest on the left." }),
    ]));
    box.append(header);

    // One collapsible section per theme. On wide screens all start open; on
    // phones only the section holding the mapped indicator does.
    const rows = el("div", { class: "rows" });
    const wide = innerWidth > 1000;
    for (const [theme, inds] of d3.group(MAPPABLE, (i) => i.theme)) {
      const section = el("details", {}, [el("summary", { text: `${theme} (${inds.length})` })]);
      section.open = wide || inds.some((i) => i.indicator_id === state.indicator);
      for (const ind of inds) section.append(profileRow(id, p, ind));
      rows.append(section);
    }
    box.append(rows);
    // Bring the mapped indicator into view inside the panel (not the page).
    const current = rows.querySelector(".current");
    if (current && wide) rows.scrollTop = Math.max(0, current.offsetTop - rows.offsetTop - 60);
  }

  // Position of a value among the sorted district values, 0-100 (interpolated),
  // so every line spreads the districts evenly however skewed the numbers are.
  const SORTED = {};
  function rankPosition(k, v) {
    const s = SORTED[k] || (SORTED[k] = DISTRICTS.map((d) => value(d.id, k)).sort(d3.ascending));
    const n = s.length;
    if (v <= s[0]) return 0;
    if (v >= s[n - 1]) return 100;
    const i = d3.bisectRight(s, v);
    const frac = s[i] === s[i - 1] ? 0 : (v - s[i - 1]) / (s[i] - s[i - 1]);
    return ((i - 1 + frac) / (n - 1)) * 100;
  }

  function profileRow(id, p, ind) {
    const k = ind.indicator_id;
    const pos = (v) => rankPosition(k, v) + "%";
    const v = p.values[k], vProv = value(p.province, k), vPk = value("PK", k);
    const track = el("div", { class: "track", "aria-hidden": "true" });
    const tProv = el("span", { class: "tk prov" }); tProv.style.left = pos(vProv);
    const tPk = el("span", { class: "tk pk" }); tPk.style.left = pos(vPk);
    const dot = el("span", { class: "dot" }); dot.style.left = pos(v);
    track.append(tProv, tPk, dot);
    const rank = p.level === "district" ? ` · ${ordinal(RANKS[k][id])} highest of ${DISTRICTS.length}` : "";
    const row = el("div", { class: "ind-row" + (k === state.indicator ? " current" : ""), tabindex: "0", role: "button",
      "aria-label": `${ind.label}: ${fmt(v, ind, true)}. ${SHORT[p.province]} ${fmt(vProv, ind, true)}, Pakistan ${fmt(vPk, ind, true)}. Show on the map.` }, [
      el("span", { class: "name", text: ind.label }),
      el("span", { class: "val", text: fmt(v, ind) }),
      track,
      el("span", { class: "ctx", text: `${SHORT[p.province]} ${fmt(vProv, ind)} · Pakistan ${fmt(vPk, ind)}${rank}` }),
    ]);
    const go = () => { state.indicator = k; renderAll(); };
    row.addEventListener("click", go);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    return row;
  }

  // ---------------------------------------------------------------- strip plot
  let stripDots = [], stripX, stripDelaunay;
  function renderStrip() {
    if (!DATA) return;
    const ind = IND[state.indicator];
    const wrap = $("strip-wrap");
    const w = Math.max(300, wrap.clientWidth);
    const narrow = w < 560;
    const labelW = narrow ? 92 : 150, r = narrow ? 3.5 : 4.5, top = 26, axisH = 26;
    const vals = DISTRICTS.map((d) => value(d.id, state.indicator));
    stripX = d3.scaleLinear().domain(d3.extent(vals)).nice().range([labelW + r + 4, w - r - 10]);

    // Beeswarm: within each province row, nudge dots up/down until they don't overlap.
    const rows = PROVINCE_ORDER.map((code) => {
      const members = DISTRICTS.filter((d) => d.province === code)
        .map((d) => ({ ...d, v: value(d.id, state.indicator), x: stripX(value(d.id, state.indicator)) }))
        .sort((a, b) => a.x - b.x);
      const placed = [];
      for (const m of members) {
        for (let i = 0; ; i++) {
          const dy = (i % 2 ? 1 : -1) * Math.ceil(i / 2) * (2 * r + 1);
          if (!placed.some((o) => Math.abs(o.x - m.x) < 2 * r + 1 && Math.abs(o.dy - dy) < 2 * r + 1)) { m.dy = dy; break; }
        }
        placed.push(m);
      }
      const spread = d3.max(members, (m) => Math.abs(m.dy)) || 0;
      return { code, members, h: Math.max(34, 2 * spread + 2 * r + 14) };
    });
    let y = top;
    for (const row of rows) { row.y0 = y; row.cy = y + row.h / 2; y += row.h; }
    const H = y + axisH;

    const s = d3.select("#strip").attr("viewBox", `0 0 ${w} ${H}`).attr("height", H);
    s.selectAll("*").remove();
    const gx = s.append("g").attr("class", "axis").attr("transform", `translate(0,${y})`)
      .call(d3.axisBottom(stripX).ticks(narrow ? 4 : 8).tickSize(-(y - top)).tickFormat((v) => fmt(v, ind)));
    gx.select(".domain").remove();

    for (const row of rows) {
      const g = s.append("g");
      g.append("text").attr("class", "row-label").attr("x", 0).attr("y", row.cy - 3).text(SHORT[row.code]);
      g.append("text").attr("class", "lbl-muted").attr("x", 0).attr("y", row.cy + 12).text(fmt(value(row.code, state.indicator), ind));
      const pv = value(row.code, state.indicator);
      g.append("line").attr("class", "prov").attr("x1", stripX(pv)).attr("x2", stripX(pv))
        .attr("y1", row.y0 + 4).attr("y2", row.y0 + row.h - 4);
    }
    const pk = value("PK", state.indicator);
    s.append("line").attr("class", "pk").attr("x1", stripX(pk)).attr("x2", stripX(pk)).attr("y1", top - 6).attr("y2", y);
    s.append("text").attr("class", "lbl-muted").attr("x", stripX(pk)).attr("y", top - 10).attr("text-anchor", "middle")
      .text("Pakistan " + fmt(pk, ind));

    stripDots = rows.flatMap((row) => row.members.map((m) => ({ ...m, cy: row.cy + m.dy })));
    s.append("g").selectAll("circle").data(stripDots).join("circle")
      .attr("class", "d").attr("r", r).attr("cx", (d) => d.x).attr("cy", (d) => d.cy);
    s.append("g").attr("class", "sel-layer");
    stripDelaunay = d3.Delaunay.from(stripDots, (d) => d.x, (d) => d.cy);
    s.on("pointermove", (event) => {
      const [mx, my] = d3.pointer(event);
      const i = stripDelaunay.find(mx, my);
      const d = stripDots[i];
      if (!d || Math.hypot(d.x - mx, d.cy - my) > 24) { hideTip(); s.selectAll("circle.d").classed("hover", false); return; }
      s.selectAll("circle.d").classed("hover", (o) => o.id === d.id);
      showTip(event, d.id);
    }).on("pointerleave", () => { hideTip(); s.selectAll("circle.d").classed("hover", false); })
      .on("click", (event) => {
        const [mx, my] = d3.pointer(event);
        const d = stripDots[stripDelaunay.find(mx, my)];
        if (d && Math.hypot(d.x - mx, d.cy - my) <= 24) select_(d.id, true);
      });
    $("strip-sub").textContent = `${IND[state.indicator].label}. Each dot is a district; the bold tick marks the province figure and the thin line Pakistan's.`;
    renderStripSelection();
  }

  function renderStripSelection() {
    const s = d3.select("#strip");
    if (!stripDots.length) return;
    const selDistricts = place(state.selected).level === "map_unit" ? place(state.selected).districts : [state.selected];
    s.selectAll("circle.d")
      .classed("sel", (d) => selDistricts.includes(d.id))
      .classed("dim", (d) => !!state.province && d.province !== state.province);
    s.selectAll("circle.d.sel").raise();
    const layer = s.select("g.sel-layer");
    layer.selectAll("*").remove();
    if (selDistricts.length === 1) {
      const d = stripDots.find((o) => o.id === selDistricts[0]);
      if (d) {
        const right = d.x < (stripX.range()[0] + stripX.range()[1]) / 2;
        layer.append("text").attr("class", "lbl").attr("x", d.x + (right ? 9 : -9)).attr("y", d.cy - 7)
          .attr("text-anchor", right ? "start" : "end").text(d.name);
      }
    }
  }

  // ---------------------------------------------------------------- table
  function renderTable() {
    const ind = IND[state.indicator];
    // Typing part of a name narrows the table; a complete name selects that
    // district instead (see buildChrome), so the full list stays in view.
    let q = $("search").value.trim().toLowerCase();
    if (DISTRICTS.some((d) => d.name.toLowerCase() === q)) q = "";
    let rows = DISTRICTS.filter((d) => (!state.province || d.province === state.province) &&
                                       (!q || d.name.toLowerCase().includes(q)));
    const key = state.sort.key, dir = state.sort.dir === "asc" ? 1 : -1;
    const get = {
      rank: (d) => RANKS[state.indicator][d.id],
      name: (d) => d.name, province: (d) => SHORT[d.province],
      population: (d) => value(d.id, "population"), value: (d) => value(d.id, state.indicator),
    }[key];
    rows = rows.slice().sort((a, b) => {
      const A = get(a), B = get(b);
      return (typeof A === "string" ? A.localeCompare(B) : A - B) * dir;
    });
    const max = d3.max(DISTRICTS, (d) => value(d.id, state.indicator));
    const selDistricts = place(state.selected).level === "map_unit" ? place(state.selected).districts : [state.selected];
    const body = document.querySelector("#table tbody");
    body.replaceChildren();
    for (const d of rows) {
      const v = value(d.id, state.indicator);
      const bar = el("span", { class: "bar", "aria-hidden": "true" });
      bar.style.width = Math.max(1, (v / max) * 110) + "px";
      const tr = el("tr", { tabindex: "0", class: selDistricts.includes(d.id) ? "selected" : "" }, [
        el("td", { class: "num", text: RANKS[state.indicator][d.id] }),
        el("td", { text: d.name }),
        el("td", { text: SHORT[d.province] }),
        el("td", { class: "num", text: comma(value(d.id, "population")) }),
        el("td", { class: "num value-cell" }, [bar, document.createTextNode(fmt(v, ind))]),
      ]);
      const go = () => select_(d.id, true);
      tr.addEventListener("click", go);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
      body.append(tr);
    }
    const selRow = body.querySelector("tr.selected");
    const scroller = document.querySelector(".table-scroll");
    if (selRow) {
      const top = selRow.offsetTop, bottom = top + selRow.offsetHeight;
      if (top < scroller.scrollTop + 36 || bottom > scroller.scrollTop + scroller.clientHeight) {
        scroller.scrollTop = Math.max(0, top - scroller.clientHeight / 2);
      }
    }
    $("value-col").textContent = ind.label;
    $("table-title").textContent = (state.province ? DATA.provinces[state.province] + ": " : "All ") +
      `${rows.length} districts`;
    document.querySelectorAll("#table th").forEach((th) => {
      th.setAttribute("aria-sort", th.dataset.sort === key ? (state.sort.dir === "asc" ? "ascending" : "descending") : "none");
    });
  }

  // ---------------------------------------------------------------- notes
  function renderNotes() {
    const ind = IND[state.indicator];
    const repo = repoUrl();
    const link = (text, href) => (href ? el("a", { href, text }) : document.createTextNode(text));
    const doc = (file) => (repo ? `${repo}/blob/main/${file}` : null);
    const box = $("notes");
    box.replaceChildren(
      el("div", {}, [
        el("h3", { text: ind.label }),
        el("p", { text: ind.definition }),
        el("p", { text: `Unit: ${ind.unit}. Source: PBS Census 2023, ${ind.source_table}. Province and Pakistan figures are rebuilt from district counts, not averaged.` }),
      ]),
      el("div", {}, [
        el("h3", { text: "Where the numbers come from" }),
        el("p", {}, [document.createTextNode("Pakistan Bureau of Statistics, "),
          link("7th Population and Housing Census 2023", DATA.sources.census.url),
          document.createTextNode(", district tables, as converted from PDF to CSV by "),
          link("Fahad Mirza", DATA.sources.census.conversion), document.createTextNode(" (MIT licence).")]),
        el("p", {}, [document.createTextNode("Two conversion errors are corrected, a third is worked around, and PBS's national headline figures are reproduced exactly; see the "),
          link("data quality report", doc("data/processed/QA.md")), document.createTextNode(".")]),
      ]),
      el("div", {}, [
        el("h3", { text: "About the map" }),
        el("p", {}, [document.createTextNode("District shapes are rebuilt from "),
          link("geoBoundaries", DATA.sources.boundaries.url),
          document.createTextNode(" tehsil polygons (ODbL). Parts of Balochistan were redrawn after that boundary data was made, so some shapes there are approximate; see the "),
          link("methodology", doc("docs/methodology.md")), document.createTextNode(".")]),
        el("p", { text: "Azad Jammu & Kashmir and Gilgit-Baltistan are shown for context; they are not part of these PBS census tables." }),
      ]),
    );
  }
})();
