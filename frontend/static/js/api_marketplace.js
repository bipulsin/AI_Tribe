function apiMarketplace(bootstrap = {}) {
  const data = bootstrap || {};
  return {
    validityOptions: data.validityOptions || [30, 60, 90, 120, 180, 360],
    defaultValidity: data.defaultValidity || 90,
    validityDays: data.defaultValidity || 90,
    tokenView: data.tokenView || null,
    catalog: data.catalog || [],
    chains: data.chains || [],
    baseUrl: String(data.baseUrl || "").replace(/\/$/, ""),
    revealedToken: "",
    maskedToken: "atr_live_••••••••",
    chainName: "",
    // Cascading dropdown selections; "" means END (shown as first option value "END")
    chainSelections: ["END"],
    busy: false,
    message: "",

    get chainableSubscribed() {
      return (this.catalog || []).filter(
        (item) =>
          item &&
          !item.wip &&
          !item.always_subscribed &&
          item.subscribed &&
          item.api_name !== "submit_claim"
      );
    },

    get followOnApis() {
      const out = [];
      for (const sel of this.chainSelections || []) {
        if (!sel || sel === "END") break;
        out.push(sel);
      }
      return out;
    },

    get canSubmitChain() {
      return !!(this.chainName || "").trim();
    },

    init() {
      if (this.tokenView && this.tokenView.token_prefix) {
        this.maskedToken = this.tokenView.token_prefix + "…";
      }
      if (!this.chainSelections.length) {
        this.chainSelections = ["END"];
      }
    },

    optionsForStep(idx) {
      const used = new Set();
      for (let i = 0; i < idx; i += 1) {
        const prev = this.chainSelections[i];
        if (prev && prev !== "END") used.add(prev);
      }
      const options = [{ value: "END", label: "END — finish chain here" }];
      for (const item of this.chainableSubscribed) {
        if (used.has(item.api_name)) continue;
        options.push({ value: item.api_name, label: item.title || item.api_name });
      }
      return options;
    },

    onChainStepChange(idx, value) {
      const next = value || "END";
      const updated = this.chainSelections.slice(0, idx);
      updated[idx] = next;

      if (next === "END") {
        this.chainSelections = updated;
        return;
      }

      // Keep only selected APIs up to here, then offer another dropdown (default END)
      // until END or every subscribed API is already used.
      const usedCount = updated.filter((v) => v && v !== "END").length;
      const maxSteps = this.chainableSubscribed.length;
      if (usedCount < maxSteps) {
        updated.push("END");
      }
      this.chainSelections = updated;
    },

    formatChainSteps(chain) {
      const steps = (chain && chain.steps) || [];
      return steps
        .map((s) => `${s.order}. ${s.title || s.api_name}`)
        .join(" → ");
    },

    async generateToken() {
      this.busy = true;
      this.message = "";
      try {
        const resp = await fetch("/api/marketplace/token", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ validity_days: this.validityDays || this.defaultValidity }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.message = data.detail || "Could not generate token.";
          return;
        }
        this.tokenView = data.token_view;
        this.revealedToken = data.token || "";
        this.maskedToken =
          (data.token_view && data.token_view.token_prefix) || "atr_live_…";
        this.message = "New token generated. Previous token (if any) is revoked.";
      } finally {
        this.busy = false;
      }
    },

    async showToken() {
      this.busy = true;
      this.message = "";
      try {
        const resp = await fetch("/api/marketplace/token/reveal", {
          method: "POST",
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.message = data.detail || "Could not reveal token.";
          return;
        }
        this.revealedToken = data.token || "";
        this.tokenView = data.token_view;
        this.message = "Token revealed (this action was audited).";
      } finally {
        this.busy = false;
      }
    },

    async copyToken() {
      if (!this.revealedToken) return;
      try {
        await navigator.clipboard.writeText(this.revealedToken);
        this.message = "Token copied to clipboard.";
      } catch (_err) {
        this.message = "Select the field and copy manually.";
      }
    },

    async toggleSubscribe(item, enabled) {
      if (!item || item.wip || item.always_subscribed) return;
      const previous = !!item.subscribed;
      item.subscribed = !!enabled;
      this.busy = true;
      this.message = "";
      try {
        const resp = await fetch("/api/marketplace/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ api_name: item.api_name, enabled: !!enabled }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          item.subscribed = previous;
          this.message = data.detail || "Could not update subscription.";
          return;
        }
        if (data.catalog) this.catalog = data.catalog;
        // Reset chain picker so options stay in sync with subscriptions.
        this.chainSelections = ["END"];
        this.message = enabled
          ? `Subscribed to ${item.title}.`
          : `Unsubscribed from ${item.title}.`;
      } finally {
        this.busy = false;
      }
    },

    sampleCurl(item) {
      const token = this.revealedToken || this.maskedToken;
      const path = (item.path || "")
        .replace("{claim_no}", "CLM-2026-000001")
        .replace("{claim_ref}", "CLM-2026-000001");
      const url = `${this.baseUrl}${path}`;
      if (item.method === "POST" && item.api_name === "submit_claim") {
        return `curl -X POST '${url}' \\\n  -H 'Authorization: Bearer ${token}' \\\n  -H 'Content-Type: application/json' \\\n  -d '{"surveyor_name":"Ada","claimant_name":"Raj","garage_name":"Metro Motors","date_of_accident":"2026-03-15"}'`;
      }
      if (item.api_name === "submit_images") {
        return `curl -X POST '${url}' \\\n  -H 'Authorization: Bearer ${token}' \\\n  -F 'images=@damage1.jpg'`;
      }
      return `curl -X ${item.method} '${url}' \\\n  -H 'Authorization: Bearer ${token}' \\\n  -H 'Accept: application/json'`;
    },

    samplePython(item) {
      const token = this.revealedToken || this.maskedToken;
      const path = (item.path || "")
        .replace("{claim_no}", "CLM-2026-000001")
        .replace("{claim_ref}", "CLM-2026-000001");
      const url = `${this.baseUrl}${path}`;
      return `import requests\n\nr = requests.request(\n    "${item.method}",\n    "${url}",\n    headers={"Authorization": "Bearer ${token}"},\n)\nprint(r.status_code, r.json())`;
    },

    chainCurl(chain) {
      const token = this.revealedToken || this.maskedToken;
      const lines = [
        `# 1. submit_claim → capture claim_no + upload_token`,
        `CLAIM_NO=$(curl -s -X POST '${this.baseUrl}/api/v1/external/claims/submit' \\`,
        `  -H 'Authorization: Bearer ${token}' -H 'Content-Type: application/json' \\`,
        `  -d '{"surveyor_name":"Ada","claimant_name":"Raj","garage_name":"Metro Motors","date_of_accident":"2026-03-15"}' | jq -r .data.claim_no)`,
      ];
      for (const step of chain.steps || []) {
        if (step.api_name === "submit_claim") continue;
        if (step.api_name === "submit_images") {
          lines.push(
            `# ${step.order}. submit_images`,
            `curl -X POST "${this.baseUrl}/api/v1/external/claims/$CLAIM_NO/images" \\`,
            `  -H "Authorization: Bearer ${token}" -F 'images=@damage1.jpg'`
          );
        } else if (step.api_name === "claim_detail") {
          lines.push(
            `# ${step.order}. claim_detail`,
            `curl -H "Authorization: Bearer ${token}" "${this.baseUrl}/api/v1/external/claims/$CLAIM_NO"`
          );
        } else if (step.api_name === "assessment_detail") {
          lines.push(
            `# ${step.order}. assessment_detail`,
            `curl -H "Authorization: Bearer ${token}" "${this.baseUrl}/api/v1/external/claims/$CLAIM_NO/assessment"`
          );
        } else if (step.api_name === "estimation_detail") {
          lines.push(
            `# ${step.order}. estimation_detail`,
            `curl -H "Authorization: Bearer ${token}" "${this.baseUrl}/api/v1/external/claims/$CLAIM_NO/estimate"`
          );
        }
      }
      return lines.join("\n");
    },

    async createChain() {
      this.busy = true;
      this.message = "";
      try {
        const resp = await fetch("/api/marketplace/chains", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            chain_name: this.chainName,
            follow_on: this.followOnApis,
          }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.message = data.detail || "Could not create chain.";
          return;
        }
        this.chains = data.chains || [];
        this.chainName = "";
        this.chainSelections = ["END"];
        this.message = "Chain saved.";
      } finally {
        this.busy = false;
      }
    },

    async removeChain(id) {
      if (!id || !window.confirm("Delete this chain?")) return;
      const resp = await fetch(`/api/marketplace/chains/${id}`, {
        method: "DELETE",
        credentials: "same-origin",
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok) {
        this.chains = data.chains || [];
        this.message = "Chain deleted.";
      } else {
        this.message = data.detail || "Could not delete chain.";
      }
    },
  };
}
