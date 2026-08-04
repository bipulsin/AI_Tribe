function usageReport({ defaultStart, defaultEnd, users = [] } = {}) {
  return {
    start: defaultStart || "",
    end: defaultEnd || "",
    userId: "",
    users: users || [],
    rows: [],
    details: {},
    expanded: {},
    detailLoadingKey: "",
    busy: false,
    error: "",

    init() {
      this.load();
    },

    rowKey(row) {
      return String(row.user.id);
    },

    isExpanded(row) {
      return !!this.expanded[this.rowKey(row)];
    },

    formatTime(iso) {
      if (!iso) return "—";
      try {
        const d = new Date(iso);
        return d.toISOString().replace("T", " ").slice(0, 19);
      } catch (_err) {
        return String(iso);
      }
    },

    async load() {
      this.busy = true;
      this.error = "";
      try {
        const params = new URLSearchParams();
        if (this.start) params.set("start", this.start);
        if (this.end) params.set("end", this.end);
        if (this.userId) params.set("user_id", this.userId);
        const resp = await fetch(`/api/admin/usage-report?${params}`, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.error = data.detail || "Could not load report.";
          this.rows = [];
          return;
        }
        this.rows = data.rows || [];
        if (data.users) this.users = data.users;
        this.details = {};
        this.expanded = {};
      } catch (_err) {
        this.error = "Network error loading report.";
      } finally {
        this.busy = false;
      }
    },

    async toggleDetail(row) {
      if (!row || row.status !== "accessed") return;
      const key = this.rowKey(row);
      if (this.expanded[key]) {
        this.expanded = { ...this.expanded, [key]: false };
        return;
      }
      this.expanded = { ...this.expanded, [key]: true };
      if (this.details[key]) return;
      this.detailLoadingKey = key;
      try {
        const params = new URLSearchParams({
          user_id: String(row.user.id),
          start: row.range_start || this.start,
          end: row.range_end || this.end,
        });
        const resp = await fetch(`/api/admin/usage-report/detail?${params}`, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.error = data.detail || "Could not load detail.";
          return;
        }
        this.details = { ...this.details, [key]: data.events || [] };
      } finally {
        this.detailLoadingKey = "";
      }
    },
  };
}
