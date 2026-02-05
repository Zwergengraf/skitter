import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

const storedTheme = localStorage.getItem("theme");
const isDark = storedTheme ? storedTheme === "dark" : true;
document.documentElement.classList.toggle("dark", isDark);
if (!storedTheme) {
  localStorage.setItem("theme", "dark");
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
