const state = {
  maxUserId: localStorage.getItem("max_user_id") || "",
  fullName: localStorage.getItem("full_name") || "",
  accessToken: localStorage.getItem("access_token") || "",
  isAdmin: false,
  user: null,
  appSettings: null,
  catalog: null,
  webAppReady: false,
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
};

function byId(id) {
  return document.getElementById(id);
}

function setLaunchStatus(message) {
  byId("maxLaunchStatus").textContent = message;
}

function applyBranding() {
  const settings = state.appSettings;
  if (!settings) return;

  document.title = settings.brand_name || "MAX Support";
  byId("brandTitle").textContent = settings.brand_name || "MAX Support";
  byId("brandSubtitle").textContent = settings.brand_subtitle || "";

  const markNode = byId("brandMark");
  if (settings.brand_icon_url) {
    markNode.innerHTML = `<img src="${settings.brand_icon_url}" alt="brand icon" style="width:100%;height:100%;object-fit:cover;border-radius:16px;">`;
  } else {
    markNode.textContent = settings.brand_mark || "MS";
  }

  if (byId("brandNameInput")) byId("brandNameInput").value = settings.brand_name || "";
  if (byId("brandSubtitleInput")) byId("brandSubtitleInput").value = settings.brand_subtitle || "";
  if (byId("brandMarkInput")) byId("brandMarkInput").value = settings.brand_mark || "";
  if (byId("brandIconUrlInput")) byId("brandIconUrlInput").value = settings.brand_icon_url || "";
}

