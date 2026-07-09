function userChrome() {
  return {
    initialName: "",
    profile: {
      full_name: "",
      date_of_birth: "",
      has_photo: false,
      photo_url: null,
      username: "",
    },
    profileOpen: false,
    settingsOpen: false,
    photoMessage: "",
    nameMessage: "",
    dobMessage: "",
    passwordMessage: "",
    passwordCurrent: "",
    passwordNew: "",
    llmSettings: null,
    llmKeyInputs: {},
    llmMessage: "",
    llmSaving: false,
    llmTesting: "",
    llmTestResults: {},

    get initials() {
      const name = this.profile.full_name || this.initialName || "?";
      return name
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((p) => p[0]?.toUpperCase() || "")
        .join("") || "?";
    },

    async init() {
      this.initialName = this.$el.dataset.initialName || "User";
      this.profile.full_name = this.initialName;
      await this.refreshProfile();
    },

    async refreshProfile() {
      const resp = await fetch("/api/user/profile");
      if (!resp.ok) return;
      const data = await resp.json();
      this.profile = {
        full_name: data.full_name || "",
        date_of_birth: data.date_of_birth || "",
        has_photo: !!data.has_photo,
        photo_url: data.photo_url,
        username: data.username || "",
      };
    },

    openProfile() {
      this.settingsOpen = false;
      this.profileOpen = true;
      document.body.classList.add("chrome-panel-open");
    },

    closeProfile() {
      this.profileOpen = false;
      if (!this.settingsOpen) document.body.classList.remove("chrome-panel-open");
    },

    async openSettings() {
      this.profileOpen = false;
      this.settingsOpen = true;
      document.body.classList.add("chrome-panel-open");
      await this.refreshLlmSettings();
    },

    closeSettings() {
      this.settingsOpen = false;
      if (!this.profileOpen) document.body.classList.remove("chrome-panel-open");
    },

    providerLabel(provider) {
      return String(provider || "")
        .replace(/_/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase());
    },

    providerConfigured(provider) {
      if (!this.llmSettings?.keys) return false;
      return this.llmSettings.keys.some((row) => row.provider === provider);
    },

    providerHint(provider) {
      const row = (this.llmSettings?.keys || []).find((item) => item.provider === provider);
      return row?.key_hint ? `Saved ${row.key_hint}` : "Configured";
    },

    async refreshLlmSettings() {
      this.llmMessage = "";
      const resp = await fetch("/api/user/llm-settings");
      if (!resp.ok) {
        this.llmMessage = "Could not load LLM settings.";
        return;
      }
      this.llmSettings = await resp.json();
      const inputs = {};
      for (const provider of this.llmSettings.providers || []) {
        inputs[provider] = this.llmKeyInputs[provider] || "";
      }
      this.llmKeyInputs = inputs;
    },

    async saveLlmKey(provider) {
      const apiKey = (this.llmKeyInputs[provider] || "").trim();
      if (!apiKey) return;
      this.llmSaving = true;
      this.llmMessage = "";
      try {
        const resp = await fetch("/api/user/llm-settings/keys", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider, api_key: apiKey }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.llmMessage = data.detail || "Could not save API key.";
          return;
        }
        this.llmSettings = data.settings;
        this.llmKeyInputs[provider] = "";
        this.llmMessage = `${this.providerLabel(provider)} key saved.`;
      } finally {
        this.llmSaving = false;
      }
    },

    async removeLlmKey(provider) {
      this.llmMessage = "";
      const resp = await fetch(`/api/user/llm-settings/keys/${provider}`, {
        method: "DELETE",
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        this.llmMessage = data.detail || "Could not remove key.";
        return;
      }
      this.llmSettings = data;
      delete this.llmTestResults[provider];
      this.llmMessage = `${this.providerLabel(provider)} key removed.`;
    },

    async testLlmKey(provider) {
      this.llmTesting = provider;
      this.llmMessage = "";
      const body = {};
      const draft = (this.llmKeyInputs[provider] || "").trim();
      if (draft) body.api_key = draft;
      try {
        const resp = await fetch(`/api/user/llm-settings/keys/${provider}/test`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));
        this.llmTestResults = {
          ...this.llmTestResults,
          [provider]: { ok: !!data.ok, message: data.message || data.detail || "Test failed." },
        };
      } finally {
        this.llmTesting = "";
      }
    },

    async saveLlmPreferences() {
      if (!this.llmSettings) return;
      this.llmMessage = "";
      const resp = await fetch("/api/user/llm-settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          active_provider: this.llmSettings.active_provider || null,
          toggle_deepfake: this.llmSettings.toggles.toggle_deepfake,
          toggle_vmmr: this.llmSettings.toggles.toggle_vmmr,
          toggle_estimation: this.llmSettings.toggles.toggle_estimation,
          toggle_fraud: this.llmSettings.toggles.toggle_fraud,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        this.llmMessage = data.detail || "Could not save preferences.";
        return;
      }
      this.llmSettings = data;
      this.llmMessage = "Preferences saved.";
    },

    async setLlmToggle(toggle, enabled) {
      if (!this.llmSettings) return;
      this.llmSettings.toggles[toggle] = enabled;
      await this.saveLlmPreferences();
    },

    async saveFullName() {
      this.nameMessage = "";
      const resp = await fetch("/api/user/profile/full-name", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full_name: this.profile.full_name.trim() }),
      });
      const data = await resp.json().catch(() => ({}));
      this.nameMessage = resp.ok ? "Name saved." : data.detail || "Could not save name.";
      if (resp.ok) this.initialName = this.profile.full_name;
    },

    async saveDob() {
      this.dobMessage = "";
      const resp = await fetch("/api/user/profile/date-of-birth", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date_of_birth: this.profile.date_of_birth || null }),
      });
      const data = await resp.json().catch(() => ({}));
      this.dobMessage = resp.ok ? "Date of birth saved." : data.detail || "Could not save date.";
    },

    async savePassword() {
      this.passwordMessage = "";
      const resp = await fetch("/api/user/profile/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: this.passwordCurrent,
          new_password: this.passwordNew,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok) {
        this.passwordMessage = "Password updated.";
        this.passwordCurrent = "";
        this.passwordNew = "";
      } else {
        this.passwordMessage = data.detail || "Could not update password.";
      }
    },

    async uploadPhoto(event) {
      this.photoMessage = "";
      const file = event.target.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append("photo", file);
      const resp = await fetch("/api/user/profile/photo", { method: "POST", body: form });
      const data = await resp.json().catch(() => ({}));
      this.photoMessage = resp.ok ? "Photo updated." : data.detail || "Upload failed.";
      if (resp.ok) await this.refreshProfile();
      event.target.value = "";
    },

    async removePhoto() {
      this.photoMessage = "";
      const resp = await fetch("/api/user/profile/photo", { method: "DELETE" });
      if (resp.ok) {
        this.photoMessage = "Photo removed.";
        await this.refreshProfile();
      }
    },
  };
}
