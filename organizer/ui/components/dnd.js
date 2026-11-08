// Glisser-déposer des cartes de tâches, à la souris et au doigt.
//
// - Cartes : éléments portant data-dnd-task (+ data-dnd-parent, data-dnd-has-subtasks, data-dnd-title).
// - Zones de dépôt : éléments portant data-dnd-zone="clé" (data-dnd-accept="0" : dépôt refusé, avec le
//   message data-dnd-denied, sauf pour reclasser une carte de la zone ; data-dnd-ordered="1" : l'ordre des
//   cartes compte, un repère montre où la carte va s'insérer).
// - Souris : on glisse après quelques pixels ; **Ctrl** (⌘ sur Mac) au-dessus d'une carte = rattacher la
//   tâche comme sous-tâche de cette carte (surbrillance verte si possible, rouge sinon).
// - Doigt : appui long pour saisir la carte ; **rester ~1 s au-dessus d'une carte** = rattacher.
// - Près d'un bord (fenêtre, ou zone qui défile horizontalement comme le kanban), la page défile toute seule.
// Événements envoyés au serveur : « drop » {task, zone, index}, « attach » {task, parent} et « dragstate »
// {active} (début / fin du geste : le temps réel attend la fin pour rafraîchir la page).

const CARD = "[data-dnd-task]";
const ZONE = "[data-dnd-zone]";
const IGNORE = "button, a, input, textarea, select, .q-btn, .q-menu, .q-field, .cm-editor, [data-dnd-ignore]";
const MOUSE_THRESHOLD = 6;
const TOUCH_SLOP = 10;
const LONG_PRESS_MS = 350;
const TOUCH_ATTACH_MS = 900;
const EDGE = 70; // px : distance au bord à partir de laquelle on fait défiler
const MAX_SPEED = 20; // px par image
const HIGHLIGHTS = ["dnd-attach-ok", "dnd-attach-no", "dnd-zone-over", "dnd-zone-denied"];
// Les téléphones émettent des événements « touch » (on les utilise : ils permettent de bloquer le défilement) ;
// sinon (écran tactile sans événements touch, stylet), on se rabat sur les événements « pointer ».
const TOUCH_EVENTS = "ontouchstart" in window;

function infoOf(element) {
  return {
    id: Number(element.dataset.dndTask),
    parent: element.dataset.dndParent ? Number(element.dataset.dndParent) : null,
    hasSubtasks: element.dataset.dndHasSubtasks === "1",
    title: element.dataset.dndTitle || "",
  };
}

// Mêmes règles que organizer.core.rules.attach_refusal_reason (le serveur revérifie).
function refusal(child, parent) {
  if (child.id === parent.id) return "Une tâche ne peut pas être sa propre sous-tâche";
  if (parent.parent !== null) return "La cible est déjà une sous-tâche (un seul niveau)";
  if (child.hasSubtasks) return "Cette tâche a déjà des sous-tâches (un seul niveau)";
  if (child.parent === parent.id) return "C'est déjà une sous-tâche de cette tâche";
  return null;
}

