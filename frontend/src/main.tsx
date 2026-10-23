import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/manrope/600.css";
import "./styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { I18nProvider } from "./i18n";
import { nativeApp } from "./lib/native";
import { POCKET } from "./lib/pocket";
import { registerServiceWorker } from "./lib/updates";

// iPhone and iPad: keep the phone app on the device so it opens without internet.
if (POCKET && !nativeApp() && "serviceWorker" in navigator && window.isSecureContext) {
  registerServiceWorker();
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider>
      <App />
    </I18nProvider>
  </StrictMode>,
);
