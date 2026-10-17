import next from "eslint-config-next";
import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const config = [
  { ignores: [".next/**", "out/**", "test-results/**", "playwright-report/**", "next-env.d.ts"] },
  ...next,
  ...coreWebVitals,
  ...typescript,
];

export default config;
