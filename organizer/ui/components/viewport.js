// Clavier virtuel des téléphones : suit la partie visible de la page (window.visualViewport).
//
// - Variables CSS sur <html> : --vv-top (haut de la partie visible dans la page), --vv-height (sa hauteur).
//   Sous Android (interactive-widget=resizes-content), la page rapetisse avec le clavier : --vv-top reste à 0.
//   Sous iOS, la page garde sa taille et Safari la fait glisser sous la partie visible : un élément
//   « position: fixed » qui doit rester au-dessus du clavier se place avec ces variables.
// - Classe « keyboard-open » sur <body> : écran tactile + saisie en cours + hauteur visible réduite.
// - Mode écriture : si le champ actif est dans un élément [data-writing] (texte d'une note), cet élément
//   reçoit « writing-active » et <body> « writing » (CSS : l'élément occupe toute la partie visible).
// - Événement « organizer-viewport » (window) à chaque changement d'état : l'éditeur markdown ramène alors
//   son curseur en vue.
(() => {
  if (window.organizerViewport) return;
  const root = document.documentElement;
  const vv = window.visualViewport;
  const touch = window.matchMedia("(pointer: coarse)");
  const TEXT_TYPES = /^(text|search|email|url|tel|password|number|date|time|datetime-local|month|week)$/;
  const KEYBOARD_MIN = 120; // en dessous : barre d'adresse qui se replie, pas un clavier
  let base = 0; // hauteur visible sans clavier (orientation courante)
  let orientation = null;
  let frame = 0;
  let state = { keyboard: false, writer: null };

  function typing(element) {
    if (!element) return false;
    if (element.isContentEditable) return true;
    if (element.tagName === "TEXTAREA") return !element.readOnly;
    if (element.tagName === "INPUT") return TEXT_TYPES.test(element.type || "text") && !element.readOnly;
    return false;
  }

  function update() {
    frame = 0;
    const height = vv ? vv.height : window.innerHeight;
    const top = vv ? vv.offsetTop : 0;
    const visible = height * (vv ? vv.scale : 1); // hauteur à l'échelle 1 (zoom à deux doigts ignoré)
    const turned = (screen.orientation && screen.orientation.type) || String(window.orientation);
    if (turned !== orientation) {
      orientation = turned;
      base = 0;
    }
    const active = document.activeElement;
    const isTyping = typing(active);
    base = isTyping ? Math.max(base, visible) : visible;
    const keyboard = touch.matches && isTyping && base - visible > KEYBOARD_MIN;
    root.style.setProperty("--vv-top", `${Math.round(top)}px`);
    root.style.setProperty("--vv-height", `${Math.round(height)}px`);
    const writer = keyboard ? active.closest("[data-writing]") : null;
    if (keyboard === state.keyboard && writer === state.writer) return;
    document.body.classList.toggle("keyboard-open", keyboard);
    document.body.classList.toggle("writing", !!writer);
    if (state.writer && state.writer !== writer) state.writer.classList.remove("writing-active");
    if (writer) writer.classList.add("writing-active");
    state = { keyboard, writer };
    window.dispatchEvent(new CustomEvent("organizer-viewport", { detail: { keyboard, writing: !!writer } }));
  }

  function schedule() {
    if (!frame) frame = requestAnimationFrame(update);
  }

  if (vv) {
    vv.addEventListener("resize", schedule);
    vv.addEventListener("scroll", schedule);
  }
  window.addEventListener("resize", schedule);
  // focusout : l'élément suivant n'a pas encore le focus pendant l'événement ; la frame d'après, si.
  document.addEventListener("focusin", schedule);
  document.addEventListener("focusout", schedule);
  window.organizerViewport = { update, state: () => state };
  schedule();
})();
