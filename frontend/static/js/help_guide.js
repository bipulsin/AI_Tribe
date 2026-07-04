/**
 * Help guide modal — open/close, focus trap, soft copy deterrent.
 * Soft UX deterrent only (user-select / contextmenu / copy block on the
 * modal content) — not real content protection.
 */
(function () {
  const openBtn = document.getElementById("help-guide-open");
  const modal = document.getElementById("help-guide-modal");
  if (!openBtn || !modal) return;

  const panel = modal.querySelector(".help-guide-panel");
  const content = document.getElementById("help-guide-content");
  const closeEls = modal.querySelectorAll("[data-help-close]");
  let lastFocus = null;

  function focusable() {
    if (!panel) return [];
    return Array.from(
      panel.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      )
    ).filter((el) => !el.hasAttribute("disabled") && el.offsetParent !== null);
  }

  function openModal() {
    lastFocus = document.activeElement;
    modal.hidden = false;
    openBtn.setAttribute("aria-expanded", "true");
    document.body.classList.add("help-guide-open");
    (panel || modal).focus();
  }

  function closeModal() {
    modal.hidden = true;
    openBtn.setAttribute("aria-expanded", "false");
    document.body.classList.remove("help-guide-open");
    if (lastFocus && typeof lastFocus.focus === "function") {
      lastFocus.focus();
    } else {
      openBtn.focus();
    }
  }

  openBtn.addEventListener("click", openModal);
  closeEls.forEach((el) => el.addEventListener("click", closeModal));

  document.addEventListener("keydown", (event) => {
    if (modal.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeModal();
      return;
    }
    if (event.key !== "Tab") return;
    const nodes = focusable();
    if (!nodes.length) {
      event.preventDefault();
      return;
    }
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  // Soft UX deterrent — scoped to modal content only.
  if (content) {
    content.addEventListener("contextmenu", (event) => {
      if (!modal.hidden) event.preventDefault();
    });
    content.addEventListener("copy", (event) => {
      if (!modal.hidden) event.preventDefault();
    });
    content.addEventListener("cut", (event) => {
      if (!modal.hidden) event.preventDefault();
    });
  }

  document.addEventListener("keydown", (event) => {
    if (modal.hidden) return;
    const key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === "c") {
      const sel = window.getSelection();
      if (sel && content && content.contains(sel.anchorNode)) {
        event.preventDefault();
      }
    }
  });
})();
