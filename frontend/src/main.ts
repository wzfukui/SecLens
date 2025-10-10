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

const AUTH_STORAGE_KEY = "seclens:authTokens";
const USER_META_KEY = "seclens:userMeta";
const AUTH_ERROR = "AUTH_MISSING";

type StoredTokens = {
  accessToken: string;
  refreshToken: string;
};

type TokenResponse = {
  access_token: string;
  refresh_token: string;
};

type UserProfile = {
  id: number;
  email: string;
  display_name?: string | null;
  is_admin: boolean;
};

type VipStatus = {
  is_vip: boolean;
  vip_activated_at?: string | null;
  vip_expires_at?: string | null;
  remaining_days?: number | null;
};

type NotificationSetting = {
  webhook_url?: string | null;
  notify_email?: string | null;
  send_webhook: boolean;
  send_email: boolean;
  updated_at: string;
};

type PushRule = {
  id: number;
  name: string;
  keyword: string;
  is_active: boolean;
  notify_via_webhook: boolean;
  notify_via_email: boolean;
  created_at: string;
  updated_at: string;
};

type Subscription = {
  id: number;
  name: string;
  channel_slugs: string[];
  keyword_filter?: string | null;
  is_active: boolean;
  token: string;
  rss_url?: string | null;
  created_at: string;
  updated_at: string;
};

type PluginSummary = {
  id: number;
  slug: string;
  name: string;
  display_name?: string | null;
};

const getStoredTokens = (): StoredTokens | null => {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredTokens | null;
    if (!parsed || !parsed.accessToken) return null;
    return parsed;
  } catch {
    return null;
  }
};

const setAuthTokens = (tokens: TokenResponse) => {
  const stored: StoredTokens = {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
  };
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(stored));
};

const clearAuthTokens = () => {
  localStorage.removeItem(AUTH_STORAGE_KEY);
  localStorage.removeItem(USER_META_KEY);
  void fetch("/auth/logout", { method: "POST", credentials: "include" }).catch(() => {
    /* ignore */
  });
};

type StoredUserMeta = {
  isAdmin: boolean;
};

const getStoredUserMeta = (): StoredUserMeta | null => {
  try {
    const raw = localStorage.getItem(USER_META_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredUserMeta;
  } catch {
    return null;
  }
};

const setStoredUserMeta = (meta: StoredUserMeta | null) => {
  if (!meta) {
    localStorage.removeItem(USER_META_KEY);
    return;
  }
  localStorage.setItem(USER_META_KEY, JSON.stringify(meta));
};

const updateAuthMenu = () => {
  const tokens = getStoredTokens();
  const isLoggedIn = Boolean(tokens?.accessToken);
  document.querySelectorAll<HTMLElement>("[data-auth]").forEach((node) => {
    const state = node.dataset.auth;
    if (state === "auth") {
      node.style.display = isLoggedIn ? "" : "none";
    } else if (state === "guest") {
      node.style.display = isLoggedIn ? "none" : "";
    }
  });
  const userMeta = getStoredUserMeta();
  document.querySelectorAll<HTMLElement>("[data-admin]").forEach((node) => {
    const visible = Boolean(isLoggedIn && userMeta?.isAdmin);
    node.style.display = visible ? "" : "none";
  });
};

const setupAuthMenu = () => {
  updateAuthMenu();
  const logoutLink = document.getElementById("logout-link");
  if (logoutLink) {
    logoutLink.addEventListener("click", (event) => {
      event.preventDefault();
      clearAuthTokens();
      updateAuthMenu();
      window.location.href = "/";
    });
  }
};

const parseErrorResponse = async (resp: Response): Promise<string> => {
  const text = await resp.text();
  if (!text) return resp.statusText;
  try {
    const data = JSON.parse(text) as { detail?: string; message?: string };
    return data.detail ?? data.message ?? text;
  } catch (error) {
    return text;
  }
};

const fetchWithAuth = async (
  input: RequestInfo,
  options: RequestInit = {},
  attempt = 0
): Promise<Response> => {
  const tokens = getStoredTokens();
  if (!tokens) {
    throw new Error(AUTH_ERROR);
  }

  const headers = new Headers(options.headers ?? {});
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Authorization", `Bearer ${tokens.accessToken}`);

  const response = await fetch(input, {
    credentials: "include",
    ...options,
    headers,
  });

  if (response.status !== 401 || attempt > 0) {
    if (response.status === 401) {
      clearAuthTokens();
      updateAuthMenu();
    }
    return response;
  }

  if (!tokens.refreshToken) {
    clearAuthTokens();
    updateAuthMenu();
    return response;
  }

  const refreshResponse = await fetch("/auth/refresh", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ refresh_token: tokens.refreshToken }),
  });

  if (!refreshResponse.ok) {
    clearAuthTokens();
    updateAuthMenu();
    return response;
  }

  const tokenPair = (await refreshResponse.json()) as TokenResponse;
  setAuthTokens(tokenPair);
  updateAuthMenu();
  return fetchWithAuth(input, options, attempt + 1);
};

