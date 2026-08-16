// Ensure window.fetch is writable and compatible across sandboxed environments
(function() {
  try {
    if (typeof window !== "undefined" && window.fetch) {
      var _fetch = window.fetch.bind(window);
      var current = _fetch;
      try {
        Object.defineProperty(window, "fetch", {
          get: function() { return current; },
          set: function(fn) { if (typeof fn === "function") current = fn; },
          configurable: true,
          enumerable: true
        });
      } catch (_) {}
    }
  } catch (_) {}
})();

import './i18n';
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { router } from "./router";
import "highlight.js/styles/github-dark-dimmed.min.css";
import "./index.css";
import "./liquid-glass.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <RouterProvider router={router} />
      <Toaster position="bottom-right" richColors closeButton duration={4000} visibleToasts={3} />
    </ErrorBoundary>
  </StrictMode>
);
