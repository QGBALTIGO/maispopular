"use strict";
// Runs before the page is painted so a saved dark theme never flashes white.
(() => {
  const key = "maispopular.theme";
  const root = document.documentElement;
  const telegram = window.Telegram?.WebApp;
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  let saved;
  try {
    const value = localStorage.getItem(key);
    if (value === "dark" || value === "light") saved = value;
  } catch {
    // Storage can be disabled in private browsing or embedded WebViews.
  }
  // The storefront opens in its branded dark theme; explicit choices persist.
  const automatic = () => "dark";
  function apply(theme) {
    root.dataset.theme = theme;
    const color = theme === "dark" ? "#08090d" : "#f7f8fa";
    document.querySelector('meta[name="theme-color"]').content = color;
    const button = document.getElementById("themeToggle");
    if (button) {
      button.setAttribute("aria-pressed", String(theme === "dark"));
      button.title = theme === "dark" ? "Usar tema claro" : "Usar tema escuro";
    }
    if (telegram?.initData && telegram.isVersionAtLeast?.("6.1")) {
      try {
        telegram.setHeaderColor(color);
        telegram.setBackgroundColor(color);
        if (telegram.isVersionAtLeast("7.10"))
          telegram.setBottomBarColor(color);
      } catch {
        // Keep the store usable if the host does not support a chrome method.
      }
    }
  }
  apply(saved || automatic());
  document.addEventListener("DOMContentLoaded", () => {
    apply(saved || automatic());
    document.getElementById("themeToggle").addEventListener("click", () => {
      saved = root.dataset.theme === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(key, saved);
      } catch {
        /* Session-only choice. */
      }
      apply(saved);
    });
  });
  const followSystem = () => {
    if (!saved) apply(automatic());
  };
  system.addEventListener?.("change", followSystem);
  telegram?.onEvent?.("themeChanged", followSystem);
})();
