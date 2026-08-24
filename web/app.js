// 枕草子アトラス — 4 ビュー(座標/解体/沈黙/升目)の描画。
// データはすべて data/*.json から読む(N-02: UI に集計済み定数を埋め込まない)。

const SVGNS = "http://www.w3.org/2000/svg";

const TYPE_LABEL = { zuiso: "随想", ruiju: "類聚", nikki: "日記" };
const TYPE_COLOR = { zuiso: "#46777d", ruiju: "#b0563a", nikki: "#6f5b9e" };
const CONF_LABEL = { high: "高", mid: "中", low: "低" };
const SEASONS = [
  { key: "haru", label: "春" },
  { key: "natsu", label: "夏" },
  { key: "aki", label: "秋" },
  { key: "fuyu", label: "冬" },
  { key: "tsuji", label: "通季" },
];
const TIMES = [
  { key: "akatsuki", label: "暁" },
  { key: "akebono", label: "あけぼの" },
  { key: "tsutomete", label: "つとめて" },
  { key: "hiru", label: "昼" },
  { key: "yugure", label: "夕暮" },
  { key: "yoru", label: "夜" },
];
const TONE_FILL = { bright: "#e9ddb8", neutral: "#d8cdb6", dark: "#b7a893" };

const state = {
  chapters: [],
  items: [],
  declared: [],
  events: [],
  tags: [],
  typeOn: new Set(["zuiso", "ruiju", "nikki"]),
  tagOn: new Set(),
  kaitaiChap: null,
};

async function loadJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}

function svgEl(tag, attrs = {}, text) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ---------------- 共通: ラベルの貪欲配置 ----------------
   置けた場所の占有ボックスを覚え、右→左→上→下の順に空きを探す。
   どこにも置けなければラベルは省略し、点のツールチップに委ねる。 */

function makeLabelPlacer() {
  const placed = [];
  const overlaps = (b) => placed.some(
    (p) => b.x < p.x + p.w && p.x < b.x + b.w && b.y < p.y + p.h && p.y < b.y + b.h);
  return function place(svg, x, y, text, anchorR = 8) {
    const w = text.length * 10.8 + 4;
    const h = 13;
    const candidates = [
      { x: x + anchorR + 2, y: y - h / 2, w, h, anchor: "start", tx: x + anchorR + 2, ty: y + 3.5 },
      { x: x - anchorR - 2 - w, y: y - h / 2, w, h, anchor: "end", tx: x - anchorR - 2, ty: y + 3.5 },
      { x: x - w / 2, y: y - anchorR - 3 - h, w, h, anchor: "middle", tx: x, ty: y - anchorR - 6 },
      { x: x - w / 2, y: y + anchorR + 3, w, h, anchor: "middle", tx: x, ty: y + anchorR + 13 },
    ];
    for (const c of candidates) {
      if (!overlaps(c)) {
        placed.push({ x: c.x, y: c.y, w, h });
        svg.appendChild(svgEl("text", {
          x: c.tx, y: c.ty, "text-anchor": c.anchor, class: "dot-label",
        }, text));
        return true;
      }
    }
    return false;
  };
}

/* ---------------- 共通: 二軸平面の骨格 ---------------- */

