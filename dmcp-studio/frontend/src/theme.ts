import { Themes } from "@geist-ui/core";

const SANS = '"Geist Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
const MONO = '"Geist Mono Variable", "SF Mono", Menlo, monospace';

// A tight, near-monochrome dark Geist theme. Colour is rationed: greyscale ink
// everywhere, a single restrained green/red reserved for verdicts + checkpoints.
export const dmcpDark = Themes.createFromDark({
  type: "dmcp-dark",
  font: { sans: SANS, mono: MONO },
  layout: {
    // tighter corners than stock Geist
    radius: "4px",
    unit: "16px",
  },
  palette: {
    background: "#000000",
    foreground: "#ededed",
    accents_1: "#0a0a0a",
    accents_2: "#161616",
    accents_3: "#1f1f1f",
    accents_4: "#2e2e2e",
    accents_5: "#6f6f6f",
    accents_6: "#8f8f8f",
    accents_7: "#a1a1a1",
    accents_8: "#ededed",
    border: "#1f1f1f",
    success: "#3ad07f",
    successLighter: "#0d2419",
    successLight: "#2bb46c",
    successDark: "#3ad07f",
    error: "#f56565",
    errorLighter: "#2a1110",
    errorLight: "#e5484d",
    errorDark: "#f56565",
    warning: "#a1a1a1",
    warningLight: "#a1a1a1",
    warningDark: "#cfcfcf",
    link: "#ededed",
    selection: "#1f1f1f",
    code: "#ededed",
  },
});