function updateAdminVisibility() {
  const adminNavBtn = document.querySelector('.nav-btn[data-tab="admin"]');
  const adminPanel = byId("tab-admin");
  if (!adminNavBtn || !adminPanel) return;

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
  if (!bindNavBtn || !bindPanel || !bindSummary) return;

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

function persistSession() {
  localStorage.setItem("max_user_id", state.maxUserId);
  localStorage.setItem("full_name", state.fullName);
  if (state.accessToken) {
    localStorage.setItem("access_token", state.accessToken);
  } else {
    localStorage.removeItem("access_token");
  }
}

function setSession() {
  state.maxUserId = byId("maxUserId").value.trim();
  state.fullName = byId("fullName").value.trim();
  persistSession();
}

function hydrateSession() {
  byId("maxUserId").value = state.maxUserId;
  byId("fullName").value = state.fullName;
}

async function validateStoredSession() {
  if (!state.accessToken) {
    state.isAdmin = false;
    updateAdminVisibility();
    return;
  }
  try {
    const me = await api.getMe();
    state.user = me;
    state.maxUserId = String(me.max_user_id || state.maxUserId);
    state.fullName = String(me.full_name || state.fullName);
    state.isAdmin = Boolean(me.is_admin);
    persistSession();
  } catch (error) {
    console.warn("Stored session is invalid", error);
    state.accessToken = "";
    state.isAdmin = false;
    state.user = null;
    persistSession();
  } finally {
    updateAdminVisibility();
    updateBindVisibility();
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
      byId("maxUserId").value = state.maxUserId;
      byId("fullName").value = state.fullName;
      persistSession();
      state.webAppReady = true;
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
    byId("maxUserId").value = state.maxUserId;
  }
  if (fullName) {
    state.fullName = String(fullName);
    byId("fullName").value = state.fullName;
  }
  if (maxUserId || fullName) {
    persistSession();
    state.webAppReady = true;
    setLaunchStatus("Данные пользователя получены из MAX WebApp без серверной валидации.");
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

async function loadCatalog() {
  state.catalog = await api.getCatalog();

  const hotelSelect = byId("hotelSelect");
  const categorySelect = byId("categorySelect");
  hotelSelect.innerHTML = state.catalog.hotels
    .filter((item) => item.is_active)
    .map((item) => `<option value="${item.id}">${item.name}</option>`)
    .join("");

  categorySelect.innerHTML = state.catalog.categories
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
  const data = await api.requestEmailCode({
    max_user_id: state.maxUserId,
    full_name: state.fullName,
    email,
  });
  result.textContent = data.message;
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
  const data = await api.verifyEmailCode({
    max_user_id: state.maxUserId,
    full_name: state.fullName,
    email,
    code,
  });
  state.user = data;
  state.isAdmin = Boolean(data.is_admin);
  result.textContent = `Почта подтверждена: ${data.work_email}`;
  updateAdminVisibility();
  updateBindVisibility();
  activateTab("create");
}

async function createTicket() {
  setSession();
  const result = byId("createResult");
  if (!state.maxUserId) {
    result.textContent = "Сначала сохраните MAX User ID.";
    return;
  }
  const payload = {
    max_user_id: state.maxUserId,
    hotel_id: Number(byId("hotelSelect").value),
    category_id: Number(byId("categorySelect").value),
    topic_id: Number(byId("topicSelect").value),
    description: byId("descriptionInput").value.trim(),
  };
  const data = await api.createTicket(payload);
  result.textContent = `Заявка создана. ID: ${data.external_id}. Статус: ${data.current_status}`;
  byId("descriptionInput").value = "";
}

async function refreshTickets() {
  setSession();
  const root = byId("ticketsList");
  if (!state.maxUserId) {
    root.innerHTML = `<div class="list-item">Сначала сохраните MAX User ID.</div>`;
    return;
  }
  const tickets = await api.getTickets(state.maxUserId);
  root.innerHTML = tickets.map((ticket) => `
    <div class="list-item">
      <div class="list-head">
        <span>#${ticket.external_id}</span>
        <span>${ticket.current_status}</span>
      </div>
      <div>${ticket.subject}</div>
      <div class="list-meta">${ticket.description}</div>
    </div>
  `).join("") || `<div class="list-item">Заявок пока нет.</div>`;
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
        <span>${item.full_name || item.work_email}</span>
        <span>${item.is_admin ? "admin" : "user"}</span>
      </div>
      <div class="list-meta">${item.work_email}</div>
      <div class="list-meta">MAX: ${item.max_user_id} | ${item.is_active ? "active" : "inactive"}</div>
      <div class="admin-actions">
        <button onclick="editUser(${item.id})">Редактировать</button>
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
    const [users, hotels, categories, topics, auditLogs] = await Promise.all([
      api.adminListUsers(),
      api.adminListHotels(),
      api.adminListCategories(),
      api.adminListTopics(),
      api.adminListAuditLogs(),
    ]);
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
    const data = await api.adminUpdateAppSettings({
      brand_name: byId("brandNameInput").value.trim(),
      brand_subtitle: byId("brandSubtitleInput").value.trim(),
      brand_mark: byId("brandMarkInput").value.trim(),
      brand_icon_url: byId("brandIconUrlInput").value.trim(),
    });
    state.appSettings = data;
    applyBranding();
    result.textContent = "Настройки брендинга сохранены.";
  } catch (error) {
    result.textContent = error.message;
  }
}

window.editUser = async function editUser(id) {
  try {
    const users = await api.adminListUsers();
    const user = users.find((item) => item.id === id);
    const fullName = prompt("Имя пользователя", user.full_name || "");
    if (fullName === null) return;
    const isAdmin = confirm("Выдать права администратора?");
    const isActive = confirm("Оставить пользователя активным?");
    await api.adminUpdateUser(id, {
      full_name: fullName,
      is_admin: isAdmin,
      is_active: isActive,
    });
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
      const name = prompt("Новое имя отеля", hotel.name);
      if (!name) return;
      await api.adminUpdateHotel(id, { name, is_active: hotel.is_active });
    }
    if (type === "categories") {
      const categories = await api.adminListCategories();
      const category = categories.find((item) => item.id === id);
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
  applyBranding();
  hydrateSession();
  await validateStoredSession();
  await hydrateFromMaxWebApp();
  await validateStoredSession();
  hydrateSession();
  updateAdminVisibility();
  updateBindVisibility();

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

  byId("saveSessionBtn").addEventListener("click", setSession);
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

  await loadCatalog();
  if (state.user && state.user.work_email) {
    activateTab("create");
  }
}

init().catch((error) => {
  console.error(error);
  alert(error.message);
});