const fetchJsonWithAuth = async <T>(url: string, options?: RequestInit): Promise<T> => {
  const response = await fetchWithAuth(url, options);
  if (!response.ok) {
    throw new Error(await parseErrorResponse(response));
  }
  return (await response.json()) as T;
};

const requestWithAuth = async (url: string, options?: RequestInit): Promise<void> => {
  const response = await fetchWithAuth(url, options);
  if (!response.ok) {
    throw new Error(await parseErrorResponse(response));
  }
};

const setMessage = (node: HTMLElement | null, message: string, state?: "error" | "success") => {
  if (!node) return;
  node.textContent = message;
  if (state) {
    node.dataset.state = state;
  } else {
    delete node.dataset.state;
  }
};

const formatDateTime = (iso?: string | null): string => {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const setupLoginPage = () => {
  if (document.body.dataset.page !== "login") return;
  const form = document.getElementById("login-form") as HTMLFormElement | null;
  const messageEl = document.getElementById("login-message");
  if (!form) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const email = String(formData.get("email") ?? "").trim();
    const password = String(formData.get("password") ?? "");
    if (!email || !password) {
      setMessage(messageEl, "请输入邮箱和密码", "error");
      return;
    }
    setMessage(messageEl, "正在登录…");
    try {
      const resp = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });
      if (!resp.ok) {
        throw new Error(await parseErrorResponse(resp));
      }
      const tokens = (await resp.json()) as TokenResponse & { token_type: string };
      setAuthTokens(tokens);
      let destination = "/dashboard";
      try {
        const user = await fetchJsonWithAuth<UserProfile>("/auth/me");
        setStoredUserMeta({ isAdmin: Boolean(user.is_admin) });
        destination = user.is_admin ? "/admin" : "/dashboard";
      } catch (error) {
        setStoredUserMeta({ isAdmin: false });
      }
      updateAuthMenu();
      setMessage(messageEl, "登录成功，即将跳转…", "success");
      window.setTimeout(() => {
        window.location.href = destination;
      }, 400);
    } catch (error) {
      setMessage(messageEl, error instanceof Error ? error.message : "登录失败", "error");
    }
  });
};

const setupRegisterPage = () => {
  if (document.body.dataset.page !== "register") return;
  const form = document.getElementById("register-form") as HTMLFormElement | null;
  const messageEl = document.getElementById("register-message");
  if (!form) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const email = String(formData.get("email") ?? "").trim();
    const displayName = String(formData.get("display_name") ?? "").trim();
    const password = String(formData.get("password") ?? "");
    const confirm = String(formData.get("confirm_password") ?? "");
    if (!email || !password) {
      setMessage(messageEl, "请填写邮箱和密码", "error");
      return;
    }
    if (password !== confirm) {
      setMessage(messageEl, "两次输入的密码不一致", "error");
      return;
    }
    setMessage(messageEl, "正在创建账户…");
    try {
      const resp = await fetch("/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, display_name: displayName || null }),
      });
      if (!resp.ok) {
        throw new Error(await parseErrorResponse(resp));
      }
      // 自动登录
      const loginResp = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });
      if (!loginResp.ok) {
        throw new Error(await parseErrorResponse(loginResp));
      }
      const tokens = (await loginResp.json()) as TokenResponse & { token_type: string };
      setAuthTokens(tokens);
      let destination = "/dashboard";
      try {
        const user = await fetchJsonWithAuth<UserProfile>("/auth/me");
        setStoredUserMeta({ isAdmin: Boolean(user.is_admin) });
        destination = user.is_admin ? "/admin" : "/dashboard";
      } catch (error) {
        setStoredUserMeta({ isAdmin: false });
      }
      updateAuthMenu();
      setMessage(messageEl, "注册成功，即将进入控制台…", "success");
      window.setTimeout(() => {
        window.location.href = destination;
      }, 500);
    } catch (error) {
      setMessage(messageEl, error instanceof Error ? error.message : "注册失败", "error");
    }
  });
};

