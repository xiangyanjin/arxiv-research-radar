"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const i18n = window.RadarI18n;
  const t = i18n.t;
  i18n.init();
  const state = { view: "papers", topic: "", filter: "all", query: "", sort: "relevance", data: null, digest: "", poll: null, search: null, request: 0, lastRun: "", loadingScan: false, toast: null, drafts: new Map(), notesOpen: new Set(), noteWidgets: new Map(), libraryPending: new Set(), draftStorageError: false };

  const draftStorageKey = "arxiv-radar-note-drafts-v1";
  try {
    const stored = JSON.parse(sessionStorage.getItem(draftStorageKey) || "[]");
    if (Array.isArray(stored)) stored.forEach((draft) => {
      if (draft && typeof draft.id === "string" && typeof draft.text === "string" && typeof draft.baseText === "string" && draft.text !== draft.baseText) {
        state.drafts.set(draft.id, { ...draft, saving: false, error: "" });
        state.notesOpen.add(draft.id);
      }
    });
  } catch { state.draftStorageError = true; }
  function dirtyDrafts() { return [...state.drafts.values()].filter((draft) => draft.text !== draft.baseText); }
  function persistDrafts() {
    try {
      sessionStorage.setItem(draftStorageKey, JSON.stringify(dirtyDrafts().map(({ id, title, text, baseText, version }) => ({ id, title, text, baseText, version }))));
      state.draftStorageError = false;
    } catch { state.draftStorageError = true; }
    renderDraftNotice();
  }
  function renderDraftNotice() {
    const notice = $("draft-notice");
    if (!notice) return;
    const drafts = dirtyDrafts();
    notice.hidden = !drafts.length;
    notice.replaceChildren();
    if (!drafts.length) return;
    const text = el("div");
    text.append(el("strong", "", i18n.language === "zh" ? `${drafts.length} 篇论文有未保存笔记` : `Unsaved notes on ${drafts.length} ${drafts.length === 1 ? "paper" : "papers"}`));
    text.append(el("p", "", state.draftStorageError ? t("草稿暂存在此标签页；浏览器无法备份，请保存后再关闭。") : t("切换页面、语言或筛选不会丢失草稿；本标签页刷新后也可恢复。")));
    const list = el("div", "draft-list");
    drafts.forEach((draft) => {
      const button = el("button", "draft-jump", draft.title || draft.id);
      button.title = t("返回这篇论文的草稿");
      button.addEventListener("click", () => {
        state.topic = ""; state.filter = "all"; state.query = ""; state.sort = "relevance";
        $("search-input").value = ""; $("sort-select").value = state.sort;
        renderTopics(); renderStatusFilters(); switchView("papers");
        loadPapers({ focusDraft: draft.id });
      });
      list.append(button);
    });
    text.append(list); notice.append(icon("file"), text);
  }
  function viewQuery() {
    return new URLSearchParams({ topic: state.topic, filter: state.filter, q: state.query, sort: state.sort });
  }
  function updateExports(disabled = false) {
    const query = viewQuery(); query.set("scope", "view");
    [["bib-link", "bib"], ["markdown-link", "markdown"]].forEach(([id, format]) => {
      const a = $(id);
      a.href = `/api/exports/${format}?${query}`;
      a.setAttribute("aria-disabled", String(disabled));
      a.tabIndex = disabled ? -1 : 0;
    });
  }
  function rememberFocus() {
    const active = document.activeElement;
    return active?.dataset?.noteEditor ? { id: active.dataset.noteEditor, start: active.selectionStart, end: active.selectionEnd, scroll: active.scrollTop } : null;
  }
  function restoreNoteFocus(focus) {
    if (!focus) return;
    const editor = [...document.querySelectorAll("[data-note-editor]")].find((node) => node.dataset.noteEditor === focus.id);
    if (!editor) return;
    editor.focus({ preventScroll: true });
    editor.setSelectionRange(focus.start ?? editor.value.length, focus.end ?? editor.value.length);
    editor.scrollTop = focus.scroll || 0;
  }

  const viewText = () => ({
    papers: [t("保持好奇，持续发现"), t("把相关研究，留在视野里。"), t("关注你的研究方向，从 arXiv 的新论文与更新中寻找值得读的工作。")],
    digest: [t("从线索到阅读"), t("留一点时间，给新的想法。"), t("一份可追溯的研究简报。初筛提供线索，结论仍需回到论文中核实。")],
    runs: [t("可追溯，才值得信任"), t("每一次发现，都有来处。"), t("保留扫描状态、数据覆盖与错误信息，区分没有新论文和未能完成扫描。")]
  });

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#i-${name}`);
    svg.append(use);
    return svg;
  }
  function safeURL(raw) {
    if (typeof raw !== "string") return null;
    try { const url = new URL(raw); return ["http:", "https:"].includes(url.protocol) ? url.href : null; } catch { return null; }
  }
  function link(label, raw, className = "") {
    const href = safeURL(raw);
    if (!href) return el("span", className, label);
    const a = el("a", className, label);
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  }
  function timeZone() {
    const zone = state.data?.profile?.display?.timezone || "UTC";
    try { new Intl.DateTimeFormat("en", { timeZone: zone }); return zone; } catch { return "UTC"; }
  }
  function date(value, time = false) {
    if (!value) return t("未记录");
    const parsed = new Date(value);
    if (!Number.isFinite(parsed.getTime())) return t("日期未记录");
    return new Intl.DateTimeFormat(i18n.language === "zh" ? "zh-CN" : "en-GB", { timeZone: timeZone(), year: "numeric", month: "2-digit", day: "2-digit", ...(time ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}) }).format(parsed);
  }
  function count(value) { return Number.isFinite(Number(value)) && value !== null && value !== undefined ? Number(value).toLocaleString(i18n.language === "zh" ? "zh-CN" : "en") : "—"; }
  function list(value) { return Array.isArray(value) ? value : []; }
  function stringify(value) { return typeof value === "string" ? value : JSON.stringify(value, null, 2); }
  function toast(message, error = false) {
    clearTimeout(state.toast);
    $("toast").textContent = message;
    $("toast").classList.toggle("error", error);
    $("toast").hidden = false;
    state.toast = setTimeout(() => { $("toast").hidden = true; }, 4500);
  }
  async function api(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(path, { ...options, signal: controller.signal, headers: { "Accept": "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers } });
      let data;
      try { data = await response.json(); } catch { throw new Error((i18n.language === "zh" ? `服务返回了无法读取的响应（${response.status}）` : `Unreadable server response (${response.status})`)); }
      if (!response.ok) { const error = new Error(data.error || data.message || (i18n.language === "zh" ? `请求失败（${response.status}）` : `Request failed (${response.status})`)); error.status = response.status; throw error; }
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error(t("连接本地服务超时，请稍后重试。"));
      if (error instanceof TypeError) throw new Error(t("无法连接本地研究雷达服务，请确认服务仍在运行。"));
      throw error;
    } finally { clearTimeout(timer); }
  }
  function empty(container, heading, description, iconName = "radar", action) {
    const box = el("div", "empty-state");
    box.append(icon(iconName), el("h3", "", heading), el("p", "", description));
    if (action) {
      const button = el("button", "button button-secondary", action.label);
      button.addEventListener("click", action.run);
      box.append(button);
    }
    container.replaceChildren(box);
  }
  function loading(container, message) {
    const box = el("div", "empty-state");
    box.append(el("span", "loading-spinner"), el("h3", "", message));
    container.replaceChildren(box);
  }
  function renderNotice() {
    const box = $("global-notice");
    box.replaceChildren();
    box.className = "notice";
    const data = state.data;
    if (!data) { box.hidden = true; return; }
    const run = data.latest_run;
    let title = "", body = "", style = "";
    if (data.scanning || state.loadingScan) {
      title = t("扫描进行中");
      body = t("正在查询 arXiv 并整理研究线索。当前显示已归档的记录，完成后会自动刷新。");
    } else if (run?.status === "failed") {
      title = t("最近一次扫描未完成");
      body = list(run.errors).length ? `${t("来源错误（原文）")}: ${run.errors.join("; ")}` : t("暂时无法获得有效数据。已有论文记录仍被保留，可在扫描记录中查看详情并重试。");
      style = "notice-error";
    } else if (run?.status === "partial") {
      title = t("本次扫描覆盖不完整");
      body = t("当前仅展示实际获取的数据，不能据此判断所有相关论文均已收录。");
      if (list(run.errors).length) body += ` ${t("来源错误（原文）")}: ${run.errors.join("; ")}`;
      style = "notice-warning";
    } else if (data.notice) {
      title = t("数据说明");
      body = t("依据标题与摘要进行方向匹配。相关性不代表论文质量或证明正确性。");
      if (data.latest_run?.coverage?.demo) body += i18n.language === "zh" ? " 示例数据：公开元数据快照，并非完整扫描。" : " Demo: a public metadata snapshot, not a complete scan.";
    }
    if (!title) { box.hidden = true; return; }
    if (style) box.classList.add(style);
    const content = el("div");
    content.append(el("strong", "", title), el("p", "", body));
    box.append(icon("info"), content);
    box.hidden = false;
  }
  function setScanButton() {
    const busy = Boolean(state.data?.scanning || state.loadingScan);
    const button = $("scan-button");
    button.disabled = busy;
    button.classList.toggle("is-scanning", busy);
    button.querySelector("span").textContent = busy ? t("扫描中…") : t("立即扫描");
    button.setAttribute("aria-busy", String(busy));
  }
  function updateStats() {
    const data = state.data;
    const stats = data.stats || {};
    $("stat-relevant").textContent = count(stats.relevant);
    $("stat-new").textContent = count(stats.new);
    $("stat-updates").textContent = count(stats.updates);
    $("stat-saved").textContent = count(stats.saved);
    $("library-stats").textContent = i18n.language === "zh" ? `已读 ${count(stats.read)} · 有笔记 ${count(stats.notes)}` : `${count(stats.read)} read · ${count(stats.notes)} with notes`;
    $("nav-count").textContent = count(stats.relevant);
    $("overview-title").textContent = t("与你的方向保持连接");
    const run = data.latest_run;
    $("last-scan-label").textContent = run ? `${i18n.language === "zh" ? "最近扫描" : "Last scan"} ${date(run.started_at || run.finished_at, true)} · ${timeZone()}` : t("还没有扫描记录 · 从第一次扫描开始");
    $("profile-name").textContent = data.profile?.display?.name || data.profile?.name || t("研究配置");
    $("today-label").textContent = `${date(new Date().toISOString())} · ${timeZone()}`;
  }
  function topicLabel(topic) {
    const names = { matrix: ["Random matrices", "随机矩阵"], tensor: ["Tensor statistics", "张量与高维统计"], markov: ["Markov chains", "马尔可夫链与谱隙"], concentration: ["Concentration & geometry", "集中不等式与几何概率"] };
    if (typeof topic === "string") return topic;
    return names[topic.id]?.[i18n.language === "zh" ? 1 : 0] || topic.label || topic.id;
  }
  function topicObjects() {
    const data = state.data;
    const raw = Array.isArray(data?.topics) ? data.topics : data?.profile?.topics;
    return list(raw).map((topic) => typeof topic === "string" ? { id: topic, label: topic } : topic).filter((topic) => topic?.id);
  }
  function renderTopics() {
    const topics = topicObjects();
    const filters = $("topic-filters");
    const side = $("sidebar-topics");
    filters.replaceChildren();
    side.replaceChildren();
    [{ id: "", label: t("全部方向") }, ...topics].forEach((topic) => {
      const button = el("button", `topic-filter${state.topic === topic.id ? " active" : ""}`, topicLabel(topic));
      button.setAttribute("aria-pressed", String(state.topic === topic.id));
      if (topic.description) button.title = topic.description;
      button.addEventListener("click", () => selectTopic(topic.id));
      filters.append(button);
      if (topic.id) {
        const sideButton = el("button", `side-topic${state.topic === topic.id ? " active" : ""}`);
        sideButton.append(el("span", "topic-dot"), el("span", "", topicLabel(topic)));
        sideButton.setAttribute("aria-pressed", String(state.topic === topic.id));
        sideButton.addEventListener("click", () => { switchView("papers"); selectTopic(topic.id); });
        side.append(sideButton);
      }
    });
  }
  function selectTopic(id) { state.topic = id; renderTopics(); loadPapers(); }
  function resetFilters() {
    state.topic = ""; state.filter = "all"; state.query = ""; state.sort = "relevance"; $("search-input").value = ""; $("sort-select").value = state.sort;
    renderTopics(); renderStatusFilters(); loadPapers();
  }
  function renderStatusFilters() {
    document.querySelectorAll(".status-filter").forEach((button) => {
      const active = button.dataset.filter === state.filter;
      button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
    });
  }
  async function loadState({ quiet = false } = {}) {
    try {
      const data = await api("/api/state");
      const wasScanning = Boolean(state.data?.scanning || state.loadingScan);
      state.data = data;
      state.loadingScan = false;
      $("connection-error").hidden = true;
      updateStats(); renderTopics(); renderNotice(); setScanButton();
      const key = data.latest_run ? `${data.latest_run.id}:${data.latest_run.status}:${data.latest_run.finished_at || ""}` : "";
      const changed = state.lastRun && key !== state.lastRun;
      state.lastRun = key;
      if ((wasScanning && !data.scanning) || changed) {
        await loadPapers({ quiet: true });
        if (state.view === "runs") await loadRuns();
        if (state.view === "digest") await loadDigest();
      }
      clearTimeout(state.poll);
      state.poll = setTimeout(() => loadState({ quiet: true }), data.scanning ? 2500 : 45000);
      return data;
    } catch (error) {
      const notice = $("connection-error");
      notice.replaceChildren(icon("info"), el("span", "", error.message));
      notice.hidden = false;
      state.loadingScan = false;
      setScanButton();
      clearTimeout(state.poll);
      state.poll = setTimeout(() => loadState({ quiet: true }), 15000);
      if (!quiet) throw error;
      return null;
    }
  }
  function badge(text, kind = "") { return el("span", `badge${kind ? ` badge-${kind}` : ""}`, text); }
  function paperCard(paper) {
    const saved = typeof paper.saved === "boolean" ? paper.saved : paper.feedback === "saved";
    const read = typeof paper.read === "boolean" ? paper.read : paper.feedback === "read";
    const hidden = typeof paper.hidden === "boolean" ? paper.hidden : paper.feedback === "irrelevant";
    const card = el("article", `paper-card${read ? " is-read" : ""}`);
    card.dataset.paperId = paper.id;
    const top = el("div", "paper-topline");
    if (paper.last_event === "new") top.append(badge(t("新发现"), "new"));
    if (["update", "updated"].includes(paper.last_event)) top.append(badge(t("版本更新"), "update"));
    if (paper.is_own) top.append(badge(t("本人论文"), "own"));
    if (saved) top.append(badge(t("已收藏"), "saved"));
    if (read) top.append(badge(t("已读过"), "read"));
    if (hidden) top.append(badge(t("已忽略")));
    top.append(badge(paper.assessment?.summary_zh ? t("已有摘要解读") : t("规则初筛"), paper.assessment?.summary_zh ? "model" : ""));
    const categories = list(paper.categories);
    if (categories.length) top.append(el("span", "paper-meta-category", categories.join(" · ")));
    const score = el("span", "paper-score", t("匹配 "));
    score.title = t("规则计算的主题相关度，不是论文质量评分；也不验证证明正确性。");
    score.append(el("b", "", count(paper.score)));
    top.append(score);
    const title = el("h3", "paper-title");
    title.append(link(paper.title || t("未提供标题"), paper.url));
    card.append(top, title);
    const authors = list(paper.authors).map((author) => typeof author === "string" ? author : author.name || "");
    card.append(el("p", "paper-authors", authors.join(" · ") || t("作者信息未提供")));
    const dates = el("div", "paper-dates");
    if (paper.date_basis === "announcement" || (!paper.published && paper.announced)) {
      dates.append(el("span", "", `${i18n.language === "zh" ? "公告" : "Announced"} ${date(paper.announced || paper.updated)}`));
      dates.append(el("span", "", t("RSS 公告信息 · 首发与修订日期待核实")));
    } else {
      if (paper.published) dates.append(el("span", "", `${i18n.language === "zh" ? "首发" : "Submitted"} ${date(paper.published)}`));
      if (paper.updated) dates.append(el("span", "", `${i18n.language === "zh" ? "更新" : "Updated"} ${date(paper.updated)}`));
    }
    dates.append(el("span", "", `arXiv:${paper.id}${paper.version ? `v${String(paper.version).replace(/^v/, "")}` : ""}`));
    card.append(dates);
    if (list(paper.topics).length) {
      const tags = el("div", "paper-tags");
      paper.topics.forEach((topic) => tags.append(el("span", "topic-tag", topicLabel(topic))));
      card.append(tags);
    }
    if (list(paper.reasons).length) {
      const reasons = el("div", "reason-block");
      reasons.append(el("span", "reason-label", t("为何相关")), el("p", "reason-text", i18n.language === "zh" ? paper.reasons.join("；") : `${t("命中词组")}: ${list(paper.matched_terms).join(", ")}`));
      card.append(reasons);
    }
    if (paper.assessment?.summary_zh) {
      const assessment = paper.assessment;
      const detail = el("details", "paper-detail");
      detail.append(el("summary", "", t("中文解读 · 基于摘要")));
      const content = el("div", "assessment-content");
      [[t("研究内容"), assessment.summary_zh], [t("与你的关联"), assessment.relevance_zh], [t("阅读边界"), assessment.caveat_zh]].forEach(([label, value]) => {
        if (value) { const text = el("p"); text.append(el("span", "assessment-label", label), document.createTextNode(value)); content.append(text); }
      });
      const priority = { read: t("建议阅读"), skim: t("建议浏览"), skip: t("可暂缓") }[assessment.priority];
      content.append(el("p", "assessment-source", [t("模型基于摘要生成，未核验全文或证明"), priority, assessment.model ? `${i18n.language === "zh" ? "模型" : "Model"}: ${assessment.model}` : "", assessment.assessed_at ? date(assessment.assessed_at) : ""].filter(Boolean).join(" · ")));
      detail.append(content); card.append(detail);
    }
    const abstract = el("details", "paper-detail");
    abstract.append(el("summary", "", t("展开原文摘要")));
    abstract.append(el("p", "abstract-text", paper.abstract || t("来源未提供摘要，请打开 arXiv 原文查看。")));
    abstract.addEventListener("toggle", () => { abstract.querySelector("summary").textContent = abstract.open ? t("收起原文摘要") : t("展开原文摘要"); });
    card.append(abstract);
    const bottom = el("div", "paper-bottom");
    const links = el("div", "paper-links");
    if (safeURL(paper.url)) { const original = link(t("arXiv 原文"), paper.url, "paper-link"); original.append(icon("arrow")); links.append(original); }
    if (safeURL(paper.pdf_url)) { const pdf = link("PDF", paper.pdf_url, "paper-link"); pdf.append(icon("arrow")); links.append(pdf); }
    const actions = el("div", "feedback-actions");
    [["saved", saved, t("收藏"), t("已收藏"), "bookmark"], ["read", read, t("读过"), t("已读过"), "check"], ["hidden", hidden, t("忽略"), t("已忽略"), "hide"]].forEach(([field, selected, label, selectedLabel, iconName]) => {
      const button = el("button", `feedback-button${selected ? " selected" : ""}`);
      const pendingKey = `${paper.id}:${field}`;
      button.dataset.library = field;
      button.append(icon(iconName), el("span", "", selected ? selectedLabel : label));
      button.setAttribute("aria-pressed", String(selected));
      button.disabled = state.libraryPending.has(pendingKey);
      button.title = i18n.language === "zh" ? (selected ? `取消${label}` : `标记为${label}（独立状态）`) : (selected ? `Clear ${label.toLowerCase()} status` : `Mark ${label.toLowerCase()} (independent status)`);
      button.setAttribute("aria-label", `${button.title}: ${paper.title}`);
      button.addEventListener("click", async () => {
        if (state.libraryPending.has(pendingKey)) return;
        state.libraryPending.add(pendingKey); button.disabled = true;
        try {
          await api("/api/library", { method: "POST", body: JSON.stringify({ id: paper.id, [field]: !selected }) });
          toast(t("阅读状态已更新，其他标记保持不变。"));
        } catch (error) { toast(error.message, true); }
        finally {
          state.libraryPending.delete(pendingKey);
          await Promise.all([loadPapers({ quiet: true }), loadState({ quiet: true })]);
        }
      });
      actions.append(button);
    });
    bottom.append(links, actions); card.append(bottom, noteEditor(paper));
    return card;
  }
  function showRetainedDraft(id) {
    const draft = state.drafts.get(id);
    if (!draft) return;
    const wrapper = el("article", "paper-card retained-draft");
    wrapper.append(el("h3", "paper-title", draft.title || id), el("p", "note-status", t("这篇论文不在当前结果中；草稿仍可编辑或另存到本地论文库。")));
    wrapper.append(noteEditor({ id, title: draft.title || id, version: draft.version, notes: draft.baseText }));
    $("paper-list").prepend(wrapper); restoreNoteFocus({ id });
  }
  function noteEditor(paper) {
    const details = el("details", "paper-detail note-editor");
    details.dataset.notesFor = paper.id;
    const summary = el("summary", "", t("阅读笔记"));
    details.append(summary);
    const savedNotes = typeof paper.notes === "string" ? paper.notes : "";
    let draft = state.drafts.get(paper.id);
    if (draft && !draft.saving && draft.text === draft.baseText) { state.drafts.delete(paper.id); draft = null; }
    details.open = Boolean(draft) || state.notesOpen.has(paper.id);
    details.addEventListener("toggle", () => {
      if (details.open) state.notesOpen.add(paper.id); else state.notesOpen.delete(paper.id);
    });
    const body = el("div", "note-body");
    const metadata = el("p", "note-metadata");
    const parts = [];
    if (paper.notes_version != null && savedNotes) {
      parts.push(i18n.language === "zh" ? `已保存笔记来自 v${paper.notes_version}` : `Saved notes from v${paper.notes_version}`);
      if (paper.notes_version !== paper.version) parts.push(i18n.language === "zh" ? `当前论文为 v${paper.version}，请核对笔记` : `Current paper: v${paper.version}; review your notes`);
    }
    if (paper.notes_updated_at && savedNotes) parts.push(`${date(paper.notes_updated_at, true)} · ${timeZone()}`);
    metadata.textContent = parts.join(" · ");
    const label = el("label", "note-label", t("你的阅读记录（纯文本）"));
    const textarea = el("textarea", "note-textarea");
    textarea.id = `notes-${paper.id.replace(/[^A-Za-z0-9_-]/g, "-")}`;
    textarea.dataset.noteEditor = paper.id;
    textarea.rows = 5;
    textarea.value = draft?.text ?? savedNotes;
    textarea.placeholder = t("记录关键假设、疑问或下一步阅读计划…");
    textarea.setAttribute("aria-label", `${t("阅读笔记")}: ${paper.title}`);
    label.htmlFor = textarea.id;
    metadata.id = `${textarea.id}-meta`;
    const status = el("p", "note-status"); status.id = `${textarea.id}-status`; status.setAttribute("role", "status");
    const error = el("p", "note-error"); error.id = `${textarea.id}-error`; error.setAttribute("role", "alert"); error.hidden = true;
    textarea.setAttribute("aria-describedby", `${metadata.id} ${status.id} ${error.id}`);
    const controls = el("div", "note-controls");
    const save = el("button", "button button-primary note-save", t("保存笔记"));
    const cancel = el("button", "button button-secondary note-cancel", t("放弃修改"));
    const length = el("span", "note-length");
    controls.append(save, cancel, length);
    body.append(metadata, label, textarea, status, error, controls); details.append(body);
    function refresh() {
      const current = state.drafts.get(paper.id);
      const dirty = Boolean(current && current.text !== current.baseText);
      const characters = [...textarea.value].length;
      save.disabled = !dirty || Boolean(current?.saving) || characters > 5000;
      cancel.disabled = !dirty || Boolean(current?.saving);
      save.textContent = current?.saving ? t("正在保存…") : t("保存笔记");
      length.textContent = `${count(characters)} / 5,000`;
      length.classList.toggle("is-over-limit", characters > 5000);
      textarea.setAttribute("aria-invalid", String(characters > 5000));
      status.textContent = current?.saving ? t("正在保存；此时继续输入的文字会保留为新草稿。") : dirty ? t("尚未保存 · 切换筛选或语言时保留草稿") : savedNotes ? t("笔记已保存到本地论文库。") : t("最多 5,000 字符；保存后可搜索与导出。 ");
      if (dirty && current.version != null && current.version !== paper.version) status.textContent += i18n.language === "zh" ? ` 草稿起于 v${current.version}；当前论文为 v${paper.version}。` : ` Draft started on v${current.version}; current paper is v${paper.version}.`;
      error.textContent = characters > 5000 ? t("笔记超过 5,000 字符，请缩短后保存；文字仍已保留。") : current?.error || "";
      error.hidden = !error.textContent;
      summary.textContent = dirty ? `${t("阅读笔记")} · ${t("未保存")}` : savedNotes ? `${t("阅读笔记")} · ${t("已保存")}` : t("阅读笔记");
      details.classList.toggle("has-unsaved-notes", dirty);
    }
    state.noteWidgets.set(paper.id, { refresh, textarea });
    textarea.addEventListener("input", () => {
      let current = state.drafts.get(paper.id);
      if (!current) {
        current = { id: paper.id, title: paper.title, text: savedNotes, baseText: savedNotes, version: paper.version, saving: false, error: "" };
        state.drafts.set(paper.id, current);
      }
      current.text = textarea.value; current.error = "";
      persistDrafts(); refresh();
    });
    cancel.addEventListener("click", () => {
      const current = state.drafts.get(paper.id);
      if (current?.saving) return;
      textarea.value = current?.baseText ?? savedNotes;
      state.drafts.delete(paper.id); persistDrafts(); refresh();
      toast(t("已放弃未保存的修改。"));
    });
    save.addEventListener("click", async () => {
      const current = state.drafts.get(paper.id);
      if (!current || current.saving || [...current.text].length > 5000) return;
      const submitted = current.text;
      current.saving = true; current.error = ""; refresh();
      try {
        const result = await api("/api/library", { method: "POST", body: JSON.stringify({ id: paper.id, notes: submitted }) });
        current.baseText = result.paper?.notes ?? submitted; current.version = result.paper?.notes_version ?? current.version; current.saving = false;
        if (current.text === current.baseText) state.drafts.delete(paper.id);
        persistDrafts(); toast(t("笔记已保存。"));
        await Promise.all([loadPapers({ quiet: true }), loadState({ quiet: true })]);
      } catch (failure) {
        current.saving = false; current.error = `${t("保存失败，草稿已保留。 ")}${failure.message}`;
        persistDrafts(); state.noteWidgets.get(paper.id)?.refresh(); toast(t("保存失败，草稿已保留。 "), true);
      }
    });
    textarea.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); if (!save.disabled) save.click(); }
    });
    refresh(); return details;
  }
  async function loadPapers({ quiet = false, focusDraft = "" } = {}) {

    const request = ++state.request;
    const container = $("paper-list");
    container.setAttribute("aria-busy", "true");
    updateExports(true);
    if (!quiet) loading(container, t("正在整理研究线索"));
    try {
      const query = viewQuery();
      const response = await api(`/api/papers?${query}`);
      if (request !== state.request) return;
      const papers = list(response.papers);
      const focus = rememberFocus();
      state.noteWidgets.clear();
      $("results-count").textContent = `${count(response.total ?? papers.length)} ${i18n.language === "zh" ? "篇" : "papers"}`;
      if (!papers.length) {
        const filtered = Boolean(state.topic || state.query || state.filter !== "all");
        const messages = {
          saved: [t("给值得读的论文留一个位置"), t("点击论文上的收藏按钮，就能在这里继续阅读。")],
          read: [t("当前没有已读论文"), t("将论文标为已读，阅读记录会独立于收藏保存。")],
          unread: [t("当前没有未读论文"), t("清除筛选查看全部线索，或开始一次新的扫描。")],
          notes: [t("当前没有保存的笔记"), t("展开论文的阅读笔记并保存，即可在这里找到。")],
          hidden: [t("这里还没有被忽略的论文"), t("不相关的线索可以标记为忽略，也可以在这里恢复。")],
          new: [t("当前没有本次新增记录"), t("以最近一次实际完成的扫描结果为准；扫描异常时请查看覆盖范围。")],
          updates: [t("当前没有版本更新记录"), t("扫描会跟踪已经收录论文的修订版本。")]
        };
        let heading = t("研究视野，从第一次扫描开始"), description = t("扫描你的关注领域，将相关论文与版本更新收录到这里。");
        if (filtered) [heading, description] = state.query || state.topic ? [t("暂时没有匹配的论文"), t("换一个关键词或研究方向，也可以清除筛选查看全部线索。")] : messages[state.filter] || [t("暂无匹配论文"), t("可调整筛选条件后重试。")];
        else if (state.data?.latest_run) [heading, description] = [t("当前论文库没有相关记录"), t("这不代表 arXiv 没有相关研究；可查看扫描状态和覆盖范围，或再次扫描。")];
        empty(container, heading, description, state.filter === "saved" ? "bookmark" : "radar", filtered ? { label: t("查看全部线索"), run: resetFilters } : undefined);
      } else container.replaceChildren(...papers.map(paperCard));
      restoreNoteFocus(focusDraft ? { id: focusDraft } : focus);
      if (focusDraft && !state.noteWidgets.has(focusDraft)) showRetainedDraft(focusDraft);
      updateExports(false);
    } catch (error) {
      if (request === state.request) { empty(container, t("论文暂时未能载入"), error.message, "info", { label: t("重新加载"), run: () => loadPapers() });
        if (focusDraft) showRetainedDraft(focusDraft); $("results-count").textContent = ""; }
    } finally { if (request === state.request) container.setAttribute("aria-busy", "false"); }
  }
  async function scan() {
    if (state.data?.scanning || state.loadingScan) return;
    state.loadingScan = true; setScanButton(); renderNotice();
    try {
      await api("/api/scan", { method: "POST", body: "{}" });
      toast(t("扫描已启动，完成后自动更新。"));
      await loadState({ quiet: true });
      if (state.view === "runs") await loadRuns();
    } catch (error) {
      state.loadingScan = false;
      if (error.status === 409) { toast(t("已有扫描正在执行。")); await loadState({ quiet: true }); }
      else { toast(error.message, true); renderNotice(); }
      setScanButton();
    }
  }
  function switchView(view) {
    if (!Object.hasOwn(viewText(), view)) return;
    state.view = view;
    document.querySelectorAll(".nav-item").forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
    Object.keys(viewText()).forEach((key) => { $(`view-${key}`).hidden = key !== view; });
    const [eyebrow, title, description] = viewText()[view];
    $("page-eyebrow").textContent = eyebrow; $("page-title").textContent = title; $("page-description").textContent = description;
    if (view === "digest") loadDigest();
    if (view === "runs") loadRuns();
  }
  function runCard(run) {
    const card = el("article", "run-card");
    const header = el("div", "run-header");
    const title = el("div");
    title.append(el("h3", "", `${date(run.started_at, true)} · ${timeZone()}`), el("div", "run-id", `${i18n.language === "zh" ? "运行" : "Run"} ${run.id || t("编号未记录")}`));
    const labels = { success: t("扫描完成"), partial: t("覆盖不完整"), failed: t("扫描失败"), running: t("扫描进行中"), pending: t("等待执行") };
    const status = el("span", "run-status", labels[run.status] || t("状态未记录"));
    if (["partial", "failed", "running"].includes(run.status)) status.classList.add(run.status);
    header.append(title, status);
    const metrics = el("div", "run-metrics");
    [[t("候选"), run.candidate_count], [t("相关"), run.relevant_count], [t("新增"), run.new_count], [t("更新"), run.updated_count]].forEach(([label, value]) => { const item = el("span", "", label); item.append(el("strong", "", count(value))); metrics.append(item); });
    card.append(header, metrics);
    if (run.coverage && typeof run.coverage === "object") {
      const from = run.coverage.since, until = run.coverage.until;
      if (from || until) card.append(el("p", "run-coverage", `${i18n.language === "zh" ? "查询区间" : "Query window"} ${date(from, true)} — ${date(until, true)} (${timeZone()})`));
      if (run.coverage.source) card.append(el("p", "run-coverage", `${i18n.language === "zh" ? "数据来源" : "Source"}: ${run.coverage.source}`));
    }
    if (run.finished_at) card.append(el("p", "run-coverage", `${i18n.language === "zh" ? "结束" : "Finished"} ${date(run.finished_at, true)} · ${timeZone()}`));
    if (list(run.errors).length) card.append(el("p", "run-error", `${t("来源错误（原文）")}: ${run.errors.map(stringify).join("\n")}`));
    const details = el("details", "run-details");
    details.append(el("summary", "", t("查看执行阶段与覆盖详情")));
    details.append(el("pre", "", stringify({ stages: run.stages || [], coverage: run.coverage || {} })));
    card.append(details);
    return card;
  }
  async function loadRuns() {
    const container = $("runs-list");
    loading(container, t("正在读取扫描记录"));
    $("refresh-runs").disabled = true;
    try {
      const response = await api("/api/runs");
      const runs = list(response.runs);
      if (runs.length) container.replaceChildren(...runs.map(runCard));
      else empty(container, t("还没有扫描记录"), t("开始一次扫描后，执行状态、覆盖范围和错误信息会保存在这里。"), "clock");
    } catch (error) { empty(container, t("扫描记录暂时未能载入"), error.message, "info", { label: t("重新加载"), run: loadRuns }); }
    finally { $("refresh-runs").disabled = false; }
  }
  function inlineMarkdown(parent, text) {
    const pattern = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
    let last = 0, match;
    while ((match = pattern.exec(text))) {
      parent.append(document.createTextNode(text.slice(last, match.index)));
      if (match[1]) parent.append(link(match[1], match[2]));
      else if (match[3]) parent.append(el("strong", "", match[3]));
      else parent.append(el("code", "", match[4]));
      last = pattern.lastIndex;
    }
    parent.append(document.createTextNode(text.slice(last)));
  }
  function renderMarkdown(markdown) {
    const sheet = el("article", "digest-sheet");
    let listNode = null, codeNode = null;
    for (const line of markdown.split(/\r?\n/)) {
      if (/^\s*```/.test(line)) { if (codeNode) codeNode = null; else { codeNode = el("pre"); sheet.append(codeNode); } listNode = null; continue; }
      if (codeNode) { codeNode.append(document.createTextNode(`${line}\n`)); continue; }
      if (!line.trim()) { listNode = null; continue; }
      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      const bullet = line.match(/^\s*(?:[-*]\s+|\d+\.\s+)(.+)$/);
      let node;
      if (heading) { node = el(heading[1].length === 1 ? "h2" : heading[1].length === 2 ? "h3" : "h4"); inlineMarkdown(node, heading[2]); listNode = null; }
      else if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { node = el("hr"); listNode = null; }
      else if (bullet) { if (!listNode) { listNode = el(/^\s*\d/.test(line) ? "ol" : "ul"); sheet.append(listNode); } node = el("li"); inlineMarkdown(node, bullet[1]); listNode.append(node); continue; }
      else if (/^>\s?/.test(line)) { node = el("blockquote"); inlineMarkdown(node, line.replace(/^>\s?/, "")); listNode = null; }
      else { node = el("p"); inlineMarkdown(node, line); listNode = null; }
      sheet.append(node);
    }
    return sheet;
  }
  async function loadDigest() {
    const container = $("digest-content");
    loading(container, t("正在读取最新日报"));
    $("copy-digest").disabled = true;
    try {
      const response = await api("/api/digest");
      state.digest = response.markdown || "";
      $("digest-meta").textContent = response.run_id ? `${i18n.language === "zh" ? "来源运行" : "Source run"}: ${response.run_id} · ${i18n.language === "zh" ? "基于实际获取的数据" : "Digest in its original language"}` : t("只汇总扫描中实际获取的论文与更新。");
      if (state.digest.trim()) { container.replaceChildren(renderMarkdown(state.digest)); $("copy-digest").disabled = false; }
      else empty(container, t("研究日报尚未生成"), t("完成一次扫描后，在这里查看本次论文线索、版本变化与覆盖说明。"), "file");
    } catch (error) { state.digest = ""; empty(container, t("日报暂时未能载入"), error.message, "info", { label: t("重新加载"), run: loadDigest }); }
  }
  async function copyDigest() {
    if (!state.digest) return;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(state.digest);
      else {
        const textarea = el("textarea"); textarea.value = state.digest; textarea.style.position = "fixed"; textarea.style.opacity = "0"; document.body.append(textarea); textarea.select();
        const copied = document.execCommand("copy"); textarea.remove(); if (!copied) throw new Error("copy denied");
      }
      toast(t("已复制研究日报。"));
    } catch { toast(t("浏览器未允许复制，请选择日报文本后手动复制。"), true); }
  }
  $("today-label").textContent = `${date(new Date().toISOString())} · ${timeZone()}`;
  document.querySelectorAll("[data-language]").forEach((button) => button.addEventListener("click", () => {
    i18n.setLanguage(button.dataset.language);
    renderDraftNotice();
    if (state.data) updateStats();
    renderTopics(); renderNotice(); setScanButton(); switchView(state.view); loadPapers({ quiet: true });
  }));
  switchView(state.view);
  $("scan-button").addEventListener("click", scan);
  $("refresh-runs").addEventListener("click", loadRuns);
  $("copy-digest").addEventListener("click", copyDigest);
  document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  document.querySelectorAll(".status-filter").forEach((button) => button.addEventListener("click", () => { state.filter = button.dataset.filter; renderStatusFilters(); loadPapers(); }));
  $("search-input").addEventListener("input", () => {
    clearTimeout(state.search); state.query = $("search-input").value.trim();
    ++state.request; updateExports(true);
    state.search = setTimeout(() => loadPapers(), 250);
  });
  $("sort-select").addEventListener("change", () => { state.sort = $("sort-select").value; loadPapers(); });
  ["bib-link", "markdown-link"].forEach((id) => $(id).addEventListener("click", (event) => {
    if ($(id).getAttribute("aria-disabled") === "true") { event.preventDefault(); return; }
    if (dirtyDrafts().length) toast(t("导出仅包含已保存的笔记，不包含未保存草稿。"));
  }));
  window.addEventListener("beforeunload", (event) => {
    if (dirtyDrafts().length) { persistDrafts(); event.preventDefault(); event.returnValue = ""; }
  });
  renderDraftNotice(); updateExports(true);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") loadState({ quiet: true }); });
  loadState().catch(() => {}).finally(() => loadPapers());
})();
