document.addEventListener("click", (event) => {
  const close = event.target.closest(".notice-close");
  if (close) close.parentElement.remove();
});
document.addEventListener("submit", (event) => {
  const form = event.target.closest("[data-confirm]");
  if (form && !window.confirm(form.dataset.confirm)) event.preventDefault();
});
document.querySelectorAll(".product-card").forEach((card) => {
  card.addEventListener("pointermove", (event) => {
    if (innerWidth < 700) return;
    const r = card.getBoundingClientRect();
    card.style.setProperty(
      "--mx",
      `${((event.clientX - r.left) / r.width) * 100}%`,
    );
  });
});