const setupDashboardPage = () => {
  if (document.body.dataset.page !== "dashboard") return;
  const tokens = getStoredTokens();
  if (!tokens) {
    window.location.href = "/login";
    return;
  }

  const userNameEl = document.getElementById("user-name");
  const userEmailEl = document.getElementById("user-email");
  const vipStatusEl = document.getElementById("vip-status");
  const vipDetailEl = document.getElementById("vip-detail");
  const activationForm = document.getElementById("activation-form") as HTMLFormElement | null;
  const activationMessage = document.getElementById("activation-message");
  const notificationForm = document.getElementById("notification-form") as HTMLFormElement | null;
  const notificationMessage = document.getElementById("notification-message");
  const pushRulesList = document.getElementById("push-rules-list");
  const pushRuleForm = document.getElementById("push-rule-form") as HTMLFormElement | null;
  const pushRuleMessage = document.getElementById("push-rule-message");
  const subscriptionList = document.getElementById("subscription-list");
  const subscriptionForm = document.getElementById("subscription-form") as HTMLFormElement | null;
  const subscriptionMessage = document.getElementById("subscription-message");
  const channelsSelect = document.getElementById("subscription-channels") as HTMLSelectElement | null;
  const menuButtons = Array.from(document.querySelectorAll<HTMLButtonElement>(".dashboard-menu .menu-item"));
  const panels = Array.from(document.querySelectorAll<HTMLElement>(".dashboard-panel"));

  let pluginMap = new Map<string, string>();
  let currentRules: PushRule[] = [];
  let currentSubscriptions: Subscription[] = [];

  const renderVip = (status: VipStatus) => {
    if (vipStatusEl) {
      vipStatusEl.textContent = status.is_vip ? "VIP 已激活" : "未激活";
      vipStatusEl.dataset.state = status.is_vip ? "active" : "inactive";
    }
    if (vipDetailEl) {
      if (!status.is_vip || !status.vip_expires_at) {
        vipDetailEl.textContent = "激活后即可享受自定义订阅与推送服务。";
      } else {
        const remain = status.remaining_days ?? 0;
        vipDetailEl.textContent = `有效期至 ${formatDateTime(
          status.vip_expires_at
        )} · 剩余约 ${remain} 天`;
      }
    }
    const activationPanel = document.getElementById("activation-panel");
    if (activationPanel) {
      activationPanel.style.display = status.is_vip ? "none" : "grid";
    }
  };

  const renderNotification = (setting: NotificationSetting) => {
    if (!notificationForm) return;
    const webhookInput = notificationForm.elements.namedItem("webhook_url") as HTMLInputElement | null;
    const emailInput = notificationForm.elements.namedItem("notify_email") as HTMLInputElement | null;
    const webhookCheckbox = notificationForm.elements.namedItem("send_webhook") as HTMLInputElement | null;
    const emailCheckbox = notificationForm.elements.namedItem("send_email") as HTMLInputElement | null;
    if (webhookInput) webhookInput.value = setting.webhook_url ?? "";
    if (emailInput) emailInput.value = setting.notify_email ?? "";
    if (webhookCheckbox) webhookCheckbox.checked = Boolean(setting.send_webhook);
    if (emailCheckbox) emailCheckbox.checked = Boolean(setting.send_email);
  };

  const renderPushRules = () => {
    if (!pushRulesList) return;
    pushRulesList.innerHTML = "";
    if (!currentRules.length) {
      const empty = document.createElement("li");
      empty.textContent = "暂未配置规则。";
      pushRulesList.appendChild(empty);
      return;
    }
    currentRules.forEach((rule) => {
      const li = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = rule.name;
      const keyword = document.createElement("div");
      keyword.textContent = `关键词：${rule.keyword}`;
      const channels: string[] = [];
      if (rule.notify_via_webhook) channels.push("Webhook");
      if (rule.notify_via_email) channels.push("邮件");
      const meta = document.createElement("div");
      meta.textContent = `状态：${rule.is_active ? "启用" : "停用"} · 渠道：${
        channels.length ? channels.join(" / ") : "未配置"
      }`;
      const actions = document.createElement("div");
      actions.className = "item-actions";
      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.textContent = rule.is_active ? "停用" : "启用";
      toggleBtn.addEventListener("click", async () => {
        try {
          await requestWithAuth(`/users/me/push-rules/${rule.id}`, {
            method: "PUT",
            body: JSON.stringify({ is_active: !rule.is_active }),
          });
          currentRules = await fetchJsonWithAuth<PushRule[]>("/users/me/push-rules");
          renderPushRules();
          setMessage(pushRuleMessage, "规则状态已更新", "success");
        } catch (error) {
          setMessage(
            pushRuleMessage,
            error instanceof Error ? error.message : "更新失败",
            "error"
          );
        }
      });
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.dataset.variant = "danger";
      deleteBtn.textContent = "删除";
      deleteBtn.addEventListener("click", async () => {
        if (!window.confirm(`确定删除规则「${rule.name}」?`)) return;
        try {
          await requestWithAuth(`/users/me/push-rules/${rule.id}`, { method: "DELETE" });
          currentRules = await fetchJsonWithAuth<PushRule[]>("/users/me/push-rules");
          renderPushRules();
          setMessage(pushRuleMessage, "已删除规则", "success");
        } catch (error) {
          setMessage(
            pushRuleMessage,
            error instanceof Error ? error.message : "删除失败",
            "error"
          );
        }
      });
      actions.append(toggleBtn, deleteBtn);
      li.append(title, keyword, meta, actions);
      pushRulesList.appendChild(li);
    });
  };

  const renderSubscriptions = () => {
    if (!subscriptionList) return;
    subscriptionList.innerHTML = "";
    if (!currentSubscriptions.length) {
      const empty = document.createElement("li");
      empty.textContent = "暂未创建订阅。";
      subscriptionList.appendChild(empty);
      return;
    }
    currentSubscriptions.forEach((sub) => {
      const li = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = sub.name;
      const channels = document.createElement("div");
      const channelNames = sub.channel_slugs.map(
        (slug) => pluginMap.get(slug) ?? slug
      );
      channels.textContent = `渠道：${channelNames.length ? channelNames.join(" / ") : "全部"}`;
      const keyword = document.createElement("div");
      keyword.textContent = sub.keyword_filter ? `关键词：${sub.keyword_filter}` : "关键词：未设置";
      const linkRow = document.createElement("div");
      if (sub.rss_url) {
        const link = document.createElement("a");
        link.href = sub.rss_url;
        link.textContent = "复制订阅地址";
        link.target = "_blank";
        link.rel = "noopener";
        linkRow.append("订阅地址：", link);
      }
      const meta = document.createElement("div");
      meta.textContent = `状态：${sub.is_active ? "启用" : "停用"} · 创建于 ${formatDateTime(
        sub.created_at
      )}`;
      const actions = document.createElement("div");
      actions.className = "item-actions";
      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.textContent = sub.is_active ? "停用" : "启用";
      toggleBtn.addEventListener("click", async () => {
        try {
          await requestWithAuth(`/users/me/subscriptions/${sub.id}`, {
            method: "PUT",
            body: JSON.stringify({ is_active: !sub.is_active }),
          });
          currentSubscriptions = await fetchJsonWithAuth<Subscription[]>(
            "/users/me/subscriptions"
          );
          renderSubscriptions();
          setMessage(subscriptionMessage, "订阅状态已更新", "success");
        } catch (error) {
          setMessage(
            subscriptionMessage,
            error instanceof Error ? error.message : "更新失败",
            "error"
          );
        }
      });
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.dataset.variant = "danger";
      deleteBtn.textContent = "删除";
      deleteBtn.addEventListener("click", async () => {
        if (!window.confirm(`确定删除订阅「${sub.name}」?`)) return;
        try {
          await requestWithAuth(`/users/me/subscriptions/${sub.id}`, { method: "DELETE" });
          currentSubscriptions = await fetchJsonWithAuth<Subscription[]>(
            "/users/me/subscriptions"
          );
          renderSubscriptions();
          setMessage(subscriptionMessage, "订阅已删除", "success");
        } catch (error) {
          setMessage(
            subscriptionMessage,
            error instanceof Error ? error.message : "删除失败",
            "error"
          );
        }
      });
      actions.append(toggleBtn, deleteBtn);
      li.append(title, channels, keyword);
      if (linkRow.textContent) li.append(linkRow);
      li.append(meta, actions);
      subscriptionList.appendChild(li);
    });
  };

  const initializeChannelsSelect = (plugins: PluginSummary[]) => {
    pluginMap = new Map(
      plugins.map((plugin) => [plugin.slug, plugin.display_name ?? plugin.name ?? plugin.slug])
    );
    if (!channelsSelect) return;
    channelsSelect.innerHTML = "";
    plugins.forEach((plugin) => {
      const option = document.createElement("option");
      option.value = plugin.slug;
      option.textContent = plugin.display_name ?? plugin.name ?? plugin.slug;
      channelsSelect.appendChild(option);
    });
  };

  const loadDashboard = async () => {
    try {
      setMessage(pushRuleMessage, "");
      setMessage(notificationMessage, "");
      setMessage(subscriptionMessage, "");
      const [
        user,
        vip,
        notification,
        rules,
        subscriptions,
        pluginResponse,
      ] = await Promise.all([
        fetchJsonWithAuth<UserProfile>("/auth/me"),
        fetchJsonWithAuth<VipStatus>("/users/me/vip"),
        fetchJsonWithAuth<NotificationSetting>("/users/me/notifications"),
        fetchJsonWithAuth<PushRule[]>("/users/me/push-rules"),
        fetchJsonWithAuth<Subscription[]>("/users/me/subscriptions"),
        fetch("/v1/plugins").then(async (resp) => {
          if (!resp.ok) return { items: [] as PluginSummary[] };
          const data = await resp.json();
          return data as { items: PluginSummary[] };
        }),
      ]);
      setStoredUserMeta({ isAdmin: Boolean(user.is_admin) });
      updateAuthMenu();
      if (userNameEl) {
        userNameEl.textContent = user.display_name || user.email;
      }
      if (userEmailEl) {
        userEmailEl.textContent = user.email;
      }
      renderVip(vip);
      renderNotification(notification);
      currentRules = rules;
      renderPushRules();
      currentSubscriptions = subscriptions;
      renderSubscriptions();
      initializeChannelsSelect(pluginResponse.items ?? []);
    } catch (error) {
      if (error instanceof Error && error.message === AUTH_ERROR) {
        window.location.href = "/login";
        return;
      }
      setMessage(
        subscriptionMessage,
        error instanceof Error ? error.message : "加载控制台失败",
        "error"
      );
    }
  };

  if (activationForm) {
    activationForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(activationForm);
      const code = String(formData.get("code") ?? "").trim();
      if (!code) {
        setMessage(activationMessage, "请输入激活码", "error");
        return;
      }
      setMessage(activationMessage, "正在激活…");
      try {
        const status = await fetchJsonWithAuth<VipStatus>("/users/me/activate", {
          method: "POST",
          body: JSON.stringify({ code }),
        });
        renderVip(status);
        const codeInput = activationForm.elements.namedItem("code") as HTMLInputElement | null;
        if (codeInput) {
          codeInput.value = "";
        }
        setMessage(activationMessage, "激活成功！", "success");
      } catch (error) {
        setMessage(
          activationMessage,
          error instanceof Error ? error.message : "激活失败",
          "error"
        );
      }
    });
  }

  if (notificationForm) {
    notificationForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(notificationForm);
      const payload = {
        webhook_url: String(formData.get("webhook_url") ?? "") || null,
        notify_email: String(formData.get("notify_email") ?? "") || null,
        send_webhook: formData.get("send_webhook") === "on",
        send_email: formData.get("send_email") === "on",
      };
      setMessage(notificationMessage, "正在保存…");
      try {
        const setting = await fetchJsonWithAuth<NotificationSetting>("/users/me/notifications", {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        renderNotification(setting);
        setMessage(notificationMessage, "通知设置已更新", "success");
      } catch (error) {
        setMessage(
          notificationMessage,
          error instanceof Error ? error.message : "保存失败",
          "error"
        );
      }
    });
  }

  if (pushRuleForm) {
    pushRuleForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(pushRuleForm);
      const payload = {
        name: String(formData.get("name") ?? "").trim(),
        keyword: String(formData.get("keyword") ?? "").trim(),
        is_active: formData.get("is_active") === "on",
        notify_via_webhook: formData.get("notify_via_webhook") === "on",
        notify_via_email: formData.get("notify_via_email") === "on",
      };
      if (!payload.name || !payload.keyword) {
        setMessage(pushRuleMessage, "请填写规则名称与关键词", "error");
        return;
      }
      try {
        await fetchJsonWithAuth<PushRule>("/users/me/push-rules", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        pushRuleForm.reset();
        currentRules = await fetchJsonWithAuth<PushRule[]>("/users/me/push-rules");
        renderPushRules();
        setMessage(pushRuleMessage, "规则已创建", "success");
      } catch (error) {
        setMessage(
          pushRuleMessage,
          error instanceof Error ? error.message : "创建失败",
          "error"
        );
      }
    });
  }

  if (subscriptionForm) {
    subscriptionForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(subscriptionForm);
      const name = String(formData.get("name") ?? "").trim();
      if (!name) {
        setMessage(subscriptionMessage, "请填写订阅名称", "error");
        return;
      }
      const keywordFilter = String(formData.get("keyword_filter") ?? "").trim();
      const selectedChannels = Array.from(
        channelsSelect?.selectedOptions ?? []
      ).map((option) => option.value);
      const payload = {
        name,
        keyword_filter: keywordFilter || null,
        channel_slugs: selectedChannels,
        is_active: formData.get("is_active") === "on",
      };
      try {
        await fetchJsonWithAuth<Subscription>("/users/me/subscriptions", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        subscriptionForm.reset();
        currentSubscriptions = await fetchJsonWithAuth<Subscription[]>(
          "/users/me/subscriptions"
        );
        renderSubscriptions();
        setMessage(subscriptionMessage, "订阅已创建", "success");
      } catch (error) {
        setMessage(
          subscriptionMessage,
          error instanceof Error ? error.message : "创建失败",
          "error"
        );
      }
    });
  }

  if (menuButtons.length && panels.length) {
    const activatePanel = (targetId: string) => {
      panels.forEach((panel) => {
        panel.classList.toggle("is-active", panel.id === targetId);
      });
      menuButtons.forEach((button) => {
        button.classList.toggle("is-active", button.dataset.target === targetId);
      });
    };
    menuButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const targetId = button.dataset.target;
        if (!targetId) return;
        activatePanel(targetId);
      });
    });
  }

  void loadDashboard();
};

const setupAdminPage = () => {
  if (document.body.dataset.page !== "admin") return;
  const menuButtons = Array.from(document.querySelectorAll<HTMLButtonElement>(".dashboard-menu .menu-item"));
  const panels = Array.from(document.querySelectorAll<HTMLElement>(".dashboard-panel"));
  if (!menuButtons.length || !panels.length) return;

  const activatePanel = (targetId: string) => {
    panels.forEach((panel) => {
      panel.classList.toggle("is-active", panel.id === targetId);
    });
    menuButtons.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.target === targetId);
    });
  };

  menuButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.dataset.target;
      if (targetId) {
        activatePanel(targetId);
      }
    });
  });
};

const bootstrap = () => {
  setupGlobalMenu();
  setupRssModal();
  setupExcerptToggles(document);
  setupInfiniteScroll();
  setupAuthMenu();
  setupLoginPage();
  setupRegisterPage();
  setupDashboardPage();
  setupAdminPage();
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootstrap);
} else {
  bootstrap();
}
