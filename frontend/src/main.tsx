import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/plus-jakarta-sans";
import "./styles.css";
import { App } from "./App";

document.documentElement.setAttribute("data-theme", localStorage.getItem("jalsakhi.theme") || "light");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
