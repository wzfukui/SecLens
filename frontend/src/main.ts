import "./styles/main.css";

type Bulletin = {
  id: number;
  title: string;
  summary?: string | null;
  body_text?: string | null;
  source_slug: string;
  labels?: string[] | null;
  topics?: string[] | null;
  published_at?: string | null;
  fetched_at?: string | null;
  extra?: Record<string, unknown> | null;
};

const formatUtc = (isoString: string | undefined | null) => {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (val: number) => String(val).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(
    date.getUTCDate()
  )} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
};

const setupGlobalMenu = () => {
  const toggle = document.querySelector<HTMLButtonElement>(".menu-toggle");
  const menu = document.querySelector<HTMLDivElement>(".global-menu-list");
  if (!toggle || !menu) return;

  const setVisible = (value: boolean) => {
    menu.dataset.visible = value ? "true" : "false";
    toggle.setAttribute("aria-expanded", value ? "true" : "false");
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    const visible = menu.dataset.visible === "true";
    setVisible(!visible);
  });

  document.addEventListener("click", () => {
    setVisible(false);
  });

  menu.querySelectorAll<HTMLAnchorElement>("a").forEach((link) => {
    link.addEventListener("focus", () => {
      setVisible(true);
    });
  });
};

const setupRssModal = () => {
  const modal = document.getElementById("rss-modal");
  const modalDesc = document.getElementById("rss-modal-desc");
  const modalLink = document.getElementById("rss-modal-link");
  const copyBtn = document.getElementById("rss-copy");
  const closeBtn = document.getElementById("rss-close");
  if (!modal || !modalDesc || !modalLink || !copyBtn || !closeBtn) {
    return;
  }

  const closeModal = () => {
    modal.dataset.visible = "false";
    copyBtn.textContent = "复制链接";
  };

  const attachHandlers = (root: ParentNode) => {
    root.querySelectorAll<HTMLButtonElement>(".rss-button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const sourceTitle = btn.dataset.source;
        const slug = btn.dataset.slug;
        if (!sourceTitle || !slug) return;
        const origin = window.location.origin;
        const url = `${origin}/v1/bulletins/rss?source_slug=${slug}`;
        modalDesc.textContent = `${sourceTitle} RSS 订阅地址`;
        modalLink.textContent = url;
        modal.dataset.visible = "true";
        copyBtn.onclick = () => {
          void navigator.clipboard.writeText(url).then(() => {
            copyBtn.textContent = "已复制";
            window.setTimeout(() => {
              copyBtn.textContent = "复制链接";
            }, 1500);
          });
        };
      });
    });
  };

  attachHandlers(document);

  closeBtn.addEventListener("click", closeModal);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });
};

const setupExcerptToggles = (root: ParentNode) => {
  root.querySelectorAll<HTMLElement>(".excerpt").forEach((container) => {
    const button = container.querySelector<HTMLButtonElement>(".toggle-more");
    const paragraph = container.querySelector<HTMLParagraphElement>("p");
    const snippetNode = container.querySelector<HTMLDivElement>(".snippet-text");
    const fullNode = container.querySelector<HTMLDivElement>(".full-text");
    const showMore = container.dataset.showMore === "true";
    if (!showMore || !paragraph || !snippetNode || !fullNode) {
      if (button) button.remove();
      return;
    }

    const snippetText = snippetNode.textContent?.trim() ?? "";
    const fullText = fullNode.textContent?.trim() ?? "";

    button?.addEventListener("click", () => {
      const expanded = container.dataset.expanded === "true";
      if (!expanded) {
        paragraph.textContent = fullText;
        button.textContent = "收起";
        container.dataset.expanded = "true";
      } else {
        paragraph.textContent = snippetText;
        const ellipsis = document.createElement("span");
        ellipsis.className = "ellipsis";
        ellipsis.textContent = "…";
        paragraph.appendChild(ellipsis);
        button.textContent = "更多";
        container.dataset.expanded = "false";
      }
    });
  });
};

