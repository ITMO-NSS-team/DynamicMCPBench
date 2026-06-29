import React from "react";
import { createRoot } from "react-dom/client";
import { GeistProvider, CssBaseline } from "@geist-ui/core";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import { dmcpDark } from "./theme";
import { App } from "./App";
import { StudioProvider } from "./store/StudioProvider";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <GeistProvider themes={[dmcpDark]} themeType="dmcp-dark">
      <CssBaseline />
      <StudioProvider>
        <App />
      </StudioProvider>
    </GeistProvider>
  </React.StrictMode>,
);