function drawPlane(svg, { cx, cy, hw, hh }) {
  svg.replaceChildren();
  // 象限のうすい色分け(快=右、覚醒=上)
  const quads = [
    { x: cx, y: cy - hh, f: "#f3ead2" }, // 右上 快×動
    { x: cx, y: cy, f: "#f6efdd" },      // 右下 快×静
    { x: cx - hw, y: cy - hh, f: "#efe4d6" }, // 左上 不快×動
    { x: cx - hw, y: cy, f: "#f1e9dc" },      // 左下 不快×静
  ];
  for (const q of quads) svg.appendChild(svgEl("rect", { x: q.x, y: q.y, width: hw, height: hh, fill: q.f }));
  svg.appendChild(svgEl("line", { x1: cx - hw, y1: cy, x2: cx + hw, y2: cy, class: "axis" }));
  svg.appendChild(svgEl("line", { x1: cx, y1: cy - hh, x2: cx, y2: cy + hh, class: "axis" }));
  svg.appendChild(svgEl("text", { x: cx + hw - 4, y: cy - 8, "text-anchor": "end", class: "axis-label" }, "快 →"));
  svg.appendChild(svgEl("text", { x: cx - hw + 4, y: cy - 8, class: "axis-label" }, "← 不快"));
  svg.appendChild(svgEl("text", { x: cx + 8, y: cy - hh + 14, class: "axis-label" }, "心が動く ↑"));
  svg.appendChild(svgEl("text", { x: cx + 8, y: cy + hh - 8, class: "axis-label" }, "心が静まる ↓"));
  const quadLabels = [
    { x: cx + hw - 10, y: cy - hh + 26, t: "ときめき・憤り", a: "end" },
    { x: cx + hw - 10, y: cy + hh - 20, t: "しみじみ・安らぎ", a: "end" },
    { x: cx - hw + 10, y: cy - hh + 26, t: "にくし・あさまし", a: "start" },
    { x: cx - hw + 10, y: cy + hh - 20, t: "すさまじ・つれづれ", a: "start" },
  ];
  for (const q of quadLabels)
    svg.appendChild(svgEl("text", { x: q.x, y: q.y, "text-anchor": q.a, class: "quad-label" }, q.t));
}

/* ---------------- 詳細パネル ---------------- */

function renderChapterDetail(container, c) {
  container.replaceChildren();
  const h = el("h3");
  h.append(c.title + " ");
  h.appendChild(el("span", { class: `type-badge ${c.type}` }, TYPE_LABEL[c.type]));
  container.appendChild(h);
  container.appendChild(el("div", { class: "tatext" }, c.excerpt));
  const tagline = el("p", { class: "tagline" });
  for (const t of c.tags) tagline.appendChild(el("span", {}, t));
  container.appendChild(tagline);
  const meta = el("dl", { class: "meta" });
  meta.appendChild(el("dt", {}, "座標(編者の解釈値)"));
  meta.appendChild(el("dd", {}, `快‐不快 ${c.v.toFixed(2)} ・ 心の動き ${c.a.toFixed(2)}`));
  if (c.type === "nikki") {
    meta.appendChild(el("dt", {}, `推定年: ${c.year_label}(確度 ${CONF_LABEL[c.dating_conf]})`));
    meta.appendChild(el("dd", {}, c.dating_basis));
  }
  if (c.note) {
    meta.appendChild(el("dt", {}, "編者メモ"));
    meta.appendChild(el("dd", {}, c.note));
  }
  container.appendChild(meta);
  if (state.declared.includes(c.id)) {
    const btn = el("button", { class: "chip", type: "button" }, "▶ この章段を解体する");
    btn.addEventListener("click", () => {
      state.kaitaiChap = c.id;
      switchView("kaitai");
      renderKaitai();
    });
    container.appendChild(btn);
  }
}

/* ---------------- 座標ビュー ---------------- */

function chapterVisible(c) {
  if (!state.typeOn.has(c.type)) return false;
  if (state.tagOn.size > 0 && !c.tags.some((t) => state.tagOn.has(t))) return false;
  return true;
}

function renderScatter() {
  const svg = document.getElementById("scatter");
  const geo = { cx: 372, cy: 308, hw: 330, hh: 270 };
  drawPlane(svg, geo);
  const X = (v) => geo.cx + v * (geo.hw - 18);
  const Y = (a) => geo.cy - a * (geo.hh - 18);
  const place = makeLabelPlacer();
  for (const c of state.chapters) {
    const visible = chapterVisible(c);
    const dot = svgEl("circle", {
      cx: X(c.v), cy: Y(c.a), r: 7.5,
      fill: TYPE_COLOR[c.type],
      class: "dot" + (visible ? "" : " is-dim"),
      "data-id": c.id,
    });
    dot.appendChild(svgEl("title", {}, `${c.title}(${TYPE_LABEL[c.type]})`));
    dot.addEventListener("click", () => {
      svg.querySelectorAll(".dot").forEach((d) => d.classList.remove("is-selected"));
      dot.classList.add("is-selected");
      renderChapterDetail(document.getElementById("detail-zahyo"), c);
    });
    svg.appendChild(dot);
    if (visible) {
      const short = c.title.length > 9 ? c.title.slice(0, 9) + "…" : c.title;
      place(svg, X(c.v), Y(c.a), short, 8);
    }
  }
}

