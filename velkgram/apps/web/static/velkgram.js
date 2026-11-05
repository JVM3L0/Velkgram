// Copy a coupon code with one tap. One delegated listener: it also covers cards that htmx
// adds later, and it keeps every name out of the global scope.
(() => {
  const FEEDBACK_MS = 2000;
  const timers = new WeakMap();

  const show = (button, message) => {
    const status = button.parentElement?.querySelector(".copy-status");
    if (!status) return;
    status.textContent = message;
    clearTimeout(timers.get(status));
    timers.set(
      status,
      setTimeout(() => {
        status.textContent = "";
      }, FEEDBACK_MS),
    );
  };

  // No clipboard access (plain http, old browser, denied): select the code so Ctrl+C works.
  const select = (button) => {
    const text = button.querySelector(".coupon-text");
    const selection = getSelection();
    if (!text || !selection) return false;
    const range = document.createRange();
    range.selectNodeContents(text);
    selection.removeAllRanges();
    selection.addRange(range);
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    }
  };

  document.addEventListener("click", async (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-copy]") : null;
    if (!button) return;
    const code = button.dataset.copy ?? "";
    try {
      await navigator.clipboard.writeText(code);
      show(button, "Copiado!");
    } catch {
      show(button, select(button) ? "Copiado!" : "Código selecionado");
    }
  });
})();

// Paged lists: a failed "Carregar mais" request keeps the button clickable and says so.
(() => {
  const mark = (event, failed) => {
    const button = event.target instanceof Element ? event.target.closest(".load-more") : null;
    if (button) button.classList.toggle("is-error", failed);
  };
  document.addEventListener("htmx:beforeRequest", (event) => mark(event, false));
  document.addEventListener("htmx:responseError", (event) => mark(event, true));
  document.addEventListener("htmx:sendError", (event) => mark(event, true));
})();

// "Voltar ao topo": shown after about two screens of scrolling.
(() => {
  const SCREENS = 2;
  const sync = () => {
    const far = window.scrollY > window.innerHeight * SCREENS;
    for (const button of document.querySelectorAll("[data-scroll-top]")) button.hidden = !far;
  };
  document.addEventListener("scroll", sync, { passive: true });
  document.addEventListener("htmx:afterSwap", sync);
  sync();
  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-scroll-top]") : null;
    if (!button) return;
    const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: calm ? "auto" : "smooth" });
    // The button hides itself at the top: hand focus to the page start so it is not lost.
    const main = document.querySelector("main");
    if (main instanceof HTMLElement) {
      main.setAttribute("tabindex", "-1");
      main.focus({ preventScroll: true });
    }
  });
})();
