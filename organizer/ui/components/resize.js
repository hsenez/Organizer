// Redimensionnement horizontal d'éléments (colonnes de kanban) à la souris ou au doigt.
//
// - Élément redimensionnable : data-resize-key="clé" ; poignée (à l'intérieur) : data-resize-handle.
// - data-resize-side="left" : poignée sur le bord gauche (colonne à droite de l'écran), tirer vers la
//   gauche élargit.
// - Double-clic sur la poignée : largeur par défaut (événement envoyé avec width = null).
// Événement envoyé au serveur : « resize » {key, width}.

export default {
  template: `<div style="display: none"></div>`,
  props: { min: { type: Number, default: 180 }, max: { type: Number, default: 720 } },
  mounted() {
    this.state = null;
    this.listeners = [
      ["pointerdown", (e) => this.down(e), true],
      ["pointermove", (e) => this.move(e), false],
      ["pointerup", () => this.up(), false],
      ["pointercancel", () => this.up(), false],
      ["dblclick", (e) => this.reset(e), false],
    ];
    for (const [type, handler, capture] of this.listeners) document.addEventListener(type, handler, capture);
  },
  unmounted() {
    for (const [type, handler, capture] of this.listeners) document.removeEventListener(type, handler, capture);
  },
  methods: {
    target(event) {
      const handle = event.target instanceof Element ? event.target.closest("[data-resize-handle]") : null;
      return handle ? handle.closest("[data-resize-key]") : null;
    },
    down(event) {
      const box = this.target(event);
      if (!box || event.button > 0) return;
      event.preventDefault();
      event.stopPropagation(); // ni glisser-déposer, ni sélection de texte
      const sign = box.dataset.resizeSide === "left" ? -1 : 1;
      this.state = { box, sign, x: event.clientX, width: box.getBoundingClientRect().width };
      document.body.classList.add("resizing");
    },
    move(event) {
      if (!this.state) return;
      event.preventDefault();
      const width = Math.round(Math.min(this.max, Math.max(this.min, this.state.width + this.state.sign * (event.clientX - this.state.x))));
      this.state.box.style.width = `${width}px`;
    },
    up() {
      if (!this.state) return;
      const { box } = this.state;
      this.state = null;
      document.body.classList.remove("resizing");
      this.$emit("resize", { key: box.dataset.resizeKey, width: Math.round(box.getBoundingClientRect().width) });
    },
    reset(event) {
      const box = this.target(event);
      if (!box) return;
      box.style.width = "";
      this.$emit("resize", { key: box.dataset.resizeKey, width: null });
    },
  },
};
