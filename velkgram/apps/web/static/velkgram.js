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
