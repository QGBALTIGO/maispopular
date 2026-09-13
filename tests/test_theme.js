"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("webapp_static/theme.js", "utf8");
function start({saved, dark = false, blocked = false, telegram} = {}) {
  const listeners = {}, events = {}, attrs = {}, root = {dataset: {}}, meta = {};
  const button = {setAttribute: (key, value) => attrs[key] = value,
    addEventListener: (key, fn) => events[key] = fn};
  const storage = {getItem: () => {if (blocked) throw Error(); return saved;},
    setItem: (_, value) => {if (blocked) throw Error(); saved = value;}};
  const system = {matches: dark, addEventListener: (_, fn) => listeners.system = fn};
  vm.runInNewContext(source, {
    window: {matchMedia: () => system, Telegram: telegram ? {WebApp: telegram} : undefined},
    document: {documentElement: root, querySelector: () => meta,
      getElementById: () => button, addEventListener: (key, fn) => listeners[key] = fn},
    localStorage: storage,
  });
  listeners.DOMContentLoaded();
  return {root, attrs, events, listeners, system, saved: () => saved};
}
let env = start({dark: true});
assert.equal(env.root.dataset.theme, "dark");
assert.equal(env.attrs["aria-pressed"], "true");
env.events.click();
assert.equal(env.root.dataset.theme, "light");
assert.equal(env.saved(), "light");
env.listeners.system();
assert.equal(env.root.dataset.theme, "light");
assert.equal(start({saved: "dark"}).root.dataset.theme, "dark");
assert.equal(start({saved: "invalid"}).root.dataset.theme, "dark");
env = start({blocked: true});
env.events.click();
assert.equal(env.root.dataset.theme, "light");
env = start();
env.system.matches = true;
env.listeners.system();
assert.equal(env.root.dataset.theme, "dark");
const colors = [];
env = start({telegram: {initData: "fixture", colorScheme: "dark", isVersionAtLeast: () => true,
  setHeaderColor: color => colors.push(color), setBackgroundColor: () => {}, setBottomBarColor: () => {}}});
assert.equal(env.root.dataset.theme, "dark");
assert.equal(colors.at(-1), "#08090d");
env.events.click();
assert.equal(colors.at(-1), "#f7f8fa");
console.log("Theme: defaults, persistence, blocked storage, explicit preference and Telegram chrome passed");
