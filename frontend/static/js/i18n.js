/** Client-side UI strings from static catalog (see backend/app/i18n/). */
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
