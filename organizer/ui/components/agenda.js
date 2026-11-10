// Agenda d'une journée sur deux colonnes (0-12 h, 12-24 h) : glisser un événement (même durée) ou un de ses
// bords (début / fin), par pas de `step` minutes, d'une colonne à l'autre ; double-clic ou clic droit sur
// une heure libre.
//
// Éléments (construits côté serveur, dans le slot du composant) :
// - colonnes : [data-agenda-track] (data-agenda-offset = 0 ou 720 : minute du haut de la colonne) ;
// - événements : [data-agenda-event=id] (data-start / data-end : minutes depuis minuit ; data-editable="1") ;
//   poignées : [data-agenda-handle="start" | "end"].
// Événements envoyés : « change » {id, start, end}, « create » {minute}, « slot » {minute} (clic droit).

const HALF = 720;
const DAY = 1440;

export default {
  template: `<div class="agenda"><slot></slot></div>`,
  props: { step: { type: Number, default: 15 } },
  mounted() {
    this.drag = null;
    this.suppressClick = false;
    this.onMove = (e) => this.move(e);
    this.onUp = () => this.up();
    this.$el.addEventListener("mousedown", (e) => this.down(e));
    this.$el.addEventListener("dblclick", (e) => this.create(e));
    this.$el.addEventListener("contextmenu", (e) => this.slot(e));
    this.$el.addEventListener("click", (e) => this.click(e), true);
    document.addEventListener("mousemove", this.onMove);
    document.addEventListener("mouseup", this.onUp);
  },
  unmounted() {
    document.removeEventListener("mousemove", this.onMove);
    document.removeEventListener("mouseup", this.onUp);
  },
  methods: {
    tracks() {
      return [...this.$el.querySelectorAll("[data-agenda-track]")];
    },
    // Minute de la journée sous le pointeur (colonne la plus proche horizontalement).
    minuteAt(x, y) {
      let best = null;
      let distance = Infinity;
      for (const track of this.tracks()) {
        const r = track.getBoundingClientRect();
        const d = x < r.left ? r.left - x : x > r.right ? x - r.right : 0;
        if (d < distance) [best, distance] = [{ track, r }, d];
      }
      if (!best) return 0;
      const fraction = Math.min(1, Math.max(0, (y - best.r.top) / best.r.height));
      return Number(best.track.dataset.agendaOffset) + fraction * HALF;
    },
    snap(minute) {
      return Math.max(0, Math.min(DAY, Math.round(minute / this.step) * this.step));
    },
    floor(minute) {
      return Math.max(0, Math.min(DAY - this.step, Math.floor(minute / this.step) * this.step));
    },
    down(event) {
      if (event.button !== 0) return;
      const block = event.target.closest("[data-agenda-event]");
      if (!block || block.dataset.editable !== "1") return;
      const handle = event.target.closest("[data-agenda-handle]");
      const start = Number(block.dataset.start);
      const end = Number(block.dataset.end);
      this.drag = {
        id: Number(block.dataset.agendaEvent),
        mode: handle ? handle.dataset.agendaHandle : "move",
        start,
        end,
        grab: this.minuteAt(event.clientX, event.clientY) - start,
        x: event.clientX,
        y: event.clientY,
        moved: false,
        block,
      };
      event.preventDefault(); // pas de sélection de texte
    },
    move(event) {
      const drag = this.drag;
      if (!drag) return;
      if (!drag.moved && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 4) return;
      drag.moved = true;
      document.body.classList.add("agenda-dragging");
      const minute = this.minuteAt(event.clientX, event.clientY);
      let { start, end } = drag;
      if (drag.mode === "move") {
        const length = drag.end - drag.start;
        start = Math.min(this.snap(minute - drag.grab), DAY - length);
        end = start + length;
      } else if (drag.mode === "start") {
        start = Math.min(this.snap(minute), drag.end - this.step);
      } else {
        end = Math.max(this.snap(minute), drag.start + this.step);
      }
      drag.newStart = start;
      drag.newEnd = end;
      this.preview(start, end);
    },
    up() {
      const drag = this.drag;
      this.drag = null;
      if (!drag) return;
      this.clear();
      document.body.classList.remove("agenda-dragging");
      if (!drag.moved) return;
      this.suppressClick = true; // le clic qui suit n'ouvre pas l'éditeur
      setTimeout(() => (this.suppressClick = false), 0);
      if (drag.newStart !== drag.start || drag.newEnd !== drag.end) {
        this.$emit("change", { id: drag.id, start: drag.newStart, end: drag.newEnd });
      }
    },
    click(event) {
      if (!this.suppressClick) return;
      event.stopPropagation();
      event.preventDefault();
      this.suppressClick = false;
    },
    label(minute) {
      const h = Math.floor(minute / 60) % 24;
      const m = minute % 60;
      return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
    },
    // Aperçu de la nouvelle plage dans chaque colonne qu'elle touche ; l'original est estompé.
    preview(start, end) {
      this.clear();
      this.drag.block.classList.add("agenda-source");
      let labelled = false;
      for (const track of this.tracks()) {
        const offset = Number(track.dataset.agendaOffset);
        const a = Math.max(start, offset);
        const b = Math.min(end, offset + HALF);
        if (a >= b) continue;
        const box = document.createElement("div");
        box.className = "agenda-preview";
        box.style.top = `${((a - offset) / HALF) * 100}%`;
        box.style.height = `${((b - a) / HALF) * 100}%`;
        if (!labelled) {
          box.textContent = `${this.label(start)} – ${this.label(end)}`;
          labelled = true;
        }
        track.appendChild(box);
      }
    },
    clear() {
      this.$el.querySelectorAll(".agenda-preview").forEach((el) => el.remove());
      this.$el.querySelectorAll(".agenda-source").forEach((el) => el.classList.remove("agenda-source"));
    },
    free(event) {
      return event.target.closest("[data-agenda-track]") && !event.target.closest("[data-agenda-event]");
    },
    create(event) {
      if (!this.free(event)) return;
      this.$emit("create", { minute: this.floor(this.minuteAt(event.clientX, event.clientY)) });
    },
    slot(event) {
      if (!this.free(event)) return;
      this.$emit("slot", { minute: this.floor(this.minuteAt(event.clientX, event.clientY)) });
    },
  },
};
