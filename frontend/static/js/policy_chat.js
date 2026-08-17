function policyChat(bootstrap = {}) {
  return {
    messages: bootstrap.messages || [],
    summary: bootstrap.summary || {},
    draft: "",
    busy: false,
    formatText(text) {
      const escaped = String(text || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      return escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
    },
    init() {
      this.$nextTick(() => this.scrollToBottom());
    },
    scrollToBottom() {
      const pane = this.$refs.thread || document.getElementById("policy-thread");
      if (pane) pane.scrollTop = pane.scrollHeight;
    },
    refreshSummary() {
      if (window.htmx) {
        window.htmx.ajax("GET", "/policy/summary", { target: "#policy-summary", swap: "innerHTML" });
      }
    },
    async send(text) {
      const value = String(text || "").trim();
      if (!value || this.busy) return;
      this.busy = true;
      try {
        const resp = await fetch("/policy/chat/message", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ text: value }),
        });
        const data = await resp.json();
        if (data.messages) this.messages = data.messages;
        if (data.summary) this.summary = data.summary;
        this.$nextTick(() => this.scrollToBottom());
        this.refreshSummary();
      } finally {
        this.busy = false;
      }
    },
    sendComposer() {
      const value = this.draft;
      this.draft = "";
      this.send(value);
    },
    async startNew() {
      this.busy = true;
      try {
        const resp = await fetch("/policy/chat/start", {
          method: "POST",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const data = await resp.json();
        this.messages = data.messages || [];
        this.summary = data.summary || {};
        this.$nextTick(() => this.scrollToBottom());
        this.refreshSummary();
      } finally {
        this.busy = false;
      }
    },
  };
}
