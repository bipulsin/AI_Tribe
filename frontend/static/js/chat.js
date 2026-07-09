function chatApp({ userName = "User", maxImages = 10, maxUploadMb = 25 } = {}) {
  let nextId = 1;
  const completedPipelines = new Set();

  return {
    userName,
    maxImages,
    maxUploadMb,
    sidebarCollapsed: false,
    messages: [],
    draft: "",
    sending: false,
    showSuggestions: true,
    suggestions: [
      "Submit a claim",
      "Get details of claim CLM-2026-000017",
      "Find my claim",
    ],

    init() {
      window.addEventListener(
        "ai-tribe:pipeline-complete",
        (event) => this.onPipelineComplete(event.detail || {})
      );
    },

    openUserProfile() {
      window.dispatchEvent(new CustomEvent("ai-tribe:open-profile"));
    },

    formatText(text) {
      if (!text) return "";
      const escaped = String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      return escaped
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\n/g, "<br>");
    },

    scrollToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.thread;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    pushMessage(payload) {
      this.messages.push({
        id: nextId++,
        role: payload.role || "assistant",
        text: payload.text || "",
        widgets: payload.widgets || [],
      });
      this.scrollToBottom();
    },

    useSuggestion(hint) {
      this.draft = hint;
      this.sendMessage();
    },

    async sendMessage() {
      const text = (this.draft || "").trim();
      if (!text || this.sending) return;

      this.showSuggestions = false;
      this.pushMessage({ role: "user", text });
      this.draft = "";
      this.sending = true;

      try {
        const response = await fetch("/api/chat/message", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ text }),
        });
        const data = await response.json();
        if (!response.ok) {
          this.pushMessage({
            role: "assistant",
            text: data.detail || "Something went wrong. Please try again.",
          });
          return;
        }
        this.pushMessage(data);
      } catch (_err) {
        this.pushMessage({
          role: "assistant",
          text: "I couldn't reach the server. Check your connection and try again.",
        });
      } finally {
        this.sending = false;
      }
    },

    async onFilesSelected(event) {
      const input = event.target;
      const files = Array.from(input.files || []);
      if (!files.length) return;

      const images = [];
      let video = null;
      for (const file of files) {
        if (file.type.startsWith("video/") && !video) {
          video = file;
        } else if (file.type.startsWith("image/")) {
          images.push(file);
        }
      }

      const form = new FormData();
      images.forEach((file) => form.append("images", file));
      if (video) form.append("video", video);

      this.sending = true;
      try {
        const response = await fetch("/api/chat/upload", {
          method: "POST",
          credentials: "same-origin",
          body: form,
        });
        const data = await response.json();
        if (!response.ok) {
          this.pushMessage({
            role: "assistant",
            text: data.detail || "Upload failed.",
          });
          return;
        }
        this.showSuggestions = false;
        this.pushMessage(data);
      } catch (_err) {
        this.pushMessage({
          role: "assistant",
          text: "Upload failed — please try again.",
        });
      } finally {
        this.sending = false;
        input.value = "";
      }
    },

    async onPipelineComplete({ claimId }) {
      if (!claimId || completedPipelines.has(claimId)) return;
      completedPipelines.add(claimId);

      try {
        const response = await fetch(`/api/chat/claims/${claimId}/summary`, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) return;
        const data = await response.json();
        this.pushMessage({
          role: "assistant",
          text: `${data.text}\n\nPlease submit another claim, or ask me about an existing one.`,
        });
      } catch (_err) {
        // Pipeline UI already shows halt state; skip duplicate error noise.
      }
    },
  };
}
