// Éditeur markdown « façon Obsidian » (CodeMirror 6, fourni par NiceGUI sous le nom « nicegui-codemirror »).
//
// - Rendu en direct : titres, gras, italique, barré, code, citations, liens… La syntaxe markdown s'efface
//   quand le curseur n'est pas dessus, et réapparaît dès qu'on y revient pour l'éditer.
// - Listes : Entrée continue la liste (puces, numéros renumérotés, cases à cocher) ; Entrée sur un élément
//   vide termine la liste ; Tab / Maj+Tab indente ; Retour arrière en début d'élément retire la puce.
// - Cases à cocher cliquables ; liens, adresses web et chemins de fichiers ouverts d'un clic (Ctrl+clic si le
//   curseur est déjà dans le lien pour l'éditer ; le double-clic fonctionne aussi). Événement « open-link »
//   envoyé au serveur, qui décide quoi faire selon la plateforme.
import * as CM from "nicegui-codemirror";

// Chemins de fichiers locaux écrits tels quels dans le texte : /home/…, ~/…, C:\…
const PATH_RE = /(^|[\s(])((?:~\/|\/)[^\s()]+|[A-Za-z]:\\[^\s()]*)/g;

class CheckboxWidget extends CM.WidgetType {
  constructor(checked, pos) {
    super();
    this.checked = checked;
    this.pos = pos; // position du caractère entre les crochets (« » ou « x »)
  }
  eq(other) {
    return other.checked === this.checked && other.pos === this.pos;
  }
  toDOM(view) {
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = this.checked;
    box.className = "cm-md-checkbox";
    box.title = this.checked ? "Fait — cliquer pour décocher" : "À faire — cliquer pour cocher";
    box.addEventListener("mousedown", (event) => {
      event.preventDefault();
      view.dispatch({ changes: { from: this.pos, to: this.pos + 1, insert: this.checked ? " " : "x" } });
    });
    return box;
  }
  ignoreEvent() {
    return true;
  }
}

class BulletWidget extends CM.WidgetType {
  eq() {
    return true;
  }
  toDOM() {
    const span = document.createElement("span");
    span.className = "cm-md-bullet";
    span.textContent = "•";
    return span;
  }
}

const hidden = CM.Decoration.replace({});
const bullet = CM.Decoration.replace({ widget: new BulletWidget() });
const markCache = {};
const mark = (cls) => (markCache[cls] ||= CM.Decoration.mark({ class: cls }));
// kind : « url » (adresse web reconnue par le markdown), « link » (cible d'un [texte](cible), web ou fichier),
// « path » (chemin de fichier écrit tel quel). Le serveur décide de l'action ; « url » est toujours ouvert.
const linkMark = (target, kind, cls = "cm-md-link") =>
  CM.Decoration.mark({
    class: cls,
    attributes: {
      "data-target": target,
      "data-kind": kind,
      title: `${target}\nCliquer pour ouvrir (Ctrl+clic pendant l'édition du lien)`,
    },
  });

// Étendue du lien sous un élément rendu : le lien markdown complet [texte](url) s'il y en a un.
function linkRange(view, element) {
  const from = view.posAtDOM(element);
  const to = from + element.textContent.length;
  for (let node = CM.syntaxTree(view.state).resolveInner(from, 1); node; node = node.parent) {
    if (node.name === "Link") return { from: node.from, to: node.to };
  }
  return { from, to };
}

function buildDecorations(view) {
  const { state } = view;
  const doc = state.doc;
  // Sans le focus, tout est rendu (le curseur par défaut, au début du texte, ne révèle rien).
  const ranges = view.hasFocus ? state.selection.ranges : [];
  // « touche » : la sélection est dans l'élément ou collée à lui ; « chevauche » : strictement dedans.
  const touches = (from, to) => ranges.some((r) => r.from <= to && r.to >= from);
  const overlaps = (from, to) => ranges.some((r) => r.from < to && r.to > from);
  const cursorOnLine = (pos) => {
    const line = doc.lineAt(pos);
    return touches(line.from, line.to);
  };
  const withSpace = (pos) => (doc.sliceString(pos, pos + 1) === " " ? pos + 1 : pos);
  const decorations = [];
  const add = (deco, from, to = from) => decorations.push(deco.range(from, to));
  const eachLine = (from, to, cls) => {
    for (let pos = from; pos <= to; ) {
      const line = doc.lineAt(pos);
      add(CM.Decoration.line({ class: cls }), line.from);
      pos = line.to + 1;
    }
  };
  const hideMarks = (node, markName) => {
    if (touches(node.from, node.to)) return;
    for (const child of node.node.getChildren(markName)) add(hidden, child.from, child.to);
  };

  const tree = CM.syntaxTree(state);
  for (const { from, to } of view.visibleRanges) {
    tree.iterate({
      from,
      to,
      enter: (node) => {
        const name = node.name;
        const heading = /^ATXHeading(\d)$/.exec(name);
        if (heading) {
          add(CM.Decoration.line({ class: `cm-md-h cm-md-h${heading[1]}` }), doc.lineAt(node.from).from);
          const headerMark = node.node.getChild("HeaderMark");
          if (headerMark && !cursorOnLine(node.from)) add(hidden, headerMark.from, withSpace(headerMark.to));
          return;
        }
        switch (name) {
          case "Emphasis":
            add(mark("cm-md-em"), node.from, node.to);
            hideMarks(node, "EmphasisMark");
            break;
          case "StrongEmphasis":
            add(mark("cm-md-strong"), node.from, node.to);
            hideMarks(node, "EmphasisMark");
            break;
          case "Strikethrough":
            add(mark("cm-md-strike"), node.from, node.to);
            hideMarks(node, "StrikethroughMark");
            break;
          case "InlineCode":
            add(mark("cm-md-code"), node.from, node.to);
            hideMarks(node, "CodeMark");
            break;
          case "Link": {
            const marks = node.node.getChildren("LinkMark");
            const url = node.node.getChild("URL");
            if (marks.length < 2 || !url) break;
            const target = doc.sliceString(url.from, url.to);
            if (marks[0].to < marks[1].from) add(linkMark(target, "link"), marks[0].to, marks[1].from);
            if (!touches(node.from, node.to)) {
              add(hidden, marks[0].from, marks[0].to);
              add(hidden, marks[1].from, node.to);
            }
            break;
          }
          case "URL": {
            const parent = node.node.parent?.name;
            if (parent !== "Link" && parent !== "Image") add(linkMark(doc.sliceString(node.from, node.to), "url"), node.from, node.to);
            break;
          }
          case "Blockquote":
            eachLine(node.from, node.to, "cm-md-quote");
            break;
          case "QuoteMark":
            if (!cursorOnLine(node.from)) add(hidden, node.from, withSpace(node.to));
            break;
          case "FencedCode":
          case "CodeBlock":
            eachLine(node.from, node.to, "cm-md-codeblock");
            return false; // pas de décorations à l'intérieur du code
          case "HorizontalRule":
            add(CM.Decoration.line({ class: "cm-md-hr" }), doc.lineAt(node.from).from);
            break;
          case "Task": {
            const marker = node.node.getChild("TaskMarker");
            if (marker && /x/i.test(doc.sliceString(marker.from, marker.to))) add(mark("cm-md-task-done"), marker.to, node.to);
            break;
          }
          case "ListMark": {
            const item = node.node.parent;
            const marker = item?.getChild("Task")?.getChild("TaskMarker");
            const isBullet = item?.parent?.name === "BulletList";
            if (marker) {
              // « - [ ] » → case à cocher (la puce et les crochets disparaissent)
              const start = isBullet ? node.from : marker.from;
              const end = withSpace(marker.to);
              if (!isBullet) add(mark("cm-md-olmark"), node.from, node.to);
              if (!overlaps(start, end)) {
                const checked = /x/i.test(doc.sliceString(marker.from, marker.to));
                add(CM.Decoration.replace({ widget: new CheckboxWidget(checked, marker.from + 1) }), start, end);
              }
            } else if (isBullet) {
              const end = withSpace(node.to);
              if (!overlaps(node.from, end)) add(bullet, node.from, end);
            } else {
              add(mark("cm-md-olmark"), node.from, node.to);
            }
            break;
          }
        }
      },
    });
  }

  // Chemins de fichiers écrits tels quels (hors code et hors liens déjà traités).
  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos <= to; ) {
      const line = doc.lineAt(pos);
      PATH_RE.lastIndex = 0;
      let match;
      while ((match = PATH_RE.exec(line.text))) {
        const start = line.from + match.index + match[1].length;
        const end = start + match[2].length;
        const inner = tree.resolveInner(start, 1);
        if (/Code|URL|Link/.test(inner.name) || /Code/.test(inner.parent?.name || "")) continue;
        add(linkMark(match[2], "path", "cm-md-link cm-md-path"), start, end);
      }
      pos = line.to + 1;
    }
  }
  return CM.Decoration.set(decorations, true);
}

