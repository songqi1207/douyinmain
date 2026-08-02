import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth";
import { PreferencesProvider } from "./preferences";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename="/business">
      <PreferencesProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </PreferencesProvider>
    </BrowserRouter>
  </React.StrictMode>
);
