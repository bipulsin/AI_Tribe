function apiMarketplace({
  validityOptions = [30, 60, 90, 120, 180, 360],
  defaultValidity = 90,
  chainableApis = [],
  tokenView = null,
  catalog = [],
  chains = [],
  baseUrl = "",
} = {}) {
  return {
    validityOptions,
    defaultValidity,
    validityDays: defaultValidity,
    chainableApis,
    tokenView,
    catalog,
    chains,
    baseUrl: (baseUrl || "").replace(/\/$/, ""),
    revealedToken: "",
    maskedToken: "atr_live_••••••••",
    chainName: "",
    chainFollowOn: [],
    busy: false,
    message: "",

    init() {
      if (this.tokenView && this.tokenView.token_prefix) {
        this.maskedToken = this.tokenView.token_prefix + "…";
      }
    },

    async generateToken() {
      this.busy = true;
      this.message = "";
      try {
        const resp = await fetch("/api/marketplace/token", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ validity_days: this.validityDays }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.message = data.detail || "Could not generate token.";
          return;
        }
        this.tokenView = data.token_view;
        this.revealedToken = data.token || "";
        this.maskedToken = (data.token_view && data.token_view.token_prefix) || "atr_live_…";
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
      if (!item || item.wip) return;
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
          this.message = data.detail || "Could not update subscription.";
          item.subscribed = !enabled;
          return;
        }
        if (data.catalog) this.catalog = data.catalog;
        item.subscribed = !!enabled;
      } finally {
        this.busy = false;
      }
    },

    sampleCurl(item) {
      const token = this.revealedToken || this.maskedToken;
      const path = (item.path || "").replace("{claim_no}", "CLM-2026-000001").replace("{claim_ref}", "CLM-2026-000001");
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
      const path = (item.path || "").replace("{claim_no}", "CLM-2026-000001").replace("{claim_ref}", "CLM-2026-000001");
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
            follow_on: this.chainFollowOn,
          }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.message = data.detail || "Could not create chain.";
          return;
        }
        this.chains = data.chains || [];
        this.chainName = "";
        this.chainFollowOn = [];
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
      if (resp.ok) this.chains = data.chains || [];
      else this.message = data.detail || "Could not delete chain.";
    },
  };
}