function renderFilters() {
  const typeBox = document.getElementById("type-filter");
  typeBox.replaceChildren(el("span", { class: "axis-label" }, "型:"));
  for (const t of ["zuiso", "ruiju", "nikki"]) {
    const chip = el("button", { class: "chip is-on", type: "button", "data-type": t }, TYPE_LABEL[t]);
    chip.addEventListener("click", () => {
      if (state.typeOn.has(t)) state.typeOn.delete(t);
      else state.typeOn.add(t);
      chip.classList.toggle("is-on", state.typeOn.has(t));
      renderScatter();
    });
    typeBox.appendChild(chip);
  }
  const tagBox = document.getElementById("tag-filter");
  tagBox.replaceChildren(el("span", { class: "axis-label" }, "情緒語:"));
  for (const t of state.tags) {
    const chip = el("button", { class: "chip", type: "button" }, t);
    chip.addEventListener("click", () => {
      if (state.tagOn.has(t)) state.tagOn.delete(t);
      else state.tagOn.add(t);
      chip.classList.toggle("is-on", state.tagOn.has(t));
      renderScatter();
    });
    tagBox.appendChild(chip);
  }
}

/* ---------------- 解体ビュー ---------------- */

function renderKaitaiChips() {
  const box = document.getElementById("kaitai-chips");
  box.replaceChildren(el("span", { class: "axis-label" }, "章段:"));
  for (const id of state.declared) {
    const c = state.chapters.find((x) => x.id === id);
    const chip = el("button", { class: "chip" + (state.kaitaiChap === id ? " is-on" : ""), type: "button" }, c.title);
    chip.addEventListener("click", () => {
      state.kaitaiChap = id;
      renderKaitai();
    });
    box.appendChild(chip);
  }
}

function renderKaitai() {
  renderKaitaiChips();
  const svg = document.getElementById("kaitai-scatter");
  const geo = { cx: 372, cy: 308, hw: 330, hh: 270 };
  drawPlane(svg, geo);
  const X = (v) => geo.cx + v * (geo.hw - 18);
  const Y = (a) => geo.cy - a * (geo.hh - 18);
  const chap = state.chapters.find((x) => x.id === state.kaitaiChap);
  if (!chap) return;
  // 親章段: 破線の輪
  const parent = svgEl("circle", {
    cx: X(chap.v), cy: Y(chap.a), r: 13, class: "parent-dot", stroke: TYPE_COLOR.ruiju,
  });
  parent.appendChild(svgEl("title", {}, `${chap.title}(章段の座標)`));
  svg.appendChild(parent);
  svg.appendChild(svgEl("text", { x: X(chap.v) + 16, y: Y(chap.a) - 10, class: "dot-label" }, `${chap.title}(章段)`));
  // 項目
  const items = state.items.filter((i) => i.chapId === chap.id);
  items.forEach((i, idx) => {
    const dot = svgEl("circle", {
      cx: X(i.v), cy: Y(i.a), r: 6, fill: TYPE_COLOR.ruiju, class: "dot",
    });
    dot.appendChild(svgEl("title", {}, i.modern));
    dot.addEventListener("click", () => {
      svg.querySelectorAll(".dot").forEach((d) => d.classList.remove("is-selected"));
      dot.classList.add("is-selected");
      const box = document.getElementById("detail-kaitai");
      box.replaceChildren();
      const h = el("h3");
      h.append(`${chap.title} — 項目 ${idx + 1} `);
      h.appendChild(el("span", { class: "type-badge ruiju" }, "項目"));
      box.appendChild(h);
      box.appendChild(el("div", { class: "tatext" }, i.text));
      box.appendChild(el("p", { class: "modern-text" }, i.modern));
      const meta = el("dl", { class: "meta" });
      meta.appendChild(el("dt", {}, "座標(編者の解釈値)"));
      meta.appendChild(el("dd", {}, `快‐不快 ${i.v.toFixed(2)} ・ 心の動き ${i.a.toFixed(2)}`));
      box.appendChild(meta);
    });
    svg.appendChild(dot);
  });
  const note = document.getElementById("detail-kaitai");
  if (!note.querySelector("h3")) {
    note.replaceChildren(el("p", { class: "detail-empty" },
      `「${chap.title}」の項目 ${items.length} 件。破線の輪が章段としての座標、点が項目。点を選ぶと原文と現代語訳が出ます。`));
  }
}

