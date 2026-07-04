/**
 * Medium-size modal for enlarged image / video preview (claims upload + assessment).
 */
(function () {
  const modal = document.getElementById("media-preview-modal");
  if (!modal) return;

  const panel = modal.querySelector(".media-preview-panel");
  const imageEl = document.getElementById("media-preview-image");
  const videoEl = document.getElementById("media-preview-video");
  const closeEls = modal.querySelectorAll("[data-media-preview-close]");
  let lastFocus = null;

  function hideEl(el) {
    el.hidden = true;
    el.removeAttribute("src");
  }

  function closePreview() {
    modal.hidden = true;
    hideEl(imageEl);
    hideEl(videoEl);
    if (videoEl.pause) videoEl.pause();
    document.body.style.overflow = "";
    if (lastFocus && typeof lastFocus.focus === "function") {
      lastFocus.focus();
    }
    lastFocus = null;
  }

  function openPreview({ src, alt = "", isVideo = false } = {}) {
    if (!src) return;

    lastFocus = document.activeElement;
    hideEl(imageEl);
    hideEl(videoEl);

    if (isVideo) {
      videoEl.src = src;
      videoEl.hidden = false;
    } else {
      imageEl.src = src;
      imageEl.alt = alt || "Claim image preview";
      imageEl.hidden = false;
    }

    modal.hidden = false;
    document.body.style.overflow = "hidden";
    (panel || modal).focus();
  }

  window.openMediaPreview = openPreview;

  closeEls.forEach((el) => {
    el.addEventListener("click", closePreview);
  });

  document.addEventListener("keydown", (event) => {
    if (modal.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closePreview();
    }
  });
})();
