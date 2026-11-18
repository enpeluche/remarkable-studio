/* Thème jour / nuit : choix mémorisé, sinon réglage du système, suivi en direct.
   À charger dans le <head> : le thème est posé avant le premier affichage. Interrupteur : .theme-toggle */
(function () {
  const KEY = "rm_theme", sys = window.matchMedia("(prefers-color-scheme: dark)");
  const saved = () => { try { return localStorage.getItem(KEY); } catch (e) { return null; } };
  const apply = t => { document.documentElement.dataset.theme = t; };
  apply(saved() || (sys.matches ? "dark" : "light"));
  sys.addEventListener("change", e => { if (!saved()) apply(e.matches ? "dark" : "light"); });
  window.toggleTheme = () => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem(KEY, t); } catch (e) {}
    apply(t);
  };
  // interrupteur + logo dans l'en-tête, ajoutés quand la page est prête
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".theme-toggle").forEach(b => {
      b.innerHTML = '<svg class="sun" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1z"/></svg>'
                  + '<svg class="moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3c-4.97 0-9 4.03-9 9s4.03 9 9 9 9-4.03 9-9c0-.46-.04-.92-.1-1.36-.98 1.37-2.58 2.26-4.4 2.26-2.98 0-5.4-2.42-5.4-5.4 0-1.81.89-3.42 2.26-4.4-.44-.06-.9-.1-1.36-.1z"/></svg>'
                  + '<span class="knob"></span>';
      b.title = "Mode jour / nuit";
      b.setAttribute("aria-label", "Mode jour / nuit");
      b.onclick = window.toggleTheme;
    });
  });
})();