/* ---------------- 沈黙ビュー ---------------- */

function renderTimeline() {
  const svg = document.getElementById("timeline");
  svg.replaceChildren();
  const x0 = 56, x1 = 736, yTop = 96, yBottom = 470;
  const t0 = 989.5, t1 = 1001.5;
  const X = (y) => x0 + ((y - t0) / (t1 - t0)) * (x1 - x0);
  const YC = (yTop + yBottom) / 2;
  const Y = (v) => YC - v * ((yBottom - yTop) / 2 - 12);

  // 時代の帯: 各史実からつぎの史実までを、その明暗で塗る(データから決定論に導出)
  const evs = state.events;
  for (let i = 0; i < evs.length; i++) {
    const from = X(evs[i].year);
    const to = i + 1 < evs.length ? X(evs[i + 1].year) : x1;
    svg.appendChild(svgEl("rect", {
      x: from, y: yTop, width: Math.max(to - from, 0), height: yBottom - yTop,
      fill: TONE_FILL[evs[i].tone], opacity: 0.55,
    }));
  }
  // 軸
  svg.appendChild(svgEl("line", { x1: x0, y1: YC, x2: x1, y2: YC, class: "axis", "stroke-dasharray": "4 4" }));
  svg.appendChild(svgEl("line", { x1: x0, y1: yTop, x2: x0, y2: yBottom, class: "axis" }));
  svg.appendChild(svgEl("text", { x: x0 - 44, y: yTop + 12, class: "axis-label" }, "快 ↑"));
  svg.appendChild(svgEl("text", { x: x0 - 44, y: yBottom - 2, class: "axis-label" }, "不快 ↓"));
  for (let yr = 990; yr <= 1001; yr++) {
    svg.appendChild(svgEl("text", { x: X(yr), y: yBottom + 18, "text-anchor": "middle", class: "axis-label" }, String(yr)));
    svg.appendChild(svgEl("line", { x1: X(yr), y1: yBottom, x2: X(yr), y2: yBottom + 4, class: "axis" }));
  }
  // 史実の印(上部に縦書きで)
  for (const e of evs) {
    const x = X(e.year);
    svg.appendChild(svgEl("line", { x1: x, y1: 14, x2: x, y2: yBottom, class: "event-line" }));
    const label = svgEl("text", { x: 0, y: 0, class: "event-mark", transform: `translate(${x + 4} 16) rotate(90)` }, e.label);
    label.appendChild(svgEl("title", {}, e.detail));
    svg.appendChild(label);
  }
  // 日記章段の点
  const place = makeLabelPlacer();
  const nikki = state.chapters.filter((c) => c.type === "nikki").sort((a, b) => a.year - b.year);
  nikki.forEach((c) => {
    const dot = svgEl("circle", {
      cx: X(c.year), cy: Y(c.v), r: c.dating_conf === "high" ? 8 : 7,
      fill: TYPE_COLOR.nikki,
      class: "dot" + (c.dating_conf === "low" ? " conf-low" : ""),
    });
    dot.appendChild(svgEl("title", {}, `${c.title}(${c.year_label} / 確度${CONF_LABEL[c.dating_conf]})`));
    dot.addEventListener("click", () => {
      svg.querySelectorAll(".dot").forEach((d) => d.classList.remove("is-selected"));
      dot.classList.add("is-selected");
      renderChapterDetail(document.getElementById("detail-chinmoku"), c);
    });
    svg.appendChild(dot);
    const short = c.title.length > 8 ? c.title.slice(0, 8) + "…" : c.title;
    place(svg, X(c.year), Y(c.v), short, 9);
  });
  // 凡例
  svg.appendChild(svgEl("text", { x: x0, y: yBottom + 40, class: "axis-label" },
    "帯の明暗=中関白家の史実(明→暗)。点=日記章段(縁が破線は比定確度が低いもの)。暗転後も点は快側に留まる。"));
}

