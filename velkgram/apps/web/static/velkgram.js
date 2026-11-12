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

// Live updates: the page polls a count of newer rows and shows it as a pill. Visiting the tab
// again refreshes at once; at the top of the page the pill applies itself; the title carries
// the count while the pill is up.
(() => {
  const TOP_PX = 100;
  const BADGE = /^\(\d+\) /;

  const syncTitle = () => {
    const pill = document.querySelector("[data-live-pill]");
    const base = document.title.replace(BADGE, "");
    document.title = pill ? `(${pill.dataset.liveCount}) ${base}` : base;
  };

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    for (const live of document.querySelectorAll("[data-live]")) {
      live.dispatchEvent(new CustomEvent("live-refresh"));
    }
  });

  document.addEventListener("htmx:afterSwap", syncTitle);

  // A 204 means nothing is new any more (a deletion): htmx does not swap, so empty the region
  // ourselves, which drops the stale pill and its title badge.
  document.addEventListener("htmx:afterRequest", (event) => {
    const target = event.target;
    if (!(target instanceof Element) || !target.matches("[data-live]")) return;
    if (event.detail.xhr?.status !== 204) return;
    target.replaceChildren();
    syncTitle();
  });

  // Settled, not just swapped: the pill's own hx-get is processed by then, so a click works.
  document.addEventListener("htmx:afterSettle", (event) => {
    const target = event.target;
    if (!(target instanceof Element) || !target.matches("[data-live]")) return;
    const pill = target.querySelector("[data-live-pill]");
    if (pill instanceof HTMLElement && window.scrollY < TOP_PX) pill.click();
  });
})();

// A product image that fails to load (dead link, hotlink block) steps aside so the placeholder
// icon behind it shows. `error` does not bubble, so listen in the capture phase. The Amazon CDN
// answers an unknown ASIN with a 1x1 GIF that loads fine, so a tiny image counts as broken too.
(() => {
  const isThumb = (img) => img instanceof HTMLImageElement && img.classList.contains("offer-thumb");
  const markIfTiny = (img) => {
    if (isThumb(img) && img.naturalWidth > 0 && img.naturalWidth < 8) img.classList.add("is-broken");
  };
  document.addEventListener(
    "error",
    (event) => {
      if (isThumb(event.target)) event.target.classList.add("is-broken");
    },
    true,
  );
  document.addEventListener("load", (event) => markIfTiny(event.target), true);
  document.querySelectorAll("img.offer-thumb").forEach((img) => {
    if (img.complete) markIfTiny(img);
  });
})();

// Menus are native popovers (light dismiss, Escape and focus return come with the platform).
// The browser puts a popover in the top layer, so place it under its button, right-aligned.
(() => {
  const GAP = 4;
  const MARGIN = 8;
  document.addEventListener("toggle", (event) => {
    const menu = event.target;
    if (!(menu instanceof HTMLElement) || !menu.matches(".vg-menu") || event.newState !== "open") return;
    const button = document.querySelector(`[popovertarget="${menu.id}"]`);
    if (!button) return;
    const anchor = button.getBoundingClientRect();
    const box = menu.getBoundingClientRect();
    const left = Math.min(Math.max(anchor.right - box.width, MARGIN), innerWidth - box.width - MARGIN);
    const fitsBelow = anchor.bottom + GAP + box.height <= innerHeight - MARGIN;
    menu.style.left = `${left}px`;
    menu.style.top = `${fitsBelow ? anchor.bottom + GAP : Math.max(anchor.top - GAP - box.height, MARGIN)}px`;
  }, true);
})();

// Dialogs: [data-dialog-open="id"] opens a modal, [data-dialog-close] closes the one around it,
// and a click outside its box (on the backdrop) closes it too.
(() => {
  const closest = (event, selector) =>
    event.target instanceof Element ? event.target.closest(selector) : null;
  document.addEventListener("click", (event) => {
    const opener = closest(event, "[data-dialog-open]");
    if (opener) {
      const dialog = document.getElementById(opener.dataset.dialogOpen ?? "");
      if (dialog instanceof HTMLDialogElement && !dialog.open) dialog.showModal();
      return;
    }
    if (closest(event, "[data-dialog-close]")) {
      closest(event, "dialog")?.close();
      return;
    }
    // A click on the backdrop lands on the dialog or, in some engines, on the root element.
    const dialog = document.querySelector("dialog:modal");
    if (!dialog || (event.target !== dialog && event.target !== document.documentElement)) return;
    const box = dialog.getBoundingClientRect();
    const inside =
      event.clientX >= box.left && event.clientX <= box.right &&
      event.clientY >= box.top && event.clientY <= box.bottom;
    if (!inside) dialog.close();
  });
})();
