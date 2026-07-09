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

    openSettings() {
      this.profileOpen = false;
      this.settingsOpen = true;
      document.body.classList.add("chrome-panel-open");
    },

    closeSettings() {
      this.settingsOpen = false;
      if (!this.profileOpen) document.body.classList.remove("chrome-panel-open");
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
