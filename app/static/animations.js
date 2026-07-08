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
})();
