(() => {
  const toast = document.getElementById("achieveToast");
  if (toast) {
    toast.classList.add("achieve-toast--pop");
    spawnConfetti(toast);
    setTimeout(() => toast.classList.add("achieve-toast--hide"), 5200);
  }

  function spawnConfetti(anchor) {
    const rect = anchor.getBoundingClientRect();
    const colors = ["#8fd4b0", "#176b50", "#e4f3ec", "#f7ebe3"];
    for (let i = 0; i < 18; i++) {
      const p = document.createElement("span");
      p.className = "confetti";
      p.style.left = `${rect.left + rect.width / 2 + (Math.random() - 0.5) * 120}px`;
      p.style.top = `${rect.top + 20}px`;
      p.style.background = colors[i % colors.length];
      p.style.setProperty("--dx", `${(Math.random() - 0.5) * 160}px`);
      p.style.setProperty("--dy", `${60 + Math.random() * 120}px`);
      p.style.setProperty("--rot", `${Math.random() * 540}deg`);
      document.body.appendChild(p);
      setTimeout(() => p.remove(), 1600);
    }
  }

  initSwipeRows();
  initAchievementStagger();

  function initSwipeRows() {
    const rows = document.querySelectorAll("[data-swipe]");
    if (!rows.length) return;

    rows.forEach((row) => {
      const panel = row.querySelector(".swipe-row__panel");
      const actions = row.querySelector(".swipe-row__actions");
      if (!panel || !actions) return;

      const width = actions.offsetWidth;
      row.style.setProperty("--swipe-width", `${width}px`);

      let startX = 0;
      let currentX = 0;
      let dragging = false;

      const setOffset = (dx) => {
        const clamped = Math.max(-width, Math.min(0, dx));
        panel.style.transform = `translateX(${clamped}px)`;
        return clamped;
      };

      const snap = (dx) => {
        panel.style.transform = "";
        if (dx < -width * 0.35) row.classList.add("is-open");
        else row.classList.remove("is-open");
      };

      panel.addEventListener(
        "touchstart",
        (e) => {
          if (e.touches.length !== 1) return;
          startX = e.touches[0].clientX;
          currentX = row.classList.contains("is-open") ? -width : 0;
          dragging = true;
        },
        { passive: true }
      );

      panel.addEventListener(
        "touchmove",
        (e) => {
          if (!dragging) return;
          const dx = currentX + (e.touches[0].clientX - startX);
          if (Math.abs(dx) > 8) setOffset(dx);
        },
        { passive: true }
      );

      panel.addEventListener("touchend", (e) => {
        if (!dragging) return;
        dragging = false;
        const endX = e.changedTouches[0].clientX;
        const total = currentX + (endX - startX);
        snap(total);
      });

      panel.addEventListener("touchcancel", () => {
        dragging = false;
        panel.style.transform = "";
      });
    });

    document.addEventListener("click", (e) => {
      if (!e.target.closest("[data-swipe]")) {
        rows.forEach((r) => r.classList.remove("is-open"));
      }
    });
  }

  function initAchievementStagger() {
    const grid = document.querySelector(".achieve-grid--stagger");
    if (!grid) return;
    requestAnimationFrame(() => {
      grid.classList.add("is-ready");
      const statVal = document.querySelector(".stat .value");
      if (statVal) statVal.classList.add("value--pop");
    });
  }
})();
