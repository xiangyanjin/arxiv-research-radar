"use strict";
(() => {
  const english = {
  "保持好奇，持续发现": "STAY CURIOUS. KEEP DISCOVERING.",
  "把相关研究，留在视野里。": "Keep your research in view.",
  "关注你的研究方向，从 arXiv 的新论文与更新中寻找值得读的工作。": "Find papers worth reading, across new submissions and revisions in your field.",
  "从线索到阅读": "FROM DISCOVERY TO READING",
  "留一点时间，给新的想法。": "Make room for new ideas.",
  "一份可追溯的研究简报。初筛提供线索，结论仍需回到论文中核实。": "A digest with a traceable source. Follow promising leads back to the paper.",
  "可追溯，才值得信任": "EVERY RUN, ACCOUNTED FOR",
  "每一次发现，都有来处。": "Know where a discovery begins.",
  "保留扫描状态、数据覆盖与错误信息，区分没有新论文和未能完成扫描。": "Inspect coverage and errors. An incomplete scan is different from an empty result.",
  "未记录": "Not recorded",
  "日期未记录": "Date unavailable",
  "编号未记录": "ID unavailable",
  "连接本地服务超时，请稍后重试。": "The local service timed out. Try again shortly.",
  "无法连接本地研究雷达服务，请确认服务仍在运行。": "Cannot reach the local radar. Check that the server is running.",
  "扫描进行中": "Scan in progress",
  "正在查询 arXiv 并整理研究线索。当前显示已归档的记录，完成后会自动刷新。": "Retrieving arXiv metadata. Archived records remain visible and will refresh when the scan finishes.",
  "最近一次扫描未完成": "The latest scan did not complete",
  "暂时无法获得有效数据。已有论文记录仍被保留，可在扫描记录中查看详情并重试。": "No valid response was available. Existing records are preserved; inspect run history before retrying.",
  "本次扫描覆盖不完整": "This scan has partial coverage",
  "当前仅展示实际获取的数据，不能据此判断所有相关论文均已收录。": "Only retrieved records are shown. Other relevant papers may still be missing.",
  "数据说明": "About this feed",
  "扫描中…": "Scanning…",
  "立即扫描": "Scan now",
  "与你的方向保持连接": "A clearer view of your field",
  "还没有扫描记录 · 从第一次扫描开始": "No scans yet · start your first scan",
  "全部方向": "All topics",
  "新发现": "First discovered",
  "版本更新": "Revisions",
  "本人论文": "Own paper",
  "已收藏": "Saved",
  "已读过": "Read",
  "已忽略": "Hidden",
  "已有摘要解读": "Abstract review",
  "规则初筛": "Rule-based match",
  "匹配 ": "Match ",
  "规则计算的主题相关度，不是论文质量评分；也不验证证明正确性。": "Rule-based topic relevance, not paper quality or proof verification.",
  "未提供标题": "Untitled paper",
  "作者信息未提供": "Authors unavailable",
  "RSS 公告信息 · 首发与修订日期待核实": "RSS announcement · submission and revision dates unconfirmed",
  "为何相关": "Why it matches",
  "中文解读 · 基于摘要": "Chinese review · abstract only",
  "研究内容": "Research summary",
  "与你的关联": "Research connection",
  "阅读边界": "Evidence boundary",
  "建议阅读": "Read next",
  "建议浏览": "Skim",
  "可暂缓": "Defer",
  "模型基于摘要生成，未核验全文或证明": "Generated from the abstract; full text and proofs not checked",
  "展开原文摘要": "Read original abstract",
  "来源未提供摘要，请打开 arXiv 原文查看。": "No abstract is available in this source. Open the arXiv record.",
  "收起原文摘要": "Collapse abstract",
  "arXiv 原文": "Open arXiv",
  "收藏": "Save",
  "读过": "Read",
  "忽略": "Hide",
  "取消": "Clear",
  "标记": "Mark",
  "正在整理研究线索": "Loading research leads",
  "给值得读的论文留一个位置": "A place for your next read",
  "点击论文上的收藏按钮，就能在这里继续阅读。": "Save a paper to find it here later.",
  "这里还没有被忽略的论文": "No hidden papers",
  "不相关的线索可以标记为忽略，也可以在这里恢复。": "Hide irrelevant papers, or restore them from this view.",
  "当前没有本次新增记录": "No first discoveries in this view",
  "以最近一次实际完成的扫描结果为准；扫描异常时请查看覆盖范围。": "This reflects the latest completed or partial run. Check coverage when a scan has errors.",
  "当前没有版本更新记录": "No revisions in this view",
  "扫描会跟踪已经收录论文的修订版本。": "Scans track new versions of papers already in your collection.",
  "研究视野，从第一次扫描开始": "Your research feed starts here",
  "扫描你的关注领域，将相关论文与版本更新收录到这里。": "Scan your topics to collect relevant papers and follow their revisions.",
  "暂时没有匹配的论文": "No matching papers",
  "换一个关键词或研究方向，也可以清除筛选查看全部线索。": "Try another query or topic, or clear the filters to see all leads.",
  "暂无匹配论文": "No matches yet",
  "可调整筛选条件后重试。": "Try adjusting your filters.",
  "当前论文库没有相关记录": "No relevant papers in the collection yet",
  "这不代表 arXiv 没有相关研究；可查看扫描状态和覆盖范围，或再次扫描。": "Check scan coverage or try again. This does not mean there is no relevant research on arXiv.",
  "查看全部线索": "Show all papers",
  "论文暂时未能载入": "Could not load papers",
  "重新加载": "Try again",
  "扫描已启动，完成后自动更新。": "Scan started. The feed will refresh when it finishes.",
  "已有扫描正在执行。": "A scan is already running.",
  "扫描完成": "Scan complete",
  "覆盖不完整": "Partial coverage",
  "扫描失败": "Scan failed",
  "等待执行": "Pending",
  "状态未记录": "Status unavailable",
  "候选": "Retrieved",
  "相关": "Relevant",
  "新增": "Discovered",
  "更新": "Revised",
  "查看执行阶段与覆盖详情": "Inspect stages and coverage · source text",
  "正在读取扫描记录": "Loading run history",
  "还没有扫描记录": "No scans yet",
  "开始一次扫描后，执行状态、覆盖范围和错误信息会保存在这里。": "After a scan, its status, coverage, and errors appear here.",
  "扫描记录暂时未能载入": "Could not load run history",
  "正在读取最新日报": "Loading the latest digest",
  "只汇总扫描中实际获取的论文与更新。": "Includes retrieved records only. Digest text is shown in its original language.",
  "研究日报尚未生成": "No digest yet",
  "完成一次扫描后，在这里查看本次论文线索、版本变化与覆盖说明。": "Complete a scan to see discoveries, revisions, and coverage notes here.",
  "日报暂时未能载入": "Could not load the digest",
  "已复制研究日报。": "Digest copied.",
  "浏览器未允许复制，请选择日报文本后手动复制。": "Clipboard access was unavailable. Select the digest text and copy it manually.",
  "跳至主要内容": "Skip to content",
  "研究雷达导航": "Research radar navigation",
  "arXiv 研究雷达首页": "arXiv Research Radar home",
  "研究雷达": "Research Radar",
  "工作空间": "WORKSPACE",
  "研究动态": "Research feed",
  "研究日报": "Research digest",
  "扫描记录": "Run history",
  "关注领域": "RESEARCH TOPICS",
  "本地研究工作台": "Local research workspace",
  "从公开资料发现相关研究，": "Discover public research.",
  "为下一次深入阅读留一条线索。": "Keep a lead for your next deep read.",
  "开放研究 · 本地记录": "Open research · local records",
  "论文研究动态": "Research feed",
  "你的研究视野": "YOUR RESEARCH AT A GLANCE",
  "连接研究线索": "Connect your research leads",
  "正在读取扫描状态…": "Loading scan status…",
  "相关论文": "Relevant papers",
  "已收录": "In your collection",
  "本次新增": "Discovered",
  "首次发现": "First seen",
  "已有论文": "Tracked papers",
  "我的收藏": "Saved papers",
  "留待阅读": "Read later",
  "论文线索": "Research leads",
  "主题相关度基于标题、摘要与分类，不代表论文质量或证明正确性。": "Relevance uses titles, abstracts, and categories. It does not assess paper quality.",
  "优先导出收藏；没有收藏时导出排名靠前的相关论文，数量由日报配置决定": "Exports saved papers, or top-ranked papers when none are saved. The digest limit sets the fallback count.",
  "导出 BibTeX": "Export BibTeX",
  "研究方向筛选": "Filter by topic",
  "论文状态筛选": "Filter by paper status",
  "全部": "All",
  "搜索标题、作者或关键词": "Search titles, authors, keywords",
  "正在载入研究线索": "Loading your research feed",
  "读取本地论文库与最近扫描记录。": "Reading the local collection and recent scans.",
  "最新研究日报": "Latest research digest",
  "复制日报": "Copy digest",
  "扫描运行记录": "Scan run history",
  "每次扫描，都有记录": "Every scan leaves a record",
  "查看数据覆盖范围、执行过程和来源异常。": "Inspect source coverage, execution stages, and retrieval errors.",
  "刷新记录": "Refresh",
  "arXiv 研究雷达": "arXiv Research Radar",
  "公开来源 · 本地记录 · 摘要级初筛": "Public sources · local records · abstract-level screening",
  "围绕随机矩阵、尖峰张量、马尔可夫链与高维概率的本地 arXiv 研究雷达。": "A local arXiv research feed with explainable ranking, revision tracking, and evidence-checked reviews.",
  "选择界面语言": "Choose interface language",
  "依据标题与摘要进行方向匹配。相关性不代表论文质量或证明正确性。": "Recommendations use titles and abstracts. Relevance is not paper quality or proof verification.",
  "来源错误（原文）": "Source errors (original text)",
  "命中词组": "Matched phrases",
  "研究配置": "Research profile"
};
  let language = "en";
  try { language = localStorage.getItem("arxiv-radar-language") === "zh" ? "zh" : "en"; } catch {}
  const textNodes = [];
  const attributes = [];
  function t(text) { return language === "zh" ? text : (english[text] || text); }
  function init() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const key = node.nodeValue.trim();
      if (Object.hasOwn(english, key)) textNodes.push({ node, original: node.nodeValue, key });
    }
    document.querySelectorAll("[aria-label], [title], [placeholder], meta[name='description']").forEach((element) => {
      ["aria-label", "title", "placeholder", "content"].forEach((name) => {
        const value = element.getAttribute(name);
        if (value && Object.hasOwn(english, value)) attributes.push({ element, name, value });
      });
    });
    apply();
  }
  function apply() {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
    document.title = t("arXiv 研究雷达");
    textNodes.forEach(({ node, original, key }) => {
      if (node.isConnected) node.nodeValue = original.replace(key, t(key));
    });
    attributes.forEach(({ element, name, value }) => element.setAttribute(name, t(value)));
    document.querySelectorAll("[data-language]").forEach((button) => {
      const active = button.dataset.language === language;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }
  function setLanguage(value) {
    language = value === "zh" ? "zh" : "en";
    try { localStorage.setItem("arxiv-radar-language", language); } catch {}
    apply();
  }
  window.RadarI18n = { t, init, setLanguage, get language() { return language; } };
})();
