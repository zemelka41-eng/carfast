(() => {
  const CARD_SELECTOR = '[data-href][role="link"][tabindex]';
  const INTERACTIVE_SELECTOR = "a, button, input, select, textarea, label";

  function getCard(target) {
    if (!(target instanceof Element)) return null;
    return target.closest(CARD_SELECTOR);
  }

  function isInteractive(target, card) {
    if (!(target instanceof Element)) return false;
    const interactive = target.closest(INTERACTIVE_SELECTOR);
    return !!(interactive && card.contains(interactive));
  }

  function navigate(card) {
    const href = card.getAttribute("data-href") || "";
    if (!href) return;
    window.location.href = href;
  }

  document.addEventListener("click", (event) => {
    const card = getCard(event.target);
    if (!card) return;
    if (event.defaultPrevented) return;
    if (typeof event.button === "number" && event.button !== 0) return;
    if (isInteractive(event.target, card)) return;
    navigate(card);
  });

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const card = getCard(target);
    if (!card) return;
    if (target !== card) return; // ignore when focus is on inner controls

    if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
      event.preventDefault();
      navigate(card);
    }
  });
})();


