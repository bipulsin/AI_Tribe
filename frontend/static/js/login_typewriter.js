/**
 * Login page typewriter for the BIONIC tagline frame.
 */
(function () {
  const frame = document.querySelector(".login-typewriter-frame");
  if (!frame) return;

  const line1 = frame.dataset.line1 || "";
  const line2 = frame.dataset.line2 || "";
  const el1 = document.getElementById("login-typewriter-l1");
  const el2 = document.getElementById("login-typewriter-l2");
  const cursor1 = document.getElementById("login-typewriter-cursor-1");
  const cursor2 = document.getElementById("login-typewriter-cursor-2");
  if (!el1 || !el2 || !cursor1 || !cursor2) return;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduceMotion) {
    el1.textContent = line1;
    el2.textContent = line2;
    cursor1.classList.add("is-hidden");
    cursor2.classList.add("is-hidden");
    return;
  }

  const CHAR_MS = 38;
  const LINE_PAUSE_MS = 420;
  const LOOP_PAUSE_MS = 2200;

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function typeInto(el, text, cursor) {
    el.textContent = "";
    for (let i = 0; i < text.length; i += 1) {
      el.textContent = text.slice(0, i + 1);
      await wait(CHAR_MS);
    }
    cursor.classList.add("is-hidden");
  }

  async function run() {
    while (true) {
      el1.textContent = "";
      el2.textContent = "";
      cursor1.classList.remove("is-hidden");
      cursor2.classList.add("is-hidden");
      await typeInto(el1, line1, cursor1);
      await wait(LINE_PAUSE_MS);
      cursor2.classList.remove("is-hidden");
      await typeInto(el2, line2, cursor2);
      await wait(LOOP_PAUSE_MS);
    }
  }

  run();
})();
