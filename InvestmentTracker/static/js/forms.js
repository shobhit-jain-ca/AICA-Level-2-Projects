/* Small progressive enhancements for server-rendered forms */
document.querySelectorAll("form.js-confirm").forEach((f) => {
  f.addEventListener("submit", (e) => { if (!confirm(f.dataset.msg || "Are you sure?")) e.preventDefault(); });
});
const rep = document.getElementById("replaceBox"), go = document.getElementById("confirmBtn");
if (rep && go) {
  const sync = () => { go.disabled = !rep.checked; };
  rep.addEventListener("change", sync); sync();
}
document.querySelectorAll("form.js-once").forEach((f) => {
  f.addEventListener("submit", () => { const b = f.querySelector("button[type=submit]"); if (b) { b.disabled = true; b.textContent = "Please wait…"; } });
});
