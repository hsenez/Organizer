// Sélection de plusieurs jours du calendrier à la souris : clic dans une case puis glisser jusqu'à une autre.
//
// - Cases : éléments portant data-cal-day="AAAA-MM-JJ". Une pastille (data-dnd-task), un bouton ou une
//   poignée ne démarrent pas de sélection (ils ont leur propre geste).
// - La plage est surlignée tout de suite (classe calendar-selected), puis envoyée au serveur : événement
//   « range » {start, end} (dans l'ordre). Le clic qui termine le geste est absorbé (sinon il resélectionnerait
//   une seule case). Un simple clic reste géré par la case elle-même.

const IGNORE = "[data-dnd-task], button, a, input, .q-btn, [data-resize-handle], [data-dnd-ignore]";

export default {
  template: `<div style="display: none"></div>`,
  mounted() {
    this.start = null;
    this.end = null;
    this.moved = false;
    this.listeners = [
      ["mousedown", (e) => this.down(e), false],
      ["mouseover", (e) => this.over(e), false],
      ["mouseup", () => this.up(), false],
      ["click", (e) => this.click(e), true],
    ];
    for (const [type, handler, capture] of this.listeners) document.addEventListener(type, handler, capture);
  },
  unmounted() {
    for (const [type, handler, capture] of this.listeners) document.removeEventListener(type, handler, capture);
  },
  methods: {
    cell(target) {
      return target instanceof Element ? target.closest("[data-cal-day]") : null;
    },
    down(event) {
      if (event.button !== 0 || !(event.target instanceof Element) || event.target.closest(IGNORE)) return;
      const cell = this.cell(event.target);
      if (!cell) return;
      this.start = this.end = cell.dataset.calDay;
      this.moved = false;
    },
    over(event) {
      if (!this.start) return;
      const cell = this.cell(event.target);
      if (!cell || cell.dataset.calDay === this.end) return;
      this.end = cell.dataset.calDay;
      this.moved = true;
      this.paint();
    },
    up() {
      if (!this.start) return;
      if (this.moved) {
        const [start, end] = [this.start, this.end].sort();
        this.$emit("range", { start, end });
        this.suppressClick = true;
        setTimeout(() => (this.suppressClick = false), 0);
      }
      this.start = null;
    },
    click(event) {
      if (!this.suppressClick) return;
      event.stopPropagation();
      event.preventDefault();
      this.suppressClick = false;
    },
    paint() {
      const [a, b] = [this.start, this.end].sort();
      for (const cell of document.querySelectorAll("[data-cal-day]")) {
        const day = cell.dataset.calDay;
        cell.classList.toggle("calendar-selected", day >= a && day <= b);
      }
    },
  },
};
