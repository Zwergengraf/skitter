import React from "react";
import ReactDOM from "react-dom/client";
import { initializeTheme } from "./lib/theme";
import App from "./App";
import "./index.css";

initializeTheme();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
