import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/plus-jakarta-sans";
import "./styles.css";
import { App } from "./App";
import { initPresentation } from "./lib/present";

document.documentElement.setAttribute("data-theme", localStorage.getItem("jalsakhi.theme") || "light");
initPresentation();

// Installable app that opens offline (public/sw.js). Not in development: Vite serves modules the worker would cache.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
// The browser offers installation once; keep the offer so the citizen app can show its own Install button.
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); (window as any).__installPrompt = e; window.dispatchEvent(new Event("jalsakhi:installable")); });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
