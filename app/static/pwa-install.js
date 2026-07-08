(() => {
  const KEY = "things_pwa_dismiss";
  if (window.matchMedia("(display-mode: standalone)").matches) return;
  if (localStorage.getItem(KEY) === "1") return;

  let deferred = null;
  const isIos =
    /iphone|ipad|ipod/i.test(navigator.userAgent) &&
    !window.MSStream &&
    !navigator.standalone;

  function bannerHtml(text, cta) {
    const el = document.createElement("div");
    el.id = "pwaInstall";
    el.className = "pwa-install";
    el.innerHTML = `
      <div class="pwa-install__text">${text}</div>
      <div class="pwa-install__actions">
        ${cta}
        <button type="button" class="linkish pwa-install__dismiss" aria-label="Закрыть">Позже</button>
      </div>`;
    document.body.appendChild(el);
    el.querySelector(".pwa-install__dismiss")?.addEventListener("click", () => {
      localStorage.setItem(KEY, "1");
      el.remove();
    });
    return el;
  }

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    if (document.getElementById("pwaInstall")) return;
    const el = bannerHtml(
      "Поставь «Стак» на Домой — как приложение",
      `<button type="button" class="btn btn-primary btn-compact" id="pwaInstallBtn">Установить</button>`
    );
    el.querySelector("#pwaInstallBtn")?.addEventListener("click", async () => {
      if (!deferred) return;
      deferred.prompt();
      await deferred.userChoice;
      deferred = null;
      localStorage.setItem(KEY, "1");
      el.remove();
    });
  });

  if (isIos) {
    setTimeout(() => {
      if (document.getElementById("pwaInstall")) return;
      bannerHtml(
        "На iPhone: Поделиться → «На экран Домой»",
        ""
      );
    }, 1800);
  }
})();
