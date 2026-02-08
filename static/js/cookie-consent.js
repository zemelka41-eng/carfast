(function () {
  var storageKey = "carfst_cookie_consent";
  var ttlMs = 180 * 24 * 60 * 60 * 1000;

  function isValidConsent() {
    try {
      var raw = window.localStorage.getItem(storageKey);
      if (!raw) return false;
      var data = JSON.parse(raw);
      return Boolean(data && data.expires_at && Date.now() < data.expires_at);
    } catch (err) {
      return false;
    }
  }

  function setConsent(type) {
    try {
      var payload = { value: true, type: type || "all", expires_at: Date.now() + ttlMs };
      window.localStorage.setItem(storageKey, JSON.stringify(payload));
    } catch (err) {
      // Ignore storage errors.
    }
  }

  function init() {
    var banner = document.getElementById("cookie-consent");
    if (!banner) return;
    if (isValidConsent()) {
      banner.classList.add("is-hidden");
      document.body.classList.remove("has-cookie-consent");
    } else {
      banner.classList.remove("is-hidden");
      document.body.classList.add("has-cookie-consent");
    }
    var btnNecessary = banner.querySelector("[data-cookie-necessary]");
    var btnAll = banner.querySelector("[data-cookie-all]");
    if (!btnNecessary && !btnAll) return;
    if (btnNecessary) {
      btnNecessary.addEventListener("click", function () {
        setConsent("necessary");
        banner.classList.add("is-hidden");
        document.body.classList.remove("has-cookie-consent");
      });
    }
    if (btnAll) {
      btnAll.addEventListener("click", function () {
        setConsent("all");
        banner.classList.add("is-hidden");
        document.body.classList.remove("has-cookie-consent");
      });
    }
    if (btnNecessary || btnAll) {
      return;
    }
    var button = banner.querySelector("[data-cookie-accept]");
    if (!button) return;
    button.addEventListener("click", function () {
      setConsent("all");
      banner.classList.add("is-hidden");
      document.body.classList.remove("has-cookie-consent");
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
