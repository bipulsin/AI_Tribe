/** Client-side UI strings from static catalog (see backend/app/i18n/). */
function atrFormatCurrency(amount) {
  if (amount === null || amount === undefined || amount === "") return "—";
  const n = Number(amount);
  if (Number.isNaN(n)) return "—";
  const text = n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const lang = window.__atrLang || "en";
  return lang === "fr" ? `${text} DH` : `₹${text}`;
}

function atrT(key, vars = {}) {
  const catalog = window.__atrI18n || {};
  let text = catalog[key] || key;
  for (const [name, value] of Object.entries(vars)) {
    text = text.split(`{${name}}`).join(String(value));
  }
  return text;
}

function atrPipelineStageLabel(stageKey, fallback) {
  const key = `pipeline.stage.${stageKey}`;
  const translated = atrT(key);
  return translated !== key ? translated : fallback || stageKey;
}