const buildExtraRows = (extra: Record<string, unknown> | null | undefined) => {
  if (!extra) return "";
  return Object.entries(extra)
    .map(([key, value]) => {
      const label = key.replace(/_/g, " ");
      const detail = typeof value === "string" ? value : JSON.stringify(value);
      return `
        <div class="extra-row">
          <dt>${label}</dt>
          <dd>${detail}</dd>
        </div>
      `;
    })
    .join("");
};

const buildCard = (bulletin: Bulletin) => {
  const summary = bulletin.summary ?? bulletin.body_text ?? "";
  const snippet = summary.slice(0, 360);
  const showMore = summary.length > 360;
  const wrapper = document.createElement("li");
  wrapper.className = "bulletin-card";
  wrapper.innerHTML = `
    <h2><a href="/bulletins/${bulletin.id}">${bulletin.title}</a></h2>
    <div class="meta">
      ${bulletin.published_at ? `发布时间 ${formatUtc(bulletin.published_at)}` : ""}
      ${bulletin.fetched_at ? `抓取时间 ${formatUtc(bulletin.fetched_at)}` : ""}
    </div>
    ${
      summary
        ? `
        <div class="excerpt" data-expanded="false" data-show-more="${showMore}">
          <p>${snippet}${showMore ? '<span class="ellipsis">…</span>' : ""}</p>
          <div class="snippet-text" hidden>${snippet}</div>
          <div class="full-text" hidden>${summary}</div>
          ${showMore ? '<button class="toggle-more" type="button">更多</button>' : ""}
        </div>`
        : ""
    }
    ${
      bulletin.extra
        ? `
        <details class="extra-details">
          <summary>扩展字段</summary>
          <dl class="extra-table">
            ${buildExtraRows(bulletin.extra)}
          </dl>
        </details>`
        : ""
    }
    <div class="tags">
      <span class="tag">${bulletin.source_slug}</span>
      ${(bulletin.labels ?? []).map((label) => `<span class="tag">${label}</span>`).join("")}
      ${(bulletin.topics ?? []).map((topic) => `<span class="tag">${topic}</span>`).join("")}
    </div>
  `;
  return wrapper;
};

const setupInfiniteScroll = () => {
  const listEl = document.getElementById("bulletin-list");
  const sentinel = document.getElementById("scroll-sentinel");
  if (!listEl || !sentinel) return;

  const sourceSlug = listEl.dataset.source ?? "all";
  const limit = Number.parseInt(listEl.dataset.limit ?? "20", 10);
  const total = Number.parseInt(listEl.dataset.total ?? "0", 10);
  let offset = Number.parseInt(listEl.dataset.offset ?? "0", 10);
  let loading = false;

  const loadMore = async () => {
    if (loading || offset >= total) return;
    loading = true;
    const params = new URLSearchParams({ limit: `${limit}`, offset: `${offset}` });
    if (sourceSlug !== "all") {
      params.append("source_slug", sourceSlug);
    }

    try {
      const resp = await fetch(`/v1/bulletins?${params.toString()}`);
      if (!resp.ok) throw new Error(resp.statusText);
      const data = await resp.json();
      const items: Bulletin[] = data.items ?? [];
      items.forEach((item) => {
        const card = buildCard(item);
        listEl.appendChild(card);
        setupExcerptToggles(card);
      });
      offset += items.length;
      listEl.dataset.offset = `${offset}`;
      const totalCount = data.pagination?.total ?? total;
      if (offset >= totalCount || items.length === 0) {
        observer.disconnect();
        sentinel.remove();
      }
    } catch (error) {
      console.error("加载更多资讯失败", error);
    } finally {
      loading = false;
    }
  };

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          void loadMore();
        }
      });
    },
    { rootMargin: "0px 0px 200px 0px" }
  );

  if (offset < total) {
    observer.observe(sentinel);
  } else {
    sentinel.remove();
  }
};

const bootstrap = () => {
  setupGlobalMenu();
  setupRssModal();
  setupExcerptToggles(document);
  setupInfiniteScroll();
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootstrap);
} else {
  bootstrap();
}
