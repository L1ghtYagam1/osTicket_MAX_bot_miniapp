"use strict";

const { app, BrowserWindow, shell, Menu, dialog } = require("electron");
const fs = require("fs");
const path = require("path");

// Конфиг читаем из файла рядом с приложением, чтобы можно было сменить адрес
// сервера без пересборки. Значения по умолчанию — production-домен.
const DEFAULT_CONFIG = {
  appUrl: "https://supbot.ukprovence.ru/app",
  windowWidth: 1280,
  windowHeight: 860,
  minWidth: 900,
  minHeight: 600,
};

function loadConfig() {
  const candidates = [
    path.join(process.resourcesPath || "", "config.json"),
    path.join(__dirname, "config.json"),
  ];
  for (const file of candidates) {
    try {
      if (file && fs.existsSync(file)) {
        const raw = JSON.parse(fs.readFileSync(file, "utf-8"));
        return { ...DEFAULT_CONFIG, ...raw };
      }
    } catch (err) {
      console.error("Не удалось прочитать config.json:", err);
    }
  }
  return DEFAULT_CONFIG;
}

const config = loadConfig();
let mainWindow = null;

function isInternalUrl(targetUrl) {
  try {
    const appOrigin = new URL(config.appUrl).origin;
    return new URL(targetUrl).origin === appOrigin;
  } catch {
    return false;
  }
}

function openExternal(targetUrl) {
  if (/^https?:\/\//i.test(targetUrl)) {
    shell.openExternal(targetUrl);
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: config.windowWidth,
    height: config.windowHeight,
    minWidth: config.minWidth,
    minHeight: config.minHeight,
    title: "Provence Support",
    autoHideMenuBar: true,
    backgroundColor: "#f4efe7",
    icon: path.join(__dirname, "assets", "icon.ico"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      // Постоянный partition — чтобы localStorage (токен сессии) и cookie
      // сохранялись между запусками и пользователь логинился один раз.
      partition: "persist:provence",
    },
  });

  mainWindow.loadURL(config.appUrl);

  // Внешние ссылки (target=_blank и переходы на чужой домен) открываем в браузере,
  // а не внутри окна приложения.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    openExternal(url);
    return { action: "deny" };
  });

  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!isInternalUrl(url)) {
      event.preventDefault();
      openExternal(url);
    }
  });

  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
    if (errorCode === -3) return; // прерванная загрузка, не ошибка
    dialog.showErrorBox(
      "Нет соединения с сервером",
      `Не удалось загрузить ${validatedURL}\n\n${errorDescription}\n\n` +
        "Проверьте интернет и доступность сервера, затем нажмите «Обновить» (Ctrl+R)."
    );
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function buildMenu() {
  const template = [
    {
      label: "Файл",
      submenu: [
        {
          label: "Обновить",
          accelerator: "CmdOrCtrl+R",
          click: () => mainWindow && mainWindow.webContents.reload(),
        },
        { type: "separator" },
        { role: "quit", label: "Выход" },
      ],
    },
    {
      label: "Правка",
      submenu: [
        { role: "cut", label: "Вырезать" },
        { role: "copy", label: "Копировать" },
        { role: "paste", label: "Вставить" },
        { role: "selectAll", label: "Выделить всё" },
      ],
    },
    {
      label: "Вид",
      submenu: [
        { role: "resetZoom", label: "Сбросить масштаб" },
        { role: "zoomIn", label: "Увеличить" },
        { role: "zoomOut", label: "Уменьшить" },
        { type: "separator" },
        { role: "togglefullscreen", label: "Полный экран" },
        { role: "toggleDevTools", label: "Инструменты разработчика" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// Один экземпляр приложения.
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    buildMenu();
    createWindow();

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