export default {
  template: `<div style="display: none"></div>`,
  mounted() {
    this.pending = null;
    this.drag = null;
    this.suppressClick = false;
    this.listeners = [
      ["pointerdown", (e) => this.pointerDown(e)],
      ["pointermove", (e) => this.pointerMove(e), { passive: false }],
      ["pointerup", (e) => this.pointerUp(e)],
      ["pointercancel", (e) => e.pointerType !== "mouse" && !TOUCH_EVENTS && this.cancel()],
      ["keydown", (e) => this.keyChange(e)],
      ["keyup", (e) => this.keyChange(e)],
      ["touchstart", (e) => this.touchStart(e), { passive: true }],
      ["touchmove", (e) => this.touchMove(e), { passive: false }],
      ["touchend", (e) => this.touchEnd(e), { passive: false }],
      ["touchcancel", () => this.cancel()],
      ["contextmenu", (e) => (this.pending || this.drag) && e.preventDefault()],
      ["click", (e) => this.click(e), { capture: true }],
    ];
    for (const [type, handler, options] of this.listeners) document.addEventListener(type, handler, options);
  },
  unmounted() {
    for (const [type, handler, options] of this.listeners) document.removeEventListener(type, handler, options);
    this.cancel();
  },
  methods: {
    candidate(target) {
      if (!(target instanceof Element) || target.closest(IGNORE)) return null;
      return target.closest(CARD);
    },

    // --- aiguillage des événements « pointer » ---
    pointerDown(event) {
      if (event.pointerType === "mouse") this.mouseDown(event);
      else if (!TOUCH_EVENTS && event.isPrimary) this.pressStart(event.target, event.clientX, event.clientY);
    },
    pointerMove(event) {
      if (event.pointerType === "mouse") this.mouseMove(event);
      else if (!TOUCH_EVENTS && event.isPrimary) this.pressMove(event, event.clientX, event.clientY);
    },
    pointerUp(event) {
      if (event.pointerType === "mouse") this.mouseUp(event);
      else if (!TOUCH_EVENTS && event.isPrimary) this.pressEnd(event);
    },

    // --- souris ---
    mouseDown(event) {
      if (event.button !== 0) return;
      const card = this.candidate(event.target);
      if (card) this.pending = { card, x: event.clientX, y: event.clientY };
    },
    mouseMove(event) {
      if (this.pending && !this.drag) {
        const moved = Math.hypot(event.clientX - this.pending.x, event.clientY - this.pending.y);
        if (moved > MOUSE_THRESHOLD) this.start(this.pending.card, this.pending.x, this.pending.y, false);
      }
      if (this.drag && !this.drag.touch) {
        event.preventDefault();
        this.drag.ctrl = event.ctrlKey || event.metaKey;
        this.move(event.clientX, event.clientY);
      }
    },
    mouseUp(event) {
      if (this.drag && !this.drag.touch) this.finish(event.clientX, event.clientY);
      this.pending = null;
    },
    keyChange(event) {
      if (!this.drag || this.drag.touch) return;
      if (event.key === "Escape") return this.cancel();
      this.drag.ctrl = event.ctrlKey || event.metaKey;
      this.move(this.drag.x, this.drag.y);
    },

    // --- doigt (événements touch, ou pointer à défaut) ---
    touchStart(event) {
      if (event.touches.length !== 1) return;
      this.pressStart(event.target, event.touches[0].clientX, event.touches[0].clientY);
    },
    touchMove(event) {
      this.pressMove(event, event.touches[0].clientX, event.touches[0].clientY);
    },
    touchEnd(event) {
      this.pressEnd(event);
    },
    pressStart(target, x, y) {
      const card = this.candidate(target);
      if (!card) return;
      this.pending = { card, x, y };
      clearTimeout(this.pressTimer);
      this.pressTimer = setTimeout(() => {
        if (!this.pending) return;
        this.start(card, this.pending.x, this.pending.y, true);
        navigator.vibrate?.(15);
      }, LONG_PRESS_MS);
    },
    pressMove(event, x, y) {
      if (this.drag) {
        event.preventDefault(); // pas de défilement pendant qu'on porte une carte
        this.move(x, y);
      } else if (this.pending && Math.hypot(x - this.pending.x, y - this.pending.y) > TOUCH_SLOP) {
        clearTimeout(this.pressTimer); // le doigt bouge tout de suite : c'est un défilement
        this.pending = null;
      }
    },
    pressEnd(event) {
      clearTimeout(this.pressTimer);
      if (this.drag) {
        event.preventDefault();
        this.finish(this.drag.x, this.drag.y);
      }
      this.pending = null;
    },

    click(event) {
      if (!this.suppressClick) return;
      event.stopPropagation(); // la carte qu'on vient de lâcher ne doit pas s'ouvrir
      event.preventDefault();
      this.suppressClick = false;
    },

    // --- glisser ---
    start(card, x, y, touch) {
      this.pending = null;
      const rect = card.getBoundingClientRect();
      const ghost = card.cloneNode(true);
      ghost.classList.add("dnd-ghost");
      Object.assign(ghost.style, { left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px` });
      document.body.appendChild(ghost);
      const badge = document.createElement("div");
      badge.className = "dnd-badge";
      document.body.appendChild(badge);
      const marker = document.createElement("div");
      marker.className = "dnd-insert";
      document.body.appendChild(marker);
      card.classList.add("dnd-source");
      document.body.classList.add("dnd-active");
      this.$emit("dragstate", { active: true });
      this.drag = {
        card, ghost, badge, marker, touch, x, y,
        home: card.closest(ZONE),
        dx: x - rect.left,
        dy: y - rect.top,
        ctrl: false,
        info: infoOf(card),
        hoverCard: null,
        hoverSince: 0,
        zone: null,
        index: null,
        attach: null,
      };
      this.move(x, y);
      this.scrollFrame = requestAnimationFrame(() => this.autoScroll());
    },
    move(x, y) {
      const drag = this.drag;
      if (!drag) return;
      drag.x = x;
      drag.y = y;
      drag.ghost.style.left = `${x - drag.dx}px`;
      drag.ghost.style.top = `${y - drag.dy}px`;
      for (const cls of HIGHLIGHTS) document.querySelectorAll(`.${cls}`).forEach((el) => el.classList.remove(cls));
      drag.zone = null;
      drag.attach = null;
      drag.marker.style.display = "none";

      const under = document.elementFromPoint(x, y);
      const card = under?.closest(CARD);
      const target = card && card !== drag.card ? card : null;
      if (target !== drag.hoverCard) {
        drag.hoverCard = target;
        drag.hoverSince = Date.now();
        clearTimeout(this.attachTimer);
        if (target && drag.touch) this.attachTimer = setTimeout(() => this.move(drag.x, drag.y), TOUCH_ATTACH_MS);
      }
      const attachMode = target && (drag.touch ? Date.now() - drag.hoverSince >= TOUCH_ATTACH_MS : drag.ctrl);
      if (attachMode) {
        const parent = infoOf(target);
        const reason = refusal(drag.info, parent);
        target.classList.add(reason ? "dnd-attach-no" : "dnd-attach-ok");
        drag.attach = reason ? null : parent.id;
        return this.showBadge(reason ? `🔴 ${reason}` : `🌳 Sous-tâche de « ${parent.title} »`);
      }
      const zone = under?.closest(ZONE);
      if (zone) {
        const accepted = zone.dataset.dndAccept !== "0" || zone === drag.home;
        zone.classList.add(accepted ? "dnd-zone-over" : "dnd-zone-denied");
        if (accepted) {
          drag.zone = zone.dataset.dndZone;
          drag.index = this.indexIn(zone, y);
          if (zone.dataset.dndOrdered === "1") this.placeMarker(zone, drag.index);
        }
        if (!accepted) return this.showBadge(zone.dataset.dndDenied || "🚫 Dépôt impossible ici");
      }
      if (target) {
        return this.showBadge(
          drag.touch ? "Restez sur la carte pour en faire une sous-tâche" : "Ctrl : en faire une sous-tâche",
        );
      }
      this.showBadge("");
    },
    zoneCards(zone) {
      return [...zone.querySelectorAll(CARD)].filter((c) => c !== this.drag.card && c.closest(ZONE) === zone);
    },
    indexIn(zone, y) {
      return this.zoneCards(zone).filter((c) => {
        const r = c.getBoundingClientRect();
        return y > r.top + r.height / 2;
      }).length;
    },
    // Trait horizontal entre les cartes, là où la carte va s'insérer.
    placeMarker(zone, index) {
      const cards = this.zoneCards(zone);
      let top, left, width;
      if (!cards.length) {
        const r = zone.getBoundingClientRect();
        [top, left, width] = [r.top + 46, r.left + 10, r.width - 20];
      } else {
        const r = cards[Math.min(index, cards.length - 1)].getBoundingClientRect();
        [top, left, width] = [index < cards.length ? r.top - 5 : r.bottom + 4, r.left, r.width];
      }
      Object.assign(this.drag.marker.style, {
        display: "block", top: `${top - 2}px`, left: `${left}px`, width: `${width}px`,
      });
    },
    showBadge(text) {
      const { badge, x, y } = this.drag;
      badge.textContent = text;
      badge.style.display = text ? "block" : "none";
      badge.style.left = `${x + 16}px`;
      badge.style.top = `${y + 20}px`;
    },
    // Défilement automatique près des bords, tant que le geste dure.
    autoScroll() {
      const drag = this.drag;
      if (!drag) return;
      const speed = (d) => (d < EDGE ? Math.ceil(((EDGE - Math.max(d, 0)) / EDGE) * MAX_SPEED) : 0);
      let moved = false;
      const dy = speed(drag.y) ? -speed(drag.y) : speed(window.innerHeight - drag.y);
      if (dy) {
        const before = window.scrollY;
        window.scrollBy(0, dy);
        moved = window.scrollY !== before;
      }
      const scroller = this.horizontalScroller(drag.x, drag.y);
      if (scroller) {
        const r = scroller.getBoundingClientRect();
        const dx = speed(drag.x - r.left) ? -speed(drag.x - r.left) : speed(r.right - drag.x);
        if (dx) {
          const before = scroller.scrollLeft;
          scroller.scrollLeft += dx;
          moved = moved || scroller.scrollLeft !== before;
        }
      }
      if (moved) this.move(drag.x, drag.y); // la zone sous le doigt a changé
      this.scrollFrame = requestAnimationFrame(() => this.autoScroll());
    },
    horizontalScroller(x, y) {
      let el = document.elementFromPoint(x, y);
      while (el && el !== document.body) {
        const style = getComputedStyle(el);
        if (/(auto|scroll)/.test(style.overflowX) && el.scrollWidth > el.clientWidth) return el;
        el = el.parentElement;
      }
      return null;
    },
    cleanup() {
      clearTimeout(this.attachTimer);
      cancelAnimationFrame(this.scrollFrame);
      if (!this.drag) return;
      this.drag.ghost.remove();
      this.drag.badge.remove();
      this.drag.marker.remove();
      this.drag.card.classList.remove("dnd-source");
      for (const cls of HIGHLIGHTS) document.querySelectorAll(`.${cls}`).forEach((el) => el.classList.remove(cls));
      document.body.classList.remove("dnd-active");
      this.$emit("dragstate", { active: false });
    },
    finish(x, y) {
      this.move(x, y);
      const drag = this.drag;
      this.cleanup();
      this.drag = null;
      this.suppressClick = true;
      setTimeout(() => (this.suppressClick = false), 0);
      if (drag.attach !== null) this.$emit("attach", { task: drag.info.id, parent: drag.attach });
      else if (drag.zone !== null) this.$emit("drop", { task: drag.info.id, zone: drag.zone, index: drag.index });
    },
    cancel() {
      clearTimeout(this.pressTimer);
      this.cleanup();
      this.drag = null;
      this.pending = null;
    },
  },
};
