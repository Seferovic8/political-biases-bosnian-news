/* =========================================================================
   Stav — front-end application
   ========================================================================= */
(function () {
  "use strict";

  // ---- bootstrap data ----------------------------------------------------
  const readJSON = (id) => JSON.parse(document.getElementById(id).textContent);
  const STATUS = readJSON("bootstrap-status");
  const TOPICS = readJSON("bootstrap-topics"); // [{key,name}]
  const CLASS_META = readJSON("bootstrap-classmeta");
  const METHOD_NAMES = readJSON("bootstrap-methodnames");

  const CLASS_COLORS = {
    for: "#1f8a70",
    against: "#c24a3a",
    neutral: "#c99a2e",
    not_mentioned: "#9aa0a6",
  };
  const STANCE_AXIS = { against: -1, neutral: 0, for: 1 };

  // ---- state -------------------------------------------------------------
  const state = {
    method: null,
    articles: [], // {id,title,content,source,url,status,error}
    charts: {},
    seq: 1,
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const uid = () => "a" + state.seq++;
  const pct = (x) => (x == null ? "—" : Math.round(x * 100) + "%");
  const esc = (s) =>
    (s || "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));

  // ---- toasts ------------------------------------------------------------
  function toast(msg, isError) {
    const host = $("#toast-host");
    const el = document.createElement("div");
    el.className = "toast" + (isError ? " is-error" : "");
    el.textContent = msg;
    host.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 250);
    }, 3600);
  }

  // ---- mode banner + method availability --------------------------------
  function initModeBanner() {
    const banner = $("#mode-banner");
    if (STATUS.mode === "models") {
      banner.classList.add("is-models");
      banner.innerHTML = "<b>Live models</b> · trained artefacts loaded";
    } else {
      banner.classList.add("is-demo");
      banner.innerHTML =
        "<b>Demo mode</b> · trained models not found — using a deterministic heuristic";
    }
    // flag availability on method cards
    $$(".method-card").forEach((card) => {
      const m = card.dataset.method;
      const flag = card.querySelector(".method-flag");
      const available = STATUS.available_methods.includes(m);
      if (STATUS.mode === "models") {
        flag.textContent = available ? "available" : "models missing";
        if (!available) {
          card.classList.add("is-unavailable");
          card.setAttribute("aria-disabled", "true");
        }
      } else {
        flag.textContent = "demo predictor";
      }
    });
  }

  // ---- method selection --------------------------------------------------
  function initMethods() {
    $$(".method-card").forEach((card) => {
      card.addEventListener("click", () => {
        if (card.getAttribute("aria-disabled") === "true") {
          toast("This method's models are not installed.", true);
          return;
        }
        state.method = card.dataset.method;
        $$(".method-card").forEach((c) =>
          c.setAttribute("aria-checked", String(c === card))
        );
        updatePredictBar();
      });
    });
    // preselect ensemble if available, else first available
    const pref = ["logreg", "ensemble", "bertic"].find((m) =>
      STATUS.available_methods.includes(m)
    );
    if (pref) {
      const card = $(`.method-card[data-method="${pref}"]`);
      if (card && card.getAttribute("aria-disabled") !== "true") card.click();
    }
  }

  // ---- tabs --------------------------------------------------------------
  function initTabs() {
    $$(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        $$(".tab").forEach((t) => {
          const active = t === tab;
          t.classList.toggle("is-active", active);
          t.setAttribute("aria-selected", String(active));
        });
        $$(".tab-panel").forEach((p) =>
          p.classList.toggle("is-active", p.dataset.panel === tab.dataset.tab)
        );
      });
    });
  }

  // ---- queue rendering ---------------------------------------------------
  function statusPill(a) {
    if (a.status === "loading")
      return '<span class="status status--loading"><span class="spinner"></span>Fetching</span>';
    if (a.status === "error")
      return '<span class="status status--error">Failed</span>';
    if (a.status === "edit")
      return '<span class="status status--edit">Editing</span>';
    return '<span class="status status--ready">Ready</span>';
  }

  function renderQueue() {
    const list = $("#article-list");
    const emptyNote = $("#queue-empty-note");
    list.innerHTML = "";
    emptyNote.classList.toggle("is-hidden", state.articles.length > 0);

    state.articles.forEach((a) => {
      const card = document.createElement("div");
      card.className = "card" + (a.status === "error" ? " is-error" : "");
      card.dataset.id = a.id;

      const bodyHTML =
        a.status === "loading"
          ? `<div class="card-url">${esc(a.url)}</div>`
          : a.status === "error"
            ? `<div class="card-url">${esc(a.url || "")}</div>`
            : `<div class="card-text" data-role="content" ${a.editing ? 'contenteditable="true"' : ""
            }>${esc(a.content || "")}</div>`;

      card.innerHTML = `
        <div class="card-top">
          <div style="min-width:0">
            <span class="card-source"><span class="source-dot"></span>${esc(a.source)}</span>
            <h3 class="card-title" data-role="title" ${a.editing ? 'contenteditable="true"' : ""
        }>${esc(a.title || "(untitled)")}</h3>
          </div>
          <div class="card-actions">
            ${a.status === "ready"
          ? `<button class="icon-btn" data-act="edit" title="${a.editing ? "Save" : "Edit"
          }">${a.editing ? "✓" : "✎"}</button>`
          : ""
        }
            <button class="icon-btn icon-btn--danger" data-act="remove" title="Remove">✕</button>
          </div>
        </div>
        <div class="card-body">${bodyHTML}</div>
        ${a.status === "error"
          ? `<div class="card-error-msg">${esc(a.error || "Could not retrieve this article.")}</div>`
          : ""
        }
        <div class="card-foot">${statusPill(a)}${a.wordcount != null
          ? `<span>· ${a.wordcount} words</span>`
          : ""
        }</div>
      `;
      list.appendChild(card);
    });

    $("#article-count").textContent = state.articles.length;
    updatePredictBar();
  }

  function updatePredictBar() {
    const bar = $("#predict-bar");
    const ready = state.articles.filter((a) => a.status === "ready");
    bar.hidden = state.articles.length === 0;
    $("#predict-bar-count").textContent =
      ready.length + (ready.length === 1 ? " article" : " articles") + " ready";
    $("#predict-bar-method").textContent = state.method
      ? METHOD_NAMES[state.method] + " selected"
      : "no method selected";
    const btn = $("#run-predict");
    btn.disabled = ready.length === 0 || !state.method;
  }

  // queue interactions (event delegation)
  $("#article-list").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const card = e.target.closest(".card");
    const a = state.articles.find((x) => x.id === card.dataset.id);
    if (!a) return;

    if (btn.dataset.act === "remove") {
      state.articles = state.articles.filter((x) => x.id !== a.id);
      renderQueue();
    } else if (btn.dataset.act === "edit") {
      if (a.editing) {
        // save
        const title = card.querySelector('[data-role="title"]').innerText.trim();
        const content = card
          .querySelector('[data-role="content"]')
          .innerText.trim();
        if (!content) {
          toast("Article text can't be empty.", true);
          return;
        }
        a.title = title === "(untitled)" ? "" : title;
        a.content = content;
        a.wordcount = content.split(/\s+/).filter(Boolean).length;
        a.editing = false;
      } else {
        a.editing = true;
      }
      renderQueue();
    }
  });

  // ---- manual add --------------------------------------------------------
  function initManual() {
    $("#add-manual").addEventListener("click", () => {
      const title = $("#manual-title").value.trim();
      const content = $("#manual-content").value.trim();
      const note = $("#manual-note");
      note.className = "inline-note";
      if (!content) {
        note.textContent = "Add some article text first.";
        note.classList.add("is-error");
        return;
      }
      state.articles.push({
        id: uid(),
        title,
        content,
        source: "Manual entry",
        url: "",
        status: "ready",
        wordcount: content.split(/\s+/).filter(Boolean).length,
      });
      $("#manual-title").value = "";
      $("#manual-content").value = "";
      note.textContent = "Added.";
      renderQueue();
    });
  }

  // ---- URL fetch ---------------------------------------------------------
  function initUrlFetch() {
    $("#fetch-urls").addEventListener("click", async () => {
      const raw = $("#url-input").value.trim();
      const note = $("#url-note");
      note.className = "inline-note";
      const urls = raw
        .split(/\n+/)
        .map((u) => u.trim())
        .filter(Boolean);
      if (urls.length === 0) {
        note.textContent = "Enter at least one URL.";
        note.classList.add("is-error");
        return;
      }

      // create placeholder loading cards
      const placeholders = urls.map((url) => {
        const a = {
          id: uid(),
          title: url,
          content: "",
          source: "Fetching…",
          url,
          status: "loading",
        };
        state.articles.push(a);
        return a;
      });
      $("#url-input").value = "";
      renderQueue();
      note.textContent = "Fetching " + urls.length + " article(s)…";
      note.classList.add("is-busy");

      const btn = $("#fetch-urls");
      btn.disabled = true;
      try {
        const resp = await fetch("api/scrape", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ urls }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Scrape request failed.");

        data.articles.forEach((res, i) => {
          const a = placeholders[i];
          if (res.ok) {
            a.status = "ready";
            a.title = res.title || "(untitled)";
            a.content = res.content;
            a.source = res.portal || "Web";
            a.wordcount = (res.content || "")
              .split(/\s+/)
              .filter(Boolean).length;
          } else {
            a.status = "error";
            a.source = "Failed";
            a.error = res.error || "Could not retrieve this article.";
          }
        });
        renderQueue();
        const ok = data.articles.filter((r) => r.ok).length;
        const failed = data.articles.length - ok;
        note.className = "inline-note";
        note.textContent =
          `Fetched ${ok} article(s)` + (failed ? `, ${failed} failed.` : ".");
        if (failed) toast(`${failed} URL(s) could not be retrieved.`, true);
      } catch (err) {
        placeholders.forEach((a) => {
          a.status = "error";
          a.source = "Failed";
          a.error = err.message;
        });
        renderQueue();
        note.className = "inline-note is-error";
        note.textContent = err.message;
      } finally {
        btn.disabled = false;
      }
    });
  }

  // ---- clear all ---------------------------------------------------------
  $("#clear-all").addEventListener("click", () => {
    if (!state.articles.length) return;
    state.articles = [];
    renderQueue();
    $("#section-results").hidden = true;
    $("#section-combined").hidden = true;
  });

  // ---- predict -----------------------------------------------------------
  function initPredict() {
    $("#run-predict").addEventListener("click", async () => {
      const ready = state.articles.filter((a) => a.status === "ready");
      if (!ready.length || !state.method) return;

      const btn = $("#run-predict");
      btn.disabled = true;
      btn.textContent = "Analysing…";

      try {
        const resp = await fetch("api/predict", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            method: state.method,
            articles: ready.map((a) => ({
              title: a.title,
              content: a.content,
              source: a.source,
            })),
          }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Prediction failed.");
        renderResults(data);
        renderCombined(data);
        (data.skipped || []).forEach((m) => toast(m, true));
        $("#section-results").scrollIntoView({ behavior: "smooth" });
      } catch (err) {
        toast(err.message, true);
      } finally {
        btn.disabled = false;
        btn.textContent = "Predict";
        updatePredictBar();
      }
    });
  }

  function badge(cls) {
    const meta = CLASS_META[cls] || { label: cls };
    return `<span class="badge badge--${cls}"><span class="badge-dot" style="background:${CLASS_COLORS[cls]
      }"></span>${meta.label}</span>`;
  }

  function stanceMeter(tr) {
    if (!tr.mentioned || !tr.stance) {
      return `<div class="meter is-nm">
        <div class="meter-zone"></div><div class="meter-zone"></div><div class="meter-zone"></div>
        <div class="meter-caption">not mentioned</div>
      </div>`;
    }
    // marker position from stance probabilities: expected value on [-1,1]
    const sp = tr.stance_probs || {};
    const ev =
      (sp.for || 0) * STANCE_AXIS.for +
      (sp.against || 0) * STANCE_AXIS.against +
      (sp.neutral || 0) * STANCE_AXIS.neutral;
    const left = ((ev + 1) / 2) * 100;
    const color = CLASS_COLORS[tr.stance];
    return `<div class="meter">
      <div class="meter-zone meter-zone--against"></div>
      <div class="meter-zone meter-zone--neutral"></div>
      <div class="meter-zone meter-zone--for"></div>
      <div class="meter-mid"></div>
      <div class="meter-marker" style="left:${left.toFixed(
      1
    )}%;background:${color};box-shadow:0 0 0 2px #fff, 0 0 6px ${color}"></div>
    </div>`;
  }

  function perModelRow(tr) {
    if (!tr.per_model) return "";
    const one = (name) => {
      const pm = tr.per_model[name];
      if (!pm) return "";
      let verdict = "not mentioned";
      if (pm.binary && pm.binary.mentioned > pm.binary.not_mentioned) {
        if (pm.stance) {
          const s = Object.entries(pm.stance).sort((a, b) => b[1] - a[1])[0];
          verdict = s[0];
        } else verdict = "mentioned";
      }
      return `<span class="pm"><b>${name}:</b> ${verdict}</span>`;
    };
    return `<div class="per-model">${one("LogReg")}${one("BERTić")}</div>`;
  }

  function renderResults(data) {
    const section = $("#section-results");
    const list = $("#results-list");
    section.hidden = false;
    list.innerHTML = "";

    $("#results-meta").textContent =
      `${data.results.length} article(s) · method: ${data.method_name} · ` +
      (data.mode === "models" ? "live models" : "demo predictor");

    data.results.forEach((r) => {
      const card = document.createElement("div");
      card.className = "result-card";
      const h = r.headline;
      const headBadge =
        h.topic == null
          ? badge("not_mentioned")
          : badge(h.final);
      const headTopic =
        h.topic == null
          ? "no topic detected"
          : (TOPICS.find((t) => t.key === h.topic) || {}).name;

      const topicRows = TOPICS.map((t) => {
        const tr = r.topics[t.key];
        const verdict = tr.mentioned && tr.stance ? tr.stance : "not_mentioned";
        return `<div class="topic-row">
          <div class="topic-name">${t.name}<small>${t.key}</small></div>
          ${stanceMeter(tr)}
          <div class="topic-verdict">
            ${badge(verdict)}
            <div class="topic-conf">conf ${pct(tr.confidence)} · p(mention) ${pct(
          tr.p_mentioned
        )}</div>
          </div>
          ${perModelRow(tr)}
        </div>`;
      }).join("");

      card.innerHTML = `
        <div class="result-head">
          <div class="result-head-main">
            <span class="card-source"><span class="source-dot"></span>${esc(
        r.source
      )}</span>
            <h3 class="result-title">${esc(r.title || "(untitled)")}</h3>
          </div>
          <div class="result-headline">
            <span class="headline-label">Strongest signal</span>
            ${headBadge}
            <span class="conf-readout">${esc(headTopic)}${h.confidence != null ? ` · <b>${pct(h.confidence)}</b>` : ""
        }</span>
          </div>
        </div>
        <div class="result-topics">${topicRows}</div>
      `;
      list.appendChild(card);
    });
  }

  // ---- combined analysis -------------------------------------------------
  function destroyChart(key) {
    if (state.charts[key]) {
      state.charts[key].destroy();
      delete state.charts[key];
    }
  }

  function renderCombined(data) {
    $("#section-combined").hidden = false;
    renderDistribution(data.summary.distribution);
    renderTopicChart(data.summary.per_topic);
    renderHeatmap(data.summary.heatmap);
    if (data.summary.model_comparison) {
      $("#panel-comparison").hidden = false;
      renderComparison(data.summary.model_comparison, data.results);
    } else {
      $("#panel-comparison").hidden = true;
    }
  }

  function renderDistribution(dist) {
    destroyChart("dist");
    const order = ["for", "neutral", "against", "not_mentioned"];
    const labels = order.map((c) => (CLASS_META[c] || {}).label || c);
    const values = order.map((c) => dist[c] || 0);
    const colors = order.map((c) => CLASS_COLORS[c]);
    const ctx = $("#chart-distribution");
    state.charts.dist = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels,
        datasets: [{ data: values, backgroundColor: colors, borderWidth: 2, borderColor: "#fff" }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "58%",
        plugins: {
          legend: { position: "bottom", labels: { font: { family: "Inter" }, boxWidth: 12 } },
          tooltip: { callbacks: { label: (c) => ` ${c.label}: ${c.parsed} cells` } },
        },
      },
    });
  }

  function renderTopicChart(perTopic) {
    destroyChart("topics");
    const keys = TOPICS.map((t) => t.key);
    const names = TOPICS.map((t) => t.name);
    const mentionRates = keys.map((k) => (perTopic[k].mention_rate * 100));
    const netStance = keys.map((k) => perTopic[k].net_stance);

    const ctx = $("#chart-topics");
    state.charts.topics = new Chart(ctx, {
      data: {
        labels: names,
        datasets: [
          {
            type: "bar",
            label: "Mention rate (%)",
            data: mentionRates,
            backgroundColor: "#2e5e7e",
            yAxisID: "y",
            borderRadius: 3,
          },
          {
            type: "line",
            label: "Net stance (for − against)",
            data: netStance,
            borderColor: "#c99a2e",
            backgroundColor: "#c99a2e",
            yAxisID: "y1",
            tension: 0.25,
            pointRadius: 5,
            pointHoverRadius: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { font: { family: "Inter" }, boxWidth: 12 } },
        },
        scales: {
          y: {
            position: "left",
            beginAtZero: true,
            max: 100,
            title: { display: true, text: "Mention rate %" },
            ticks: { font: { family: "IBM Plex Mono" } },
          },
          y1: {
            position: "right",
            min: -1,
            max: 1,
            grid: { drawOnChartArea: false },
            title: { display: true, text: "Net stance" },
            ticks: { font: { family: "IBM Plex Mono" } },
          },
          x: { ticks: { font: { family: "Inter", size: 10 } } },
        },
      },
    });
  }

  function renderComparison(cmp, results) {
    const head = $("#comparison-head");
    head.innerHTML = `
      <div class="stat"><span class="stat-num">${pct(
      cmp.agreement_rate
    )}</span><span class="stat-label">Agreement rate</span></div>
      <div class="stat"><span class="stat-num">${cmp.agreements}/${cmp.total_cells
      }</span><span class="stat-label">Cells in agreement</span></div>
      <div class="stat"><span class="stat-num">${cmp.n_disagreements
      }</span><span class="stat-label">Disagreements</span></div>
    `;

    destroyChart("cmp");
    const ctx = $("#chart-comparison");
    state.charts.cmp = new Chart(ctx, {
      type: "bar",
      data: {
        labels: ["Model decisions"],
        datasets: [
          { label: "Agree", data: [cmp.agreements], backgroundColor: "#1f8a70", borderRadius: 3 },
          {
            label: "Disagree",
            data: [cmp.n_disagreements],
            backgroundColor: "#c24a3a",
            borderRadius: 3,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true, ticks: { font: { family: "IBM Plex Mono" } } },
          y: { stacked: true, ticks: { display: false } },
        },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
      },
    });

    const dl = $("#disagreement-list");
    if (!cmp.disagreements.length) {
      dl.innerHTML =
        '<p class="panel-sub">The two models agreed on every article–topic cell.</p>';
      return;
    }
    dl.innerHTML = cmp.disagreements
      .map((d) => {
        const title = (results[d.article_index] || {}).title || "Article";
        return `<div class="disagreement">
          <span class="da-topic">${esc(d.topic_name)}</span>
          <span class="vs">·</span>
          <span>${esc(title.slice(0, 60))}</span>
          <span class="vs">LogReg</span>${badge(d.logreg)}
          <span class="vs">BERTić</span>${badge(d.bertic)}
        </div>`;
      })
      .join("");
  }

  function renderHeatmap(hm) {
    const grid = $("#heatmap");
    const cols = hm.topics;
    grid.style.gridTemplateColumns = `minmax(160px, 1.4fr) repeat(${cols.length}, 1fr)`;
    let html = '<div class="hm-head"></div>';
    cols.forEach((c) => {
      html += `<div class="hm-head">${esc(c.name)}</div>`;
    });
    hm.rows.forEach((row) => {
      html += `<div class="hm-rowhead"><span>${esc(
        row.title
      )}</span><small>${esc(row.source)}</small></div>`;
      row.cells.forEach((cell) => {
        const color = CLASS_COLORS[cell.final];
        // opacity tracks confidence (min 0.35 so labels stay legible)
        const op = 0.35 + 0.65 * (cell.confidence || 0);
        const label = (CLASS_META[cell.final] || {}).label || cell.final;
        const textColor = cell.final === "neutral" ? "#3a2f08" : "#fff";
        html += `<div class="hm-cell" title="${esc(label)} · conf ${pct(
          cell.confidence
        )}" style="background:${color};opacity:${op.toFixed(
          2
        )};color:${textColor}">${cell.final === "not_mentioned" ? "—" : esc(label)}</div>`;
      });
    });
    grid.innerHTML = html;

    // legend
    const legend = $("#heatmap-legend");
    legend.innerHTML = ["for", "neutral", "against", "not_mentioned"]
      .map(
        (c) =>
          `<span class="legend-item"><span class="legend-swatch" style="background:${CLASS_COLORS[c]
          }"></span>${(CLASS_META[c] || {}).label || c}</span>`
      )
      .join("");
  }

  // ---- init --------------------------------------------------------------
  initModeBanner();
  initMethods();
  initTabs();
  initManual();
  initUrlFetch();
  initPredict();
  renderQueue();
})();