/* ---------------- 升目ビュー ---------------- */

function koyomiCells() {
  const map = new Map(); // "season|time" -> [{chapter, evidence}]
  for (const c of state.chapters) {
    for (const k of c.koyomi ?? []) {
      const key = `${k.season}|${k.time}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push({ chapter: c, evidence: k.evidence });
    }
  }
  return map;
}

function renderMasume() {
  const grid = document.getElementById("masume-grid");
  const cells = koyomiCells();
  grid.replaceChildren();
  grid.style.gridTemplateColumns = `5.2rem repeat(${SEASONS.length}, 1fr)`;
  grid.appendChild(el("div", { class: "masume-head" }, "")); // 左上の空き
  for (const s of SEASONS) grid.appendChild(el("div", { class: "masume-head" }, s.label));
  for (const t of TIMES) {
    grid.appendChild(el("div", { class: "masume-head" }, t.label));
    for (const s of SEASONS) {
      const entry = cells.get(`${s.key}|${t.key}`) ?? [];
      const cell = el("div", {
        class: "masume-cell" + (entry.length === 0 ? " is-empty" : ""),
        role: "gridcell", tabindex: entry.length ? "0" : "-1",
      });
      if (entry.length === 0) {
        cell.append("—");
      } else {
        cell.appendChild(el("span", { class: "count" }, String(entry.length)));
        cell.appendChild(el("div", {}, entry.map((e) => e.chapter.title).join("・").slice(0, 22)));
        const open = () => {
          grid.querySelectorAll(".masume-cell").forEach((x) => x.classList.remove("is-selected"));
          cell.classList.add("is-selected");
          const box = document.getElementById("detail-masume");
          box.replaceChildren();
          box.appendChild(el("h3", {}, `${s.label} × ${t.label}`));
          for (const e of entry) {
            const p = el("p", {});
            p.appendChild(el("strong", {}, e.chapter.title));
            p.appendChild(el("br"));
            p.append(`根拠語: 「${e.evidence}」`);
            box.appendChild(p);
          }
          box.appendChild(el("p", { class: "modern-text" }, "根拠語は本文からの抄出。升目タグは編者の判定で、chapters.json の koyomi フィールドを書き換えれば升目も追随する。"));
        };
        cell.addEventListener("click", open);
        cell.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } });
      }
      grid.appendChild(cell);
    }
  }
}

/* ---------------- タブ ---------------- */

function switchView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${name}`));
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.view === name;
    t.classList.toggle("is-active", on);
    t.setAttribute("aria-selected", String(on));
  });
}

function initTabs() {
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => switchView(t.dataset.view)));
}

/* ---------------- 起動 ---------------- */

async function main() {
  const [chapters, itemsDoc, events, tags] = await Promise.all([
    loadJSON("data/chapters.json"),
    loadJSON("data/items.json"),
    loadJSON("data/events.json"),
    loadJSON("data/emotion_tags.json"),
  ]);
  state.chapters = chapters;
  state.items = itemsDoc.items;
  state.declared = itemsDoc.declared;
  state.events = events;
  state.tags = tags;
  state.kaitaiChap = state.declared[0] ?? null;

  initTabs();
  renderFilters();
  renderScatter();
  renderKaitai();
  renderTimeline();
  renderMasume();
}

main().catch((err) => {
  document.querySelector("main").prepend(
    el("p", { class: "detail-empty" }, `データの読み込みに失敗しました: ${err.message}`));
});
