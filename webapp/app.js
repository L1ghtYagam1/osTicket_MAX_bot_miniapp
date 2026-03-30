const state = {
  maxUserId: localStorage.getItem("max_user_id") || "",
  fullName: localStorage.getItem("full_name") || "",
  accessToken: localStorage.getItem("access_token") || "",
  isAdmin: false,
  user: null,
  appSettings: null,
  appThemeSettings: null,
  appUiSettings: null,
  integrationSettings: null,
  catalog: null,
};

const api = {
  async request(path, options = {}) {
    const response = await fetch(path, {
      headers: {
        "Content-Type": "application/json",
        ...(state.accessToken ? { Authorization: `Bearer ${state.accessToken}` } : {}),
        ...(options.headers || {}),
      },
      ...options,
    });

    const text = await response.text();
    let data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { detail: text };
      }
    }
    if (!response.ok) {
      throw new Error(data.detail || text || `HTTP ${response.status}`);
    }
    return data;
  },

  requestEmailCode(payload) {
    return this.request("/api/v1/auth/request-email-code", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  verifyEmailCode(payload) {
    return this.request("/api/v1/auth/verify-email-code", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  createWebAppSession(initData) {
    return this.request("/api/v1/auth/webapp-session", {
      method: "POST",
      body: JSON.stringify({ init_data: initData }),
    });
  },

  getMe() {
    return this.request("/api/v1/auth/me");
  },

  getCatalog() {
    return this.request("/api/v1/catalog");
  },

  getAppSettings() {
    return this.request("/api/v1/app-settings");
  },

  getAppThemeSettings() {
    return this.request("/api/v1/app-theme-settings");
  },

  getAppUiSettings() {
    return this.request("/api/v1/app-ui-settings");
  },

  getIntegrationSettings() {
    return this.request("/api/v1/integration-settings");
  },

  getUserByMaxId(maxUserId) {
    return this.request(`/api/v1/users/by-max/${encodeURIComponent(maxUserId)}`);
  },

  getTickets(maxUserId) {
    return this.request(`/api/v1/tickets?max_user_id=${encodeURIComponent(maxUserId)}`);
  },

  createTicket(payload) {
    return this.request("/api/v1/tickets", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  adminListUsers() {
    return this.request("/api/v1/admin/users");
  },

  adminUpdateUser(id, payload) {
    return this.request(`/api/v1/admin/users/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  adminGetUserTicketAccess(id) {
    return this.request(`/api/v1/admin/users/${id}/ticket-access`);
  },

  adminUpdateUserTicketAccess(id, payload) {
    return this.request(`/api/v1/admin/users/${id}/ticket-access`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  adminListHotels() {
    return this.request("/api/v1/admin/hotels");
  },

  adminCreateHotel(name) {
    return this.request("/api/v1/admin/hotels", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  },

  adminUpdateHotel(id, payload) {
    return this.request(`/api/v1/admin/hotels/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  adminListCategories() {
    return this.request("/api/v1/admin/categories");
  },

  adminCreateCategory(payload) {
    return this.request("/api/v1/admin/categories", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  adminUpdateCategory(id, payload) {
    return this.request(`/api/v1/admin/categories/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  adminListTopics() {
    return this.request("/api/v1/admin/topics");
  },

  adminCreateTopic(payload) {
    return this.request("/api/v1/admin/topics", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  adminUpdateTopic(id, payload) {
    return this.request(`/api/v1/admin/topics/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  adminListAuditLogs() {
    return this.request("/api/v1/admin/audit-logs");
  },

  adminUpdateAppSettings(payload) {
    return this.request("/api/v1/admin/app-settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  adminUpdateAppThemeSettings(payload) {
    return this.request("/api/v1/admin/app-theme-settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  adminUpdateAppUiSettings(payload) {
    return this.request("/api/v1/admin/app-ui-settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  adminUpdateIntegrationSettings(payload) {
    return this.request("/api/v1/admin/integration-settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
};

function byId(id) {
  return document.getElementById(id);
}

function setLaunchStatus(message) {
  byId("maxLaunchStatus").textContent = message;
}

function persistSession() {
  localStorage.setItem("max_user_id", state.maxUserId);
  localStorage.setItem("full_name", state.fullName);
  if (state.accessToken) {
    localStorage.setItem("access_token", state.accessToken);
  } else {
    localStorage.removeItem("access_token");
  }
}

function hydrateSession() {
  byId("maxUserId").value = state.maxUserId;
  byId("fullName").value = state.fullName;
}

function setSession() {
  state.maxUserId = byId("maxUserId").value.trim();
  state.fullName = byId("fullName").value.trim();
  persistSession();
}

function applyBranding() {
  const settings = state.appSettings;
  if (!settings) return;

  document.title = settings.brand_name || "MAX Support";
  byId("brandTitle").textContent = settings.brand_name || "MAX Support";
  byId("brandSubtitle").textContent = "";
  byId("createHintText").textContent = settings.brand_subtitle || "";
  byId("createHintCard").hidden = !Boolean(settings.brand_subtitle);

  const markNode = byId("brandMark");
  if (settings.brand_icon_url) {
    markNode.innerHTML = `<img src="${settings.brand_icon_url}" alt="Иконка" style="width:100%;height:100%;object-fit:cover;border-radius:16px;">`;
  } else {
    markNode.textContent = settings.brand_mark || "MS";
  }

  byId("brandNameInput").value = settings.brand_name || "";
  byId("brandSubtitleInput").value = settings.brand_subtitle || "";
  byId("brandMarkInput").value = settings.brand_mark || "";
  byId("brandIconUrlInput").value = settings.brand_icon_url || "";
}

function applyThemeSettings() {
  const theme = state.appThemeSettings;
  if (!theme) return;

  document.documentElement.style.setProperty("--bg", theme.background_color || "#f4efe7");
  document.documentElement.style.setProperty("--card", theme.card_color || "#fffaf2");
  document.documentElement.style.setProperty("--accent", theme.accent_color || "#0e7a6d");
  document.documentElement.style.setProperty("--button", theme.button_color || "#169c8b");

  byId("backgroundColorInput").value = theme.background_color || "";
  byId("cardColorInput").value = theme.card_color || "";
  byId("accentColorInput").value = theme.accent_color || "";
  byId("buttonColorInput").value = theme.button_color || "";
}

function applyUiSettings() {
  const settings = state.appUiSettings;
  if (!settings) return;

  document.documentElement.style.setProperty("--sidebar-bg", settings.sidebar_background || "rgba(255, 250, 242, 0.92)");
  document.documentElement.style.setProperty("--nav-item", settings.nav_item_color || "#ece1d1");
  document.documentElement.style.setProperty("--nav-active-text", settings.nav_item_active_text_color || "#ffffff");
  document.documentElement.style.setProperty("--button-text", settings.button_text_color || "#ffffff");
  document.documentElement.style.setProperty("--input-bg", settings.input_background || "#fffdf9");
  document.documentElement.style.setProperty("--input-border", settings.input_border_color || "#d6c8b7");
  document.documentElement.style.setProperty("--heading", settings.heading_color || "#1f2a2e");
  document.documentElement.style.setProperty("--muted", settings.muted_text_color || "#5e6c70");
  document.documentElement.style.setProperty("--card-radius", settings.card_radius || "20px");
  document.documentElement.style.setProperty("--button-radius", settings.button_radius || "14px");
  document.documentElement.style.setProperty("--shadow", settings.card_shadow || "0 18px 40px rgba(34, 32, 24, 0.08)");

  byId("sidebarBackgroundInput").value = settings.sidebar_background || "";
  byId("navItemColorInput").value = settings.nav_item_color || "";
  byId("navItemActiveTextColorInput").value = settings.nav_item_active_text_color || "";
  byId("buttonTextColorInput").value = settings.button_text_color || "";
  byId("inputBackgroundInput").value = settings.input_background || "";
  byId("inputBorderColorInput").value = settings.input_border_color || "";
  byId("headingColorInput").value = settings.heading_color || "";
  byId("mutedTextColorInput").value = settings.muted_text_color || "";
  byId("cardRadiusInput").value = settings.card_radius || "";
  byId("buttonRadiusInput").value = settings.button_radius || "";
  byId("cardShadowInput").value = settings.card_shadow || "";
}

function applyIntegrationSettings() {
  const settings = state.integrationSettings;
  if (!settings) return;
  byId("pluginLabelInput").value = settings.plugin_label || "API Endpoints";
  byId("extendedApiEnabledInput").checked = Boolean(settings.extended_api_enabled);
}

function updateAdminVisibility() {
  const adminNavBtn = document.querySelector('.nav-btn[data-tab="admin"]');
  const adminPanel = byId("tab-admin");
  const shouldShowAdmin = Boolean(state.isAdmin);
  adminNavBtn.hidden = !shouldShowAdmin;
  adminPanel.hidden = !shouldShowAdmin;

  if (!shouldShowAdmin && adminNavBtn.classList.contains("active")) {
    activateTab(state.user && state.user.work_email ? "create" : "bind");
  }
}

function updateBindVisibility() {
  const bindNavBtn = document.querySelector('.nav-btn[data-tab="bind"]');
  const bindPanel = byId("tab-bind");
  const bindSummary = byId("bindSummary");
  const hasVerifiedEmail = Boolean(state.user && state.user.work_email);

  bindNavBtn.hidden = hasVerifiedEmail;
  bindPanel.hidden = hasVerifiedEmail;

  if (hasVerifiedEmail) {
    byId("emailInput").value = state.user.work_email || "";
    bindSummary.hidden = false;
    bindSummary.textContent = `Рабочая почта уже подтверждена: ${state.user.work_email}`;
    if (bindNavBtn.classList.contains("active")) {
      activateTab("create");
    }
  } else {
    bindSummary.hidden = true;
    bindSummary.textContent = "";
  }
}

function updateSessionVisibility() {
  byId("sessionCard").hidden = Boolean(state.user && state.user.work_email);
}

function applyKnownUser(user) {
  if (!user) return;
  state.user = user;
  state.maxUserId = String(user.max_user_id || state.maxUserId);
  state.fullName = String(user.full_name || state.fullName);
  state.isAdmin = Boolean(user.is_admin);
  persistSession();
  hydrateSession();
  updateAdminVisibility();
  updateBindVisibility();
  updateSessionVisibility();
}

async function validateStoredSession() {
  if (!state.accessToken) {
    state.isAdmin = false;
    updateAdminVisibility();
    updateBindVisibility();
    updateSessionVisibility();
    return;
  }
  try {
    const me = await api.getMe();
    applyKnownUser(me);
  } catch (error) {
    console.warn("Stored session is invalid", error);
    state.isAdmin = false;
    state.user = null;
  } finally {
    updateAdminVisibility();
    updateBindVisibility();
    updateSessionVisibility();
  }
}

async function hydrateKnownUser() {
  if (!state.maxUserId) return;
  try {
    const user = await api.getUserByMaxId(state.maxUserId);
    applyKnownUser(user);
  } catch (error) {
    console.warn("Known user not found", error);
    updateBindVisibility();
    updateSessionVisibility();
  }
}

async function hydrateFromMaxWebApp() {
  const webApp = window.WebApp;
  if (!webApp) {
    setLaunchStatus("MAX WebApp не обнаружен. Можно продолжить вручную.");
    return;
  }

  try {
    if (typeof webApp.ready === "function") {
      webApp.ready();
    }
  } catch (error) {
    console.warn("WebApp.ready failed", error);
  }

  const rawInitData = webApp.initData || webApp.InitData || "";
  if (rawInitData) {
    try {
      const session = await api.createWebAppSession(rawInitData);
      state.maxUserId = String(session.max_user_id || "");
      state.fullName = String(session.full_name || "");
      state.accessToken = String(session.access_token || "");
      persistSession();
      hydrateSession();
      setLaunchStatus("Сессия подтверждена через MAX WebApp.");
      return;
    } catch (error) {
      console.warn("MAX WebApp validation failed", error);
    }
  }

  const initData = webApp.initDataUnsafe || webApp.InitDataUnsafe || {};
  const user = initData.user || initData.sender || {};
  const maxUserId = user.user_id || user.id || "";
  const fullName = user.full_name || user.name || "";

  if (maxUserId) {
    state.maxUserId = String(maxUserId);
  }
  if (fullName) {
    state.fullName = String(fullName);
  }
  if (maxUserId || fullName) {
    persistSession();
    hydrateSession();
    setLaunchStatus("Данные пользователя получены из MAX WebApp.");
    return;
  }

  setLaunchStatus("MAX WebApp доступен, но данные пользователя не переданы. Можно заполнить вручную.");
}

function activateTab(tab) {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${tab}`);
  });
}

function activateAdminTab(tab) {
  document.querySelectorAll(".subnav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.adminTab === tab);
  });
  document.querySelectorAll(".admin-subpanel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `admin-panel-${tab}`);
  });
}

async function loadCatalog() {
  state.catalog = await api.getCatalog();

  byId("hotelSelect").innerHTML = state.catalog.hotels
    .filter((item) => item.is_active)
    .map((item) => `<option value="${item.id}">${item.name}</option>`)
    .join("");

  byId("categorySelect").innerHTML = state.catalog.categories
    .filter((item) => item.is_active)
    .map((item) => `<option value="${item.id}">${item.name}</option>`)
    .join("");

  fillTopics();
}

function fillTopics() {
  const categoryId = Number(byId("categorySelect").value);
  const topicSelect = byId("topicSelect");
  const category = state.catalog?.categories.find((item) => item.id === categoryId);
  topicSelect.innerHTML = (category?.topics || [])
    .filter((item) => item.is_active)
    .map((item) => `<option value="${item.id}">${item.name}</option>`)
    .join("");
}

async function requestCode() {
  setSession();
  const email = byId("emailInput").value.trim();
  const result = byId("bindResult");
  if (!state.maxUserId || !email) {
    result.textContent = "Сначала укажите MAX User ID и рабочую почту.";
    return;
  }
  try {
    const data = await api.requestEmailCode({
      max_user_id: state.maxUserId,
      full_name: state.fullName,
      email,
    });
    result.textContent = data.message;
  } catch (error) {
    result.textContent = error.message;
  }
}

async function bindEmail() {
  setSession();
  const email = byId("emailInput").value.trim();
  const code = byId("emailCodeInput").value.trim();
  const result = byId("bindResult");
  if (!state.maxUserId || !email || !code) {
    result.textContent = "Укажите MAX User ID, рабочую почту и код из письма.";
    return;
  }
  try {
    const data = await api.verifyEmailCode({
      max_user_id: state.maxUserId,
      full_name: state.fullName,
      email,
      code,
    });
    applyKnownUser(data);
    result.textContent = `Почта подтверждена: ${data.work_email}`;
    activateTab("create");
  } catch (error) {
    result.textContent = error.message;
  }
}

function resetCreateFormVisibility() {
  byId("createFormCard").hidden = false;
  byId("createHintCard").hidden = !Boolean(state.appSettings && state.appSettings.brand_subtitle);
  byId("createSuccessCard").hidden = true;
  byId("createSuccessText").textContent = "";
  byId("createResult").textContent = "";
}

async function createTicket() {
  setSession();
  const result = byId("createResult");
  if (!state.maxUserId) {
    result.textContent = "Сначала сохраните MAX User ID.";
    return;
  }

  try {
    const data = await api.createTicket({
      max_user_id: state.maxUserId,
      hotel_id: Number(byId("hotelSelect").value),
      category_id: Number(byId("categorySelect").value),
      topic_id: Number(byId("topicSelect").value),
      description: byId("descriptionInput").value.trim(),
    });
    byId("createSuccessText").textContent = `ID заявки: ${data.external_id}\nСтатус: ${data.current_status}`;
    byId("createFormCard").hidden = true;
    byId("createHintCard").hidden = true;
    byId("createSuccessCard").hidden = false;
    byId("descriptionInput").value = "";
  } catch (error) {
    result.textContent = error.message;
  }
}

function renderTickets(tickets) {
  const root = byId("ticketsList");
  root.innerHTML = tickets.map((ticket) => `
    <div class="list-item ticket-item">
      <div class="list-head">
        <span>#${ticket.external_id}</span>
        <span>${ticket.current_status}</span>
      </div>
      <div>${ticket.subject}</div>
      <div class="list-meta">${ticket.description}</div>
      ${ticket.is_shared ? `<div class="list-meta">Владелец: ${ticket.owner_full_name || ticket.owner_work_email}</div>` : ""}
    </div>
  `).join("") || `<div class="list-item">Заявок пока нет.</div>`;
}

async function refreshTickets() {
  setSession();
  const root = byId("ticketsList");
  if (!state.maxUserId) {
    root.innerHTML = `<div class="list-item">Сначала сохраните MAX User ID.</div>`;
    return;
  }
  try {
    const tickets = await api.getTickets(state.maxUserId);
    renderTickets(tickets);
  } catch (error) {
    root.innerHTML = `<div class="list-item">${error.message}</div>`;
  }
}

function renderAdminList(items, rootId, type) {
  const root = byId(rootId);
  root.innerHTML = items.map((item) => {
    const title = type === "categories"
      ? `${item.name} (topicId: ${item.osticket_topic_id})`
      : type === "topics"
        ? `${item.name} (category: ${item.category_id})`
        : item.name;
    return `
      <div class="list-item">
        <div class="list-head">
          <span>${title}</span>
          <span>${item.is_active ? "active" : "inactive"}</span>
        </div>
        <div class="admin-actions">
          <button onclick="editItem('${type}', ${item.id})">Редактировать</button>
        </div>
      </div>
    `;
  }).join("") || `<div class="list-item">Пусто</div>`;
}

function renderUsers(items) {
  const root = byId("usersAdminList");
  root.innerHTML = items.map((item) => `
    <div class="list-item">
      <div class="list-head">
        <span>${item.full_name || item.work_email || item.max_user_id}</span>
        <span>${item.is_admin ? "admin" : "user"}</span>
      </div>
      <div class="list-meta">${item.work_email || "Почта не привязана"}</div>
      <div class="list-meta">MAX: ${item.max_user_id} | ${item.is_active ? "active" : "inactive"}</div>
      <div class="admin-actions wrap">
        <button onclick="editUser(${item.id})">Профиль</button>
        <button onclick="toggleAdmin(${item.id})">${item.is_admin ? "Снять админку" : "Сделать админом"}</button>
        <button onclick="manageAccess(${item.id})">Права на заявки</button>
      </div>
    </div>
  `).join("") || `<div class="list-item">Пусто</div>`;
}

function renderAuditLogs(items) {
  const root = byId("auditAdminList");
  root.innerHTML = items.map((item) => `
    <div class="list-item">
      <div class="list-head">
        <span>${item.action} ${item.entity_type}#${item.entity_id}</span>
        <span>${new Date(item.created_at).toLocaleString("ru-RU")}</span>
      </div>
      <div class="list-meta">actor_user_id: ${item.actor_user_id}</div>
      <div class="list-meta">${item.details_json}</div>
    </div>
  `).join("") || `<div class="list-item">Пусто</div>`;
}

async function loadAdmin() {
  if (!state.isAdmin) {
    activateTab(state.user && state.user.work_email ? "create" : "bind");
    return;
  }
  try {
    const [users, hotels, categories, topics, auditLogs, integrationSettings] = await Promise.all([
      api.adminListUsers(),
      api.adminListHotels(),
      api.adminListCategories(),
      api.adminListTopics(),
      api.adminListAuditLogs(),
      api.getIntegrationSettings(),
    ]);
    state.integrationSettings = integrationSettings;
    applyIntegrationSettings();
    renderUsers(users);
    renderAdminList(hotels, "hotelsAdminList", "hotels");
    renderAdminList(categories, "categoriesAdminList", "categories");
    renderAdminList(topics, "topicsAdminList", "topics");
    renderAuditLogs(auditLogs);
  } catch (error) {
    const message = `<div class="list-item">${error.message}</div>`;
    byId("usersAdminList").innerHTML = message;
    byId("hotelsAdminList").innerHTML = message;
    byId("categoriesAdminList").innerHTML = message;
    byId("topicsAdminList").innerHTML = message;
    byId("auditAdminList").innerHTML = message;
  }
}

async function saveBrandingSettings() {
  const result = byId("brandingResult");
  try {
    state.appSettings = await api.adminUpdateAppSettings({
      brand_name: byId("brandNameInput").value.trim(),
      brand_subtitle: byId("brandSubtitleInput").value.trim(),
      brand_mark: byId("brandMarkInput").value.trim(),
      brand_icon_url: byId("brandIconUrlInput").value.trim(),
    });
    applyBranding();
    resetCreateFormVisibility();
    result.textContent = "Настройки брендинга сохранены.";
  } catch (error) {
    result.textContent = error.message;
  }
}

async function saveThemeSettings() {
  const result = byId("themeResult");
  try {
    state.appThemeSettings = await api.adminUpdateAppThemeSettings({
      background_color: byId("backgroundColorInput").value.trim(),
      card_color: byId("cardColorInput").value.trim(),
      accent_color: byId("accentColorInput").value.trim(),
      button_color: byId("buttonColorInput").value.trim(),
    });
    applyThemeSettings();
    result.textContent = "Цвета интерфейса сохранены.";
  } catch (error) {
    result.textContent = error.message;
  }
}

async function saveAppearanceSettings() {
  const result = byId("appearanceResult");
  try {
    state.appUiSettings = await api.adminUpdateAppUiSettings({
      sidebar_background: byId("sidebarBackgroundInput").value.trim(),
      nav_item_color: byId("navItemColorInput").value.trim(),
      nav_item_active_text_color: byId("navItemActiveTextColorInput").value.trim(),
      button_text_color: byId("buttonTextColorInput").value.trim(),
      input_background: byId("inputBackgroundInput").value.trim(),
      input_border_color: byId("inputBorderColorInput").value.trim(),
      heading_color: byId("headingColorInput").value.trim(),
      muted_text_color: byId("mutedTextColorInput").value.trim(),
      card_radius: byId("cardRadiusInput").value.trim(),
      button_radius: byId("buttonRadiusInput").value.trim(),
      card_shadow: byId("cardShadowInput").value.trim(),
    });
    applyUiSettings();
    result.textContent = "Детальные настройки интерфейса сохранены.";
  } catch (error) {
    result.textContent = error.message;
  }
}

async function saveIntegrationSettings() {
  const result = byId("integrationResult");
  try {
    state.integrationSettings = await api.adminUpdateIntegrationSettings({
      extended_api_enabled: byId("extendedApiEnabledInput").checked,
      plugin_label: byId("pluginLabelInput").value.trim() || "API Endpoints",
    });
    applyIntegrationSettings();
    result.textContent = "Настройки интеграции сохранены.";
  } catch (error) {
    result.textContent = error.message;
  }
}

window.editUser = async function editUser(id) {
  try {
    const users = await api.adminListUsers();
    const user = users.find((item) => item.id === id);
    if (!user) return;
    const fullName = prompt("Имя пользователя", user.full_name || "");
    if (fullName === null) return;
    const activeAnswer = prompt("Активный пользователь? Введите yes или no", user.is_active ? "yes" : "no");
    if (activeAnswer === null) return;
    await api.adminUpdateUser(id, {
      full_name: fullName,
      is_admin: user.is_admin,
      is_active: activeAnswer.trim().toLowerCase() !== "no",
    });
    await loadAdmin();
  } catch (error) {
    alert(error.message);
  }
};

window.toggleAdmin = async function toggleAdmin(id) {
  try {
    const users = await api.adminListUsers();
    const user = users.find((item) => item.id === id);
    if (!user) return;
    await api.adminUpdateUser(id, {
      full_name: user.full_name || "",
      is_admin: !user.is_admin,
      is_active: user.is_active,
    });
    await loadAdmin();
  } catch (error) {
    alert(error.message);
  }
};

window.manageAccess = async function manageAccess(id) {
  try {
    const [users, accessItems] = await Promise.all([
      api.adminListUsers(),
      api.adminGetUserTicketAccess(id),
    ]);
    const user = users.find((item) => item.id === id);
    if (!user) return;
    const helpText = accessItems
      .map((item) => `${item.user_id}: ${item.full_name || item.work_email || item.max_user_id}${item.can_view ? " [доступ]" : ""}`)
      .join("\n");
    const current = accessItems.filter((item) => item.can_view).map((item) => String(item.user_id)).join(",");
    const raw = prompt(
      `Укажите через запятую ID пользователей, чьи заявки может видеть ${user.full_name || user.work_email}.\n\n${helpText}`,
      current,
    );
    if (raw === null) return;
    const ownerUserIds = raw
      .split(",")
      .map((item) => Number(item.trim()))
      .filter((item) => Number.isFinite(item) && item > 0);
    await api.adminUpdateUserTicketAccess(id, { owner_user_ids: ownerUserIds });
    alert("Права на просмотр заявок обновлены.");
    await loadAdmin();
  } catch (error) {
    alert(error.message);
  }
};

window.editItem = async function editItem(type, id) {
  try {
    if (type === "hotels") {
      const hotels = await api.adminListHotels();
      const hotel = hotels.find((item) => item.id === id);
      if (!hotel) return;
      const name = prompt("Новое имя отеля", hotel.name);
      if (!name) return;
      await api.adminUpdateHotel(id, { name, is_active: hotel.is_active });
    }
    if (type === "categories") {
      const categories = await api.adminListCategories();
      const category = categories.find((item) => item.id === id);
      if (!category) return;
      const name = prompt("Новое имя категории", category.name);
      if (!name) return;
      const topicId = prompt("Новый osTicket topicId", String(category.osticket_topic_id));
      if (!topicId) return;
      await api.adminUpdateCategory(id, {
        name,
        osticket_topic_id: Number(topicId),
        is_active: category.is_active,
      });
    }
    if (type === "topics") {
      const topics = await api.adminListTopics();
      const topic = topics.find((item) => item.id === id);
      if (!topic) return;
      const name = prompt("Новое имя темы", topic.name);
      if (!name) return;
      const categoryId = prompt("ID категории", String(topic.category_id));
      if (!categoryId) return;
      await api.adminUpdateTopic(id, {
        name,
        category_id: Number(categoryId),
        is_active: topic.is_active,
      });
    }
    await loadAdmin();
    await loadCatalog();
  } catch (error) {
    alert(error.message);
  }
};

async function addHotel() {
  const name = prompt("Название отеля");
  if (!name) return;
  await api.adminCreateHotel(name);
  await loadAdmin();
  await loadCatalog();
}

async function addCategory() {
  const name = prompt("Название категории");
  if (!name) return;
  const topicId = prompt("osTicket topicId");
  if (!topicId) return;
  await api.adminCreateCategory({ name, osticket_topic_id: Number(topicId) });
  await loadAdmin();
  await loadCatalog();
}

async function addTopic() {
  const name = prompt("Название темы");
  if (!name) return;
  const categoryId = prompt("ID категории");
  if (!categoryId) return;
  await api.adminCreateTopic({ name, category_id: Number(categoryId) });
  await loadAdmin();
  await loadCatalog();
}

async function init() {
  state.appSettings = await api.getAppSettings();
  state.appThemeSettings = await api.getAppThemeSettings();
  state.appUiSettings = await api.getAppUiSettings();
  state.integrationSettings = await api.getIntegrationSettings();
  applyBranding();
  applyThemeSettings();
  applyUiSettings();
  applyIntegrationSettings();

  hydrateSession();
  await validateStoredSession();
  await hydrateFromMaxWebApp();
  await validateStoredSession();
  await hydrateKnownUser();
  updateAdminVisibility();
  updateBindVisibility();
  updateSessionVisibility();

  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (btn.dataset.tab === "admin" && !state.isAdmin) {
        activateTab(state.user && state.user.work_email ? "create" : "bind");
        return;
      }
      activateTab(btn.dataset.tab);
      if (btn.dataset.tab === "tickets") await refreshTickets();
      if (btn.dataset.tab === "admin") await loadAdmin();
    });
  });

  document.querySelectorAll(".subnav-btn").forEach((btn) => {
    btn.addEventListener("click", () => activateAdminTab(btn.dataset.adminTab));
  });

  byId("saveSessionBtn").addEventListener("click", async () => {
    setSession();
    await hydrateKnownUser();
  });
  byId("requestCodeBtn").addEventListener("click", requestCode);
  byId("bindEmailBtn").addEventListener("click", bindEmail);
  byId("createTicketBtn").addEventListener("click", createTicket);
  byId("refreshTicketsBtn").addEventListener("click", refreshTickets);
  byId("categorySelect").addEventListener("change", fillTopics);
  byId("addHotelBtn").addEventListener("click", addHotel);
  byId("addCategoryBtn").addEventListener("click", addCategory);
  byId("addTopicBtn").addEventListener("click", addTopic);
  byId("refreshUsersBtn").addEventListener("click", loadAdmin);
  byId("refreshAuditBtn").addEventListener("click", loadAdmin);
  byId("saveBrandingBtn").addEventListener("click", saveBrandingSettings);
  byId("saveThemeBtn").addEventListener("click", saveThemeSettings);
  byId("saveAppearanceBtn").addEventListener("click", saveAppearanceSettings);
  byId("saveIntegrationBtn").addEventListener("click", saveIntegrationSettings);
  byId("createAnotherBtn").addEventListener("click", () => {
    resetCreateFormVisibility();
    activateTab("create");
  });

  await loadCatalog();
  resetCreateFormVisibility();
  if (state.user && state.user.work_email) {
    activateTab("create");
  }
}

init().catch((error) => {
  console.error(error);
  alert(error.message);
});
