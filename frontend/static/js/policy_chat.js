function policyChat(bootstrap = {}) {
  return {
    messages: bootstrap.messages || [],
    summary: bootstrap.summary || {},
    currentStep: bootstrap.current_step || "",
    status: bootstrap.status || "",
    draft: "",
    busy: false,
    selectedPayment: "",
    cardHolder: "",
    cardDigits: "",
    cardExpiry: "",
    cardCvv: "",
    payError: "",
    payBusy: false,
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
    applyBooking(data) {
      if (data.messages) this.messages = data.messages;
      if (data.summary) this.summary = data.summary;
      if (data.current_step) this.currentStep = data.current_step;
      if (data.status) this.status = data.status;
      this.$nextTick(() => this.scrollToBottom());
      this.refreshSummary();
    },
    refreshSummary() {
      if (window.htmx) {
        window.htmx.ajax("GET", "/policy/summary", { target: "#policy-summary", swap: "innerHTML" });
      }
    },
    selectPay(method) {
      this.selectedPayment = method;
      this.payError = "";
    },
    cardDisplay() {
      const digits = this.cardDigits || "";
      if (digits.length <= 4) return digits;
      return "*".repeat(digits.length - 4) + digits.slice(-4);
    },
    onCardInput(event) {
      const digits = String(event.target.value || "").replace(/\D/g, "").slice(0, 16);
      this.cardDigits = digits;
      event.target.value = this.cardDisplay();
    },
    async payNow() {
      if (this.payBusy || this.busy) return;
      if (!this.selectedPayment) {
        this.payError = "Please select a payment method.";
        return;
      }
      if (this.selectedPayment === "cards") {
        if (!this.cardHolder.trim() || !this.cardDigits || !this.cardExpiry.trim() || !this.cardCvv.trim()) {
          this.payError = "Please fill in the card details.";
          return;
        }
      }
      this.payError = "";
      this.payBusy = true;
      this.busy = true;
      try {
        const body = {
          selected_payment_method: this.selectedPayment,
          wallet_name: this.selectedPayment === "cards" ? null : this.selectedPayment,
          card_holder_name: this.cardHolder,
          card_number: this.cardDigits,
          card_number_masked: this.cardDigits.slice(-4),
          expiry: this.cardExpiry,
          cvv: this.cardCvv,
        };
        const resp = await fetch("/policy/payment/process", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (data.messages) this.applyBooking(data);
        if (!resp.ok) {
          this.payError = data.detail || "Payment could not be completed.";
        } else {
          this.payError = "";
        }
      } finally {
        this.payBusy = false;
        this.busy = false;
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
        this.applyBooking(data);
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
        this.selectedPayment = "";
        this.cardHolder = "";
        this.cardDigits = "";
        this.cardExpiry = "";
        this.cardCvv = "";
        this.payError = "";
        this.applyBooking(data);
      } finally {
        this.busy = false;
      }
    },
  };
}