const livePreview = CM.ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.decorations = buildDecorations(view);
    }
    update(update) {
      if (
        update.docChanged ||
        update.viewportChanged ||
        update.selectionSet ||
        update.focusChanged ||
        CM.syntaxTree(update.startState) !== CM.syntaxTree(update.state)
      ) {
        this.decorations = buildDecorations(update.view);
      }
    }
  },
  { decorations: (plugin) => plugin.decorations },
);

// Cible d'un lien à une position donnée (double-clic hors d'un élément rendu).
function targetAt(state, pos) {
  for (let node = CM.syntaxTree(state).resolveInner(pos, 1); node; node = node.parent) {
    if (node.name === "Link") {
      const url = node.getChild("URL");
      if (url) return state.doc.sliceString(url.from, url.to);
    }
    if (node.name === "URL") return state.doc.sliceString(node.from, node.to);
  }
  const line = state.doc.lineAt(pos);
  PATH_RE.lastIndex = 0;
  let match;
  while ((match = PATH_RE.exec(line.text))) {
    const start = line.from + match.index + match[1].length;
    if (pos >= start && pos <= start + match[2].length) return match[2];
  }
  return null;
}

export default {
  template: `<div class="md-editor"></div>`,
  props: {
    value: String,
    markdownModule: String,
    placeholder: String,
    loopback: Boolean,
  },
  watch: {
    value(newValue) {
      if (!this.view) return;
      const text = newValue ?? "";
      const current = this.view.state.doc.toString();
      if (text === current) return;
      this.lastEmitted = text;
      this.applyingRemote = true;
      this.view.dispatch({ changes: { from: 0, to: current.length, insert: text } });
      this.applyingRemote = false;
    },
  },
  async mounted() {
    const md = await import(this.markdownModule);
    this.lastEmitted = this.value ?? "";
    const openLink = CM.EditorView.domEventHandlers({
      // Clic simple : ouvre le lien, sauf si le curseur est déjà dedans (on l'édite) — Ctrl+clic ouvre alors.
      mousedown: (event, view) => {
        if (event.button !== 0) return false;
        const element = event.target.closest?.("[data-target]");
        if (!element) return false;
        const { from, to } = linkRange(view, element);
        const editing = view.hasFocus && view.state.selection.ranges.some((r) => r.from <= to && r.to >= from);
        if (editing && !(event.ctrlKey || event.metaKey)) return false;
        event.preventDefault();
        this.openTarget(element.dataset.target, element.dataset.kind);
        return true;
      },
      dblclick: (event, view) => {
        const element = event.target.closest?.("[data-target]");
        let target = element?.dataset.target;
        let kind = element?.dataset.kind || "link";
        if (!target) {
          const pos = view.posAtCoords({ x: event.clientX, y: event.clientY });
          if (pos != null) target = targetAt(view.state, pos);
        }
        if (!target) return false;
        event.preventDefault();
        this.openTarget(target, kind);
        return true;
      },
    });
    const sync = CM.EditorView.updateListener.of((update) => {
      if (update.docChanged && !this.applyingRemote) this.scheduleEmit();
      if (update.focusChanged && !update.view.hasFocus) {
        this.flush();
        this.$emit("blur");
      }
    });
    this.view = new CM.EditorView({
      parent: this.$el,
      doc: this.value ?? "",
      extensions: [
        CM.history(),
        CM.drawSelection(),
        CM.EditorView.lineWrapping,
        CM.indentUnit.of("    "),
        md.markdown({ base: md.markdownLanguage, addKeymap: true }),
        CM.keymap.of([...CM.defaultKeymap, ...CM.historyKeymap, CM.indentWithTab]),
        CM.placeholder(this.placeholder || ""),
        livePreview,
        openLink,
        sync,
      ],
    });
    // Les raccourcis globaux de la page (Ctrl+Z serveur, « N »…) ne doivent pas réagir à la frappe ici :
    // Ctrl+Z dans l'éditeur annule la frappe. Échap reste transmis (fermeture du panneau).
    this.$el.addEventListener("keydown", (event) => {
      if (event.key === "Escape") this.flush();
      else event.stopPropagation();
    });
  },
  beforeUnmount() {
    if (this.view) {
      this.flush();
      this.view.destroy();
    }
  },
  methods: {
    // Un double-clic produit deux clics + un double-clic : on n'ouvre qu'une fois le même lien.
    openTarget(target, kind) {
      const now = Date.now();
      if (this.lastOpen && this.lastOpen.target === target && now - this.lastOpen.time < 800) return;
      this.lastOpen = { target, time: now };
      this.$emit("open-link", { target, kind: kind || "link" });
    },
    scheduleEmit() {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.flush(), 400);
    },
    flush() {
      clearTimeout(this.timer);
      if (!this.view) return;
      const text = this.view.state.doc.toString();
      if (text === this.lastEmitted) return;
      this.lastEmitted = text;
      this.$emit("update:value", text);
    },
    focus() {
      this.view?.focus();
    },
  },
};
