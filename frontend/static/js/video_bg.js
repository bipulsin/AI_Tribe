/**
 * Login background video: ensure autoplay works across browsers and
 * recover gracefully if the asset is missing.
 */
(function () {
  const video = document.getElementById("login-bg-video");
  if (!video) return;

  const tryPlay = () => {
    const playPromise = video.play();
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch(() => {
        // Autoplay blocked or asset missing — gradient overlay still provides contrast.
      });
    }
  };

  video.addEventListener("loadeddata", tryPlay);
  video.addEventListener("error", () => {
    video.classList.add("video-missing");
  });

  if (video.readyState >= 2) {
    tryPlay();
  }
})();
