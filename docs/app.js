/* 지도 + 단지 패널 + 최근 변화 목록 */
(function () {
  const cfg = window.APP_CONFIG || {};
  const DATA = cfg.DATA_BASE || "./data";
  const TYPE_LABEL = { 59: "59㎡", 70: "70㎡대", 84: "84㎡" };
  const TYPE_COLOR = { 59: "var(--type-59)", 70: "var(--type-70)", 84: "var(--type-84)" };
  const $ = (id) => document.getElementById(id);

  const state = {
    type: "59",
    newOnly: false,
    summary: null,
    changes: null,
    newKeys: new Set(),
    map: null,
    overlays: new Map(), // kapt_code -> CustomOverlay
    active: null,
    panelTab: "all",
    tradesCache: new Map(),
  };

  // ---------- 포맷 ----------
  const fmtEok = (man) => (man == null ? "-" : (man / 10000).toFixed(man >= 100000 ? 1 : 2).replace(/\.?0+$/, "") + "억");
  function fmtMan(man) {
    if (man == null) return "-";
    const eok = Math.floor(man / 10000), rest = man % 10000;
    if (eok && rest) return `${eok}억 ${rest.toLocaleString()}`;
    if (eok) return `${eok}억`;
    return `${rest.toLocaleString()}만`;
  }
  const fmtDate = (d) => (d ? d.slice(2).replace(/-/g, ".") : "-");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function deltaClass(pct) {
    if (pct == null) return "flat";
    return pct > 0.5 ? "up" : pct < -0.5 ? "down" : "flat";
  }
  function deltaText(pct) {
    if (pct == null) return "";
    const arrow = pct > 0.5 ? "▲" : pct < -0.5 ? "▼" : "―";
    return `${arrow} ${Math.abs(pct).toFixed(1)}%`;
  }
  function bucketOf(area) { return area < 65 ? "59" : area < 80 ? "70" : "84"; }

  // ---------- 데이터 ----------
  async function fetchJson(path, optional) {
    const res = await fetch(`${DATA}/${path}`, { cache: "no-cache" });
    if (!res.ok) {
      if (optional) return null;
      throw new Error(`${path} 를 불러오지 못했습니다 (${res.status})`);
    }
    return res.json();
  }

  async function loadData() {
    const [summary, changes] = await Promise.all([fetchJson("summary.json", true), fetchJson("changes/latest.json", true)]);
    state.summary = summary;
    state.changes = changes;
    state.newKeys = new Set((changes?.events || []).map((e) => e.record.key));
    if (summary) {
      const t = new Date(summary.generated_at);
      $("meta").textContent = `기준 ${t.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })} · 단지 ${summary.complexes.length}개 · ${summary.filters.min_households}세대 이상 · ${summary.filters.area_min}~${summary.filters.area_max}㎡`;
    }
  }

  // ---------- 지도 ----------
  function loadKakao() {
    return new Promise((resolve, reject) => {
      if (!cfg.KAKAO_JS_KEY) return reject(new Error("NO_KEY"));
      const s = document.createElement("script");
      s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(cfg.KAKAO_JS_KEY)}&autoload=false`;
      s.onload = () => window.kakao.maps.load(resolve);
      s.onerror = () => reject(new Error("카카오맵 SDK 를 불러오지 못했습니다. 카카오 콘솔에서 [카카오맵] > [사용 설정] 이 ON 인지, [JavaScript SDK 도메인]에 이 사이트 도메인이 등록됐는지 확인하세요."));
      document.head.appendChild(s);
    });
  }

  function showNotice(html) {
    $("noticeBox").innerHTML = html;
    $("notice").hidden = false;
  }

  function initMap() {
    const { kakao } = window;
    state.map = new kakao.maps.Map($("map"), {
      center: new kakao.maps.LatLng(cfg.CENTER?.lat || 37.535, cfg.CENTER?.lng || 126.93),
      level: cfg.ZOOM || 6,
    });
    state.map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);
    kakao.maps.event.addListener(state.map, "zoom_changed", refreshMarkers);
    buildMarkers();
  }

  function markerHtml(c) {
    const t = c.types?.[state.type];
    const compact = state.map.getLevel() >= 7;
    const isNew = c.new_events > 0 || c.recent_sales_14d > 0;
    let cls = "marker ";
    let inner;
    if (t && t.avg) {
      cls += deltaClass(t.change_pct);
      inner = `<span class="price">${fmtEok(t.avg)}</span>${t.change_pct != null && !compact ? `<span class="delta">${deltaText(t.change_pct)}</span>` : ""}`;
    } else if (t && t.last_price) {
      cls += "flat";
      inner = `<span class="price">${fmtEok(t.last_price)}</span><span class="name">${fmtDate(t.last_date)}</span>`;
    } else {
      cls += "none";
      inner = `<span class="price">거래 없음</span>`;
    }
    if (state.active === c.kapt_code) cls += " active";
    const name = compact ? "" : `<span class="name">${esc(c.name)}</span>`;
    return `<div class="${cls}" data-code="${c.kapt_code}"><div class="pill">${name}${inner}</div><div class="tail"></div>${isNew ? '<span class="dot" title="최근 거래"></span>' : ""}</div>`;
  }

  function buildMarkers() {
    const { kakao } = window;
    for (const c of state.summary?.complexes || []) {
      if (c.lat == null || c.lng == null) continue;
      const el = document.createElement("div");
      el.innerHTML = markerHtml(c);
      el.addEventListener("click", () => openComplex(c.kapt_code));
      const overlay = new kakao.maps.CustomOverlay({ position: new kakao.maps.LatLng(c.lat, c.lng), content: el, yAnchor: 1, zIndex: 2 });
      state.overlays.set(c.kapt_code, { overlay, el, c });
    }
    refreshMarkers();
  }

  function refreshMarkers() {
    if (!state.map) return;
    for (const { overlay, el, c } of state.overlays.values()) {
      const visible = !state.newOnly || c.new_events > 0 || c.recent_sales_14d > 0;
      el.innerHTML = markerHtml(c);
      overlay.setZIndex(state.active === c.kapt_code ? 10 : 2);
      overlay.setMap(visible ? state.map : null);
    }
  }

  // ---------- 패널 ----------
  async function openComplex(code, pan) {
    const entry = state.overlays.get(code);
    const c = entry?.c || state.summary?.complexes.find((x) => x.kapt_code === code);
    if (!c) return;
    state.active = code;
    history.replaceState(null, "", `#${code}`);
    if (pan && entry && state.map) state.map.panTo(entry.overlay.getPosition());
    refreshMarkers();
    $("panel").classList.add("open");
    $("panelBody").innerHTML = `<h2>${esc(c.name)}</h2><div class="sub">불러오는 중…</div>`;
    let trades = state.tradesCache.get(code);
    if (!trades) {
      trades = (await fetchJson(`trades/${code}.json`, true)) || { sales: [], rents: [] };
      state.tradesCache.set(code, trades);
    }
    renderPanel(c, trades);
  }

  function renderPanel(c, trades) {
    const tabs = ["all", "59", "70", "84"];
    const sel = state.panelTab;
    const sales = trades.sales.filter((s) => sel === "all" || bucketOf(s.area) === sel);
    const rents = trades.rents.filter((r) => sel === "all" || bucketOf(r.area) === sel);
    const statType = sel === "all" ? state.type : sel;
    const t = c.types?.[statType];

    const statsHtml = t
      ? `<div class="stats">
          <div class="stat"><div class="k">최근 3개월 평균 (${TYPE_LABEL[statType]})</div><div class="v">${fmtMan(t.avg)}</div><div class="d ${deltaClass(t.change_pct)}">${t.change_pct != null ? deltaText(t.change_pct) + " vs 이전 3개월" : `거래 ${t.count}건`}</div></div>
          <div class="stat"><div class="k">최근 거래</div><div class="v">${fmtMan(t.last_price)}</div><div class="d flat">${fmtDate(t.last_date)} · ${t.last_floor ?? "-"}층</div></div>
          <div class="stat"><div class="k">전세 평균 (3개월)</div><div class="v">${fmtMan(t.jeonse_avg)}</div><div class="d flat">${t.jeonse_count}건</div></div>
          <div class="stat"><div class="k">전세가율</div><div class="v">${t.jeonse_ratio != null ? t.jeonse_ratio + "%" : "-"}</div><div class="d flat">전세 평균 ÷ 매매 평균</div></div>
        </div>`
      : `<div class="empty">${TYPE_LABEL[statType]} 거래 통계가 없습니다.</div>`;

    const saleRows = sales.slice(0, 60).map((s) => `
      <tr class="${s.cancelled ? "cancel" : ""} ${state.newKeys.has(s.key) ? "new" : ""}">
        <td>${fmtDate(s.date)}</td><td class="num">${s.area.toFixed(1)}</td><td class="num">${s.floor ?? "-"}</td>
        <td class="num"><b>${fmtMan(s.price)}</b></td><td>${esc(s.dealing || "")}${s.registered ? '<span class="badge">등기</span>' : ""}${s.cancelled ? '<span class="badge">해제</span>' : ""}</td>
      </tr>`).join("");
    const rentRows = rents.slice(0, 40).map((r) => `
      <tr class="${state.newKeys.has(r.key) ? "new" : ""}">
        <td>${fmtDate(r.date)}</td><td class="num">${r.area.toFixed(1)}</td><td class="num">${r.floor ?? "-"}</td>
        <td class="num"><b>${fmtMan(r.deposit)}</b>${r.monthly ? ` / ${r.monthly}` : ""}</td><td>${r.monthly ? "월세" : "전세"}${r.contract_type ? `<span class="badge">${esc(r.contract_type)}</span>` : ""}</td>
      </tr>`).join("");

    $("panelBody").innerHTML = `
      <h2>${esc(c.name)}</h2>
      <div class="sub">${esc(c.sgg)} ${esc(c.umd)} · ${c.households.toLocaleString()}세대${c.area_85 ? ` (60~85㎡ ${c.area_85.toLocaleString()}세대)` : ""} · ${c.approved ? c.approved.slice(0, 4) + "년 승인" : ""}</div>
      <div class="tabs" id="panelTabs">${tabs.map((k) => `<button data-tab="${k}" class="${k === sel ? "on" : ""}">${k === "all" ? "전체" : `<span class="sw" style="background:${TYPE_COLOR[k]}"></span>${TYPE_LABEL[k]}`}</button>`).join("")}</div>
      ${statsHtml}
      <h3>월별 평균 매매가 (최근 24개월)</h3>
      <div class="legend">${["59", "70", "84"].map((k) => `<span><i style="background:${TYPE_COLOR[k]}"></i>${TYPE_LABEL[k]}</span>`).join("")}</div>
      <div id="chartWrap"></div>
      <h3>매매 실거래 <span class="badge">${sales.length}건</span></h3>
      ${saleRows ? `<table><thead><tr><th>계약일</th><th class="num">㎡</th><th class="num">층</th><th class="num">금액</th><th>구분</th></tr></thead><tbody>${saleRows}</tbody></table>` : '<div class="empty">매매 거래가 없습니다.</div>'}
      <h3>전월세 실거래 <span class="badge">${rents.length}건</span></h3>
      ${rentRows ? `<table><thead><tr><th>계약일</th><th class="num">㎡</th><th class="num">층</th><th class="num">보증금 / 월세</th><th>구분</th></tr></thead><tbody>${rentRows}</tbody></table>` : '<div class="empty">전월세 거래가 없습니다.</div>'}
    `;
    $("panelTabs").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-tab]");
      if (!b) return;
      state.panelTab = b.dataset.tab;
      renderPanel(c, trades);
    });
    $("chartWrap").appendChild(buildChart(trades.sales, sel === "all" ? ["59", "70", "84"] : [sel]));
  }

  // ---------- 차트 (월별 평균, 평형별 시리즈) ----------
  function monthlySeries(sales, keys) {
    const months = [];
    const d = new Date();
    for (let i = 23; i >= 0; i--) {
      const m = new Date(d.getFullYear(), d.getMonth() - i, 1);
      months.push(`${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`);
    }
    const series = {};
    for (const k of keys) series[k] = months.map(() => null);
    const acc = {};
    for (const s of sales) {
      if (s.cancelled) continue;
      const k = bucketOf(s.area);
      if (!series[k]) continue;
      const idx = months.indexOf(s.date.slice(0, 7));
      if (idx < 0) continue;
      acc[k] = acc[k] || {};
      (acc[k][idx] = acc[k][idx] || []).push(s.price);
    }
    for (const k of Object.keys(acc)) for (const idx of Object.keys(acc[k])) {
      const v = acc[k][idx];
      series[k][idx] = Math.round(v.reduce((a, b) => a + b, 0) / v.length);
    }
    return { months, series };
  }

  function buildChart(sales, keys) {
    const { months, series } = monthlySeries(sales, keys);
    const W = 388, H = 180, L = 44, R = 8, T = 10, B = 24;
    const values = Object.values(series).flat().filter((v) => v != null);
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("class", "chart");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "월별 평균 매매가");
    if (!values.length) {
      svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle">거래 데이터가 없습니다</text>`;
      return svg;
    }
    let min = Math.min(...values), max = Math.max(...values);
    const pad = (max - min || max * 0.1) * 0.15;
    min -= pad; max += pad;
    const x = (i) => L + (i / (months.length - 1)) * (W - L - R);
    const y = (v) => T + (1 - (v - min) / (max - min)) * (H - T - B);
    let html = "";
    const ticks = 4;
    for (let i = 0; i <= ticks; i++) {
      const v = min + ((max - min) * i) / ticks;
      html += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 4}" y="${y(v) + 3}" text-anchor="end">${fmtEok(Math.round(v))}</text>`;
    }
    months.forEach((m, i) => { if (i % 6 === 0 || i === months.length - 1) html += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${m.slice(2).replace("-", ".")}</text>`; });
    for (const k of keys) {
      const pts = series[k].map((v, i) => (v == null ? null : [x(i), y(v)]));
      let dPath = "", prev = null;
      pts.forEach((p) => { if (!p) { prev = null; return; } dPath += prev ? ` L${p[0]} ${p[1]}` : ` M${p[0]} ${p[1]}`; prev = p; });
      html += `<path class="line" d="${dPath.trim()}" stroke="${TYPE_COLOR[k]}"/>`;
      pts.forEach((p) => { if (p) html += `<circle class="pt" cx="${p[0]}" cy="${p[1]}" fill="${TYPE_COLOR[k]}"/>`; });
    }
    html += `<g id="hover" style="display:none"><line class="axis" y1="${T}" y2="${H - B}" stroke-dasharray="3 3"/><text class="tip" y="${T + 10}"></text></g>`;
    svg.innerHTML = html;
    const hover = svg.querySelector("#hover");
    svg.addEventListener("mousemove", (e) => {
      const rect = svg.getBoundingClientRect();
      const px = ((e.clientX - rect.left) / rect.width) * W;
      const i = Math.max(0, Math.min(months.length - 1, Math.round(((px - L) / (W - L - R)) * (months.length - 1))));
      const parts = keys.map((k) => (series[k][i] != null ? `${TYPE_LABEL[k]} ${fmtEok(series[k][i])}` : null)).filter(Boolean);
      if (!parts.length) { hover.style.display = "none"; return; }
      hover.style.display = "";
      const line = hover.querySelector("line"), tip = hover.querySelector("text");
      line.setAttribute("x1", x(i)); line.setAttribute("x2", x(i));
      tip.textContent = `${months[i].slice(2).replace("-", ".")} · ${parts.join(" · ")}`;
      // 말풍선은 세로선 반대쪽 가장자리에 붙여 잘리지 않게 한다.
      const anchorRight = x(i) < W * 0.5;
      tip.setAttribute("x", anchorRight ? W - R : L + 2);
      tip.setAttribute("text-anchor", anchorRight ? "end" : "start");
    });
    svg.addEventListener("mouseleave", () => { hover.style.display = "none"; });
    return svg;
  }

  // ---------- 최근 변화 ----------
  function renderChanges() {
    const events = state.changes?.events || [];
    $("changesCount").textContent = events.length;
    $("changesList").innerHTML = events.length
      ? events.slice(0, 100).map((e) => {
          const r = e.record;
          const what = e.type === "new_sale" ? `매매 ${fmtMan(r.price)}` : e.type === "cancelled" ? `해제 ${fmtMan(r.price)}` : `${r.monthly ? "월세" : "전세"} ${fmtMan(r.deposit)}${r.monthly ? ` / ${r.monthly}` : ""}`;
          return `<div class="item" data-code="${e.kapt_code}"><b>${esc(e.name)} <span class="badge">${r.area.toFixed(0)}㎡</span></b>${what} · ${r.floor ?? "-"}층 · ${fmtDate(r.date)}</div>`;
        }).join("")
      : `<div class="item">${state.changes?.first_run ? "첫 수집입니다. 다음 실행부터 변화가 표시됩니다." : "마지막 수집에서 새 거래가 없었습니다."}</div>`;
    $("changesList").addEventListener("click", (e) => {
      const item = e.target.closest(".item[data-code]");
      if (item) openComplex(item.dataset.code, true);
    });
  }

  // ---------- 이벤트 ----------
  function bindUI() {
    $("typeSeg").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-type]");
      if (!b) return;
      state.type = b.dataset.type;
      [...$("typeSeg").children].forEach((x) => x.classList.toggle("on", x === b));
      refreshMarkers();
      if (state.active) {
        const entry = state.overlays.get(state.active);
        const trades = state.tradesCache.get(state.active);
        if (entry && trades) renderPanel(entry.c, trades);
      }
    });
    $("newOnly").addEventListener("click", () => {
      state.newOnly = !state.newOnly;
      $("newOnly").classList.toggle("on", state.newOnly);
      $("newOnly").setAttribute("aria-pressed", String(state.newOnly));
      refreshMarkers();
    });
    $("panelClose").addEventListener("click", () => {
      $("panel").classList.remove("open");
      state.active = null;
      history.replaceState(null, "", location.pathname + location.search);
      refreshMarkers();
    });
    $("changesHead").addEventListener("click", () => $("changes").classList.toggle("collapsed"));

    $("pushBtn").addEventListener("click", async () => {
      $("pushModal").classList.add("open");
      $("pushStatus").textContent = "브라우저에 알림 권한을 요청합니다…";
      try {
        const sub = await window.PushSetup.subscribe();
        $("subJson").value = JSON.stringify(sub.toJSON());
        $("pushStatus").innerHTML = "✅ 구독이 만들어졌습니다. 아래 JSON 을 GitHub Secret 에 등록하세요.";
      } catch (err) {
        $("pushStatus").innerHTML = `⚠️ ${esc(err.message)}`;
      }
    });
    $("copySub").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText($("subJson").value); $("copySub").textContent = "복사됨"; setTimeout(() => ($("copySub").textContent = "복사"), 1500); } catch (_) { $("subJson").select(); }
    });
    $("testPush").addEventListener("click", () => window.PushSetup.showTest().catch((e) => alert(e.message)));
    $("closeModal").addEventListener("click", () => $("pushModal").classList.remove("open"));
  }

  // ---------- 시작 ----------
  async function start() {
    bindUI();
    try {
      await loadData();
    } catch (err) {
      showNotice(`<h2>데이터를 불러오지 못했습니다</h2><p>${esc(err.message)}</p>`);
      return;
    }
    renderChanges();
    if (!state.summary) {
      showNotice(`<h2>아직 수집된 데이터가 없습니다</h2><p>GitHub Actions 의 <b>실거래 수집·알림·배포</b> 워크플로를 한 번 실행하면 <code>data/summary.json</code> 이 만들어집니다.</p>`);
    }
    try {
      await loadKakao();
    } catch (err) {
      if (err.message === "NO_KEY") {
        showNotice(`<h2>카카오맵 키가 필요합니다</h2><p><code>docs/config.js</code> 의 <code>KAKAO_JS_KEY</code> 에 카카오 개발자 앱의 JavaScript 키를 넣고, 카카오 콘솔의 [플랫폼 키] &gt; [JavaScript 키] &gt; [JavaScript SDK 도메인]에 이 사이트 도메인을 등록하세요.</p>`);
      } else {
        showNotice(`<h2>지도를 불러오지 못했습니다</h2><p>${esc(err.message)}</p>`);
      }
      return;
    }
    if (!state.summary) return;
    $("notice").hidden = true;
    initMap();
    const code = location.hash.slice(1);
    if (code && state.overlays.has(code)) openComplex(code, true);
  }

  start();
})();
