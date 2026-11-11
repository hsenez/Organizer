// Éditeur markdown « façon Obsidian » (CodeMirror 6, fourni par NiceGUI sous le nom « nicegui-codemirror »).
//
// - Rendu en direct : titres, gras, italique, barré, code, citations, liens… La syntaxe markdown s'efface
//   quand le curseur n'est pas dessus, et réapparaît dès qu'on y revient pour l'éditer.
// - Listes : Entrée continue la liste (puces, numéros renumérotés, cases à cocher) ; Entrée sur un élément
//   vide termine la liste ; Tab / Maj+Tab indente ; Retour arrière en début d'élément retire la puce.
// - Cases à cocher cliquables ; liens, adresses web et chemins de fichiers ouverts d'un clic (Ctrl+clic si le
//   curseur est déjà dans le lien pour l'éditer ; le double-clic fonctionne aussi). Événement « open-link »
//   envoyé au serveur, qui décide quoi faire selon la plateforme.
// - Liens internes [texte](task:12) / (event:8) / (note:5) : pastille cliquable (emoji + texte, ou titre actuel
//   si le texte est vide) ; prop « refs » = ce que le serveur sait de chaque lien (titre, inaccessible).
//   « [[ » tapé (prop refPicker) émet « ref-request » : le serveur ouvre la recherche, puis insertRef().
// - Lecture seule (prop readonly), barre de boutons (méthode format()), tri des cases (prop sortChecks :
//   cocher envoie la case en tête des cochées, décocher tout en haut ; non cochées au-dessus).
import * as CM from "nicegui-codemirror";

// Chemins de fichiers locaux écrits tels quels dans le texte : /home/…, ~/…, C:\…
const PATH_RE = /(^|[\s(])((?:~\/|\/)[^\s()]+|[A-Za-z]:\\[^\s()]*)/g;
// Cible d'un lien interne (identique à rules.parse_ref côté Python).
const REF_RE = /^(task|event|note):(\d+)$/;
const REF_EMOJI = { task: "📋", event: "📅", note: "📝" };
// Relance du rendu quand les props refs / readonly changent (sans modifier le texte).
const redraw = CM.StateEffect.define();

class CheckboxWidget extends CM.WidgetType {
  constructor(checked, pos, readOnly) {
    super();
    this.checked = checked;
    this.pos = pos; // position du caractère entre les crochets (« » ou « x »)
    this.readOnly = readOnly;
  }
  eq(other) {
    return other.checked === this.checked && other.pos === this.pos && other.readOnly === this.readOnly;
  }
  toDOM(view) {
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = this.checked;
    box.disabled = this.readOnly;
    box.className = "cm-md-checkbox";
    box.title = this.readOnly ? "Lecture seule" : this.checked ? "Fait — cliquer pour décocher" : "À faire — cliquer pour cocher";
    box.addEventListener("mousedown", (event) => {
      event.preventDefault();
      if (view.state.readOnly) return;
      const sorted = view.organizer?.sortChecks ? sortedChecklist(view.state, this.pos, !this.checked) : null;
      view.dispatch(sorted || { changes: { from: this.pos, to: this.pos + 1, insert: this.checked ? " " : "x" } });
    });
    return box;
  }
  ignoreEvent() {
    return true;
  }
}

// Lien interne rendu en pastille : « 📋 Acheter du pain ». Inaccessible (supprimé, pas visible) : 🔒 barré.
class RefWidget extends CM.WidgetType {
  constructor(target, text, info) {
    super();
    this.target = target;
    this.text = text;
    this.info = info || null;
  }
  eq(other) {
    return (
      other.target === this.target &&
      other.text === this.text &&
      JSON.stringify(other.info) === JSON.stringify(this.info)
    );
  }
  toDOM() {
    const kind = REF_RE.exec(this.target)[1];
    const info = this.info;
    const missing = info && !info.available;
    const chip = document.createElement("span");
    chip.className = `cm-md-ref cm-md-ref-${kind}` + (missing ? " cm-md-ref-missing" : "");
    chip.dataset.target = this.target;
    chip.dataset.kind = "ref";
    const emoji = missing ? "🔒" : info?.emoji || REF_EMOJI[kind];
    const label = this.text || info?.title || (missing ? "inaccessible" : this.target);
    chip.textContent = `${emoji} ${label}`;
    const current = info?.title && info.title !== label ? `\nTitre actuel : ${info.title}` : "";
    chip.title = missing
      ? "Élément supprimé, ou que vous ne pouvez pas voir"
      : `${{ task: "Tâche", event: "Événement", note: "Note" }[kind]}${current}\nCliquer pour ouvrir`;
    return chip;
  }
  ignoreEvent() {
    return false; // le clic arrive au gestionnaire « mousedown » de l'éditeur (ouverture)
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
            if (REF_RE.test(target)) {
              const text = doc.sliceString(marks[0].to, marks[1].from).trim();
              const info = view.organizer?.refs?.[target];
              if (!touches(node.from, node.to)) {
                add(CM.Decoration.replace({ widget: new RefWidget(target, text, info) }), node.from, node.to);
              } else if (marks[0].to < marks[1].from) {
                add(linkMark(target, "ref", "cm-md-link cm-md-ref-edit"), marks[0].to, marks[1].from);
              }
              break;
            }
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
                add(
                  CM.Decoration.replace({ widget: new CheckboxWidget(checked, marker.from + 1, state.readOnly) }),
                  start,
                  end,
                );
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
        update.transactions.some((tr) => tr.effects.some((e) => e.is(redraw))) ||
        CM.syntaxTree(update.startState) !== CM.syntaxTree(update.state)
      ) {
        this.decorations = buildDecorations(update.view);
      }
    }
  },
  { decorations: (plugin) => plugin.decorations },
);

// Tri d'une liste de cases au moment où l'on coche / décoche celle dont la marque est en « markerPos » :
// non cochées d'abord, puis cochées, chacune dans son ordre ; la case cochée passe en tête des cochées, la
// case décochée tout en haut. Les sous-éléments suivent leur élément. Seulement si tous les éléments de ce
// niveau sont des cases (sinon : simple bascule, rien ne bouge). Une seule transaction (un seul Ctrl+Z).
function sortedChecklist(state, markerPos, nowChecked) {
  const doc = state.doc;
  let item = null;
  for (let node = CM.syntaxTree(state).resolveInner(markerPos, 1); node; node = node.parent) {
    if (node.name === "ListItem") {
      item = node;
      break;
    }
  }
  const list = item?.parent;
  if (!list) return null;
  const items = list.getChildren("ListItem");
  const blocks = [];
  for (const node of items) {
    const marker = node.getChild("Task")?.getChild("TaskMarker");
    if (!marker) return null;
    blocks.push({ node, marker, checked: /x/i.test(doc.sliceString(marker.from, marker.to)) });
  }
  if (blocks.length < 2) return null;
  for (const block of blocks) block.start = doc.lineAt(block.node.from).from;
  for (let i = 0; i < blocks.length; i++) {
    blocks[i].end =
      i + 1 < blocks.length
        ? doc.lineAt(blocks[i + 1].node.from).from - 1
        : doc.lineAt(Math.max(blocks[i].node.from, blocks[i].node.to - 1)).to;
    blocks[i].text = doc.sliceString(blocks[i].start, blocks[i].end);
  }
  const index = blocks.findIndex((b) => b.marker.from < markerPos && markerPos < b.marker.to);
  if (index < 0) return null;
  const toggled = blocks[index];
  const offset = markerPos - toggled.start;
  toggled.text = toggled.text.slice(0, offset) + (nowChecked ? "x" : " ") + toggled.text.slice(offset + 1);
  const others = blocks.filter((_, i) => i !== index);
  const unchecked = others.filter((b) => !b.checked).map((b) => b.text);
  const checked = others.filter((b) => b.checked).map((b) => b.text);
  let texts = nowChecked ? [...unchecked, toggled.text, ...checked] : [toggled.text, ...unchecked, ...checked];
  if (list.name === "OrderedList") {
    const first = /^\s*(\d+)/.exec(blocks[0].text);
    let number = first ? Number(first[1]) : 1;
    texts = texts.map((text) => text.replace(/^(\s*)\d+/, (_, indent) => `${indent}${number++}`));
  }
  const from = blocks[0].start;
  const to = blocks[blocks.length - 1].end;
  return { changes: { from, to, insert: texts.join("\n") }, userEvent: "input.check" };
}

// Préfixes de ligne de la barre de boutons (un clic de plus retire le préfixe).
const LINE_PREFIX = { h1: "# ", h2: "## ", h3: "### ", bullet: "- ", ordered: "1. ", task: "- [ ] ", quote: "> " };
const ANY_PREFIX = /^(\s*)(#{1,6} |> |[-*+] \[[ xX]\] |[-*+] |\d+[.)] )?/;
const INLINE_MARK = { bold: "**", italic: "*", strike: "~~", code: "`" };

function formatLines(view, kind) {
  const { state } = view;
  const wanted = LINE_PREFIX[kind];
  const lines = [];
  for (const range of state.selection.ranges) {
    for (let pos = range.from; pos <= range.to; ) {
      const line = state.doc.lineAt(pos);
      if (!lines.some((l) => l.number === line.number)) lines.push(line);
      pos = line.to + 1;
    }
  }
  const same = (line) => {
    const prefix = ANY_PREFIX.exec(line.text)[2] || "";
    return kind === "ordered" ? /^\d+[.)] $/.test(prefix) : prefix.replace(/\[[xX]\]/, "[ ]") === wanted;
  };
  const remove = lines.every(same); // toutes déjà au bon format : on retire
  let number = 1;
  const edits = lines.map((line) => {
    const match = ANY_PREFIX.exec(line.text);
    const indent = match[1];
    const prefix = match[2] || "";
    // Le préfixe se termine toujours par une espace (« - », « 1. », « - [ ] » suivis d'une espace).
    const insert = remove ? "" : kind === "ordered" ? `${number++}. ` : wanted;
    return { line, from: line.from + indent.length, to: line.from + indent.length + prefix.length, insert };
  });
  const changes = state.changes(edits.map(({ from, to, insert }) => ({ from, to, insert })));
  // Curseur : après le nouveau préfixe s'il était dedans ou avant (ligne vide, début de ligne) ; sinon il
  // garde sa place dans le texte.
  const selection = CM.EditorSelection.create(
    state.selection.ranges.map((range) => {
      const place = (pos) => {
        const edit = edits.find((e) => e.line.from <= pos && pos <= e.line.to);
        return edit && pos <= edit.to ? changes.mapPos(edit.to, 1) : changes.mapPos(pos, 1);
      };
      return CM.EditorSelection.range(place(range.anchor), place(range.head));
    }),
    state.selection.mainIndex,
  );
  view.dispatch({ changes, selection, userEvent: "input.format" });
}

function formatInline(view, kind) {
  const mark = INLINE_MARK[kind];
  const { state } = view;
  view.dispatch(
    state.changeByRange((range) => {
      const before = state.doc.sliceString(range.from - mark.length, range.from);
      const after = state.doc.sliceString(range.to, range.to + mark.length);
      if (before === mark && after === mark && range.from - mark.length >= 0) {
        return {
          changes: [
            { from: range.from - mark.length, to: range.from },
            { from: range.to, to: range.to + mark.length },
          ],
          range: CM.EditorSelection.range(range.from - mark.length, range.to - mark.length),
        };
      }
      return {
        changes: [
          { from: range.from, insert: mark },
          { from: range.to, insert: mark },
        ],
        range: CM.EditorSelection.range(range.from + mark.length, range.to + mark.length),
      };
    }),
    { userEvent: "input.format" },
  );
}

function formatLink(view) {
  const { state } = view;
  view.dispatch(
    state.changeByRange((range) => {
      const text = state.doc.sliceString(range.from, range.to);
      const isUrl = /^(https?:\/\/|www\.)\S+$/.test(text);
      const insert = isUrl ? `[](${text})` : `[${text || "texte"}](https://)`;
      // Curseur : dans le texte pour une adresse sélectionnée, sinon dans l'adresse.
      const cursor = isUrl ? range.from + 1 : range.from + insert.length - 1;
      const anchor = isUrl ? cursor : text ? cursor - "https://".length : range.from + 1;
      const head = isUrl ? cursor : text ? cursor : range.from + 1 + "texte".length;
      return { changes: { from: range.from, to: range.to, insert }, range: CM.EditorSelection.range(anchor, head) };
    }),
    { userEvent: "input.format" },
  );
}

// Adresse d'Organizer collée (identique à organizer/links.py : from_url) → lien interne « note:5 ».
const PAGE_PARAMS = { "/tasks": ["task", "task"], "/calendar": ["event", "event"], "/notes": ["note", "note"] };
function refFromUrl(text) {
  text = text.trim();
  const scheme = /^organizer:(?:\/\/+)?(task|event|note)[/:](\d+)\/?$/i.exec(text);
  if (scheme) return `${scheme[1].toLowerCase()}:${scheme[2]}`;
  if (!/^(https?:\/\/[^\s/]+)?\/\S*$/.test(text)) return null;
  let url;
  try {
    url = new URL(text, "http://organizer.invalid");
  } catch (e) {
    return null;
  }
  const open = /^\/open\/(task|event|note)\/(\d+)\/?$/.exec(url.pathname);
  if (open) return `${open[1]}:${open[2]}`;
  const page = PAGE_PARAMS[url.pathname.replace(/\/$/, "")];
  const keys = [...url.searchParams.keys()];
  if (page && keys.length === 1 && keys[0] === page[1] && /^\d+$/.test(url.searchParams.get(page[1]))) {
    return `${page[0]}:${url.searchParams.get(page[1])}`;
  }
  return null;
}

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
    readonly: Boolean,
    sortChecks: Boolean,
    refPicker: Boolean,
    refs: Object,
  },
  watch: {
    readonly(value) {
      if (!this.view) return;
      this.view.dispatch({ effects: [this.editable.reconfigure(this.editableExtension(value)), redraw.of(null)] });
    },
    sortChecks(value) {
      if (this.view) this.view.organizer.sortChecks = value;
    },
    refs(value) {
      if (!this.view) return;
      this.view.organizer.refs = value || {};
      this.view.dispatch({ effects: redraw.of(null) });
    },
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
      // Lien d'Organizer collé (copié avec « 🔗 Copier le lien », ou adresse d'une page) → lien interne : la
      // pastille affiche le titre actuel.
      paste: (event, view) => {
        if (!this.refPicker || view.state.readOnly) return false;
        const ref = refFromUrl(event.clipboardData?.getData("text/plain") || "");
        if (!ref) return false;
        event.preventDefault();
        const insert = `[](${ref})`;
        const { from, to } = view.state.selection.main;
        view.dispatch({ changes: { from, to, insert }, selection: { anchor: from + insert.length }, userEvent: "input.paste" });
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
      if (update.docChanged && this.refPicker && update.transactions.some((tr) => tr.isUserEvent("input.type"))) {
        const pos = update.state.selection.main.head;
        const before = update.state.doc.sliceString(Math.max(0, pos - 3), pos);
        if (before.endsWith("[[") && !before.endsWith("[[[")) this.$emit("ref-request");
      }
      if (update.focusChanged && !update.view.hasFocus) {
        this.flush();
        this.$emit("blur");
      }
    });
    this.editable = new CM.Compartment();
    this.view = new CM.EditorView({
      parent: this.$el,
      doc: this.value ?? "",
      extensions: [
        this.editable.of(this.editableExtension(this.readonly)),
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
    this.view.organizer = { refs: this.refs || {}, sortChecks: this.sortChecks };
    this.view.dispatch({ effects: redraw.of(null) }); // premier rendu avec les titres des liens internes
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
      this.flush(); // le texte part avant : le serveur peut l'enregistrer avant d'ouvrir autre chose
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
    editableExtension(readonly) {
      return [CM.EditorState.readOnly.of(!!readonly), CM.EditorView.editable.of(!readonly)];
    },
    // Barre de boutons : gras, italique, barré, code, lien ; titres, puces, numéros, cases, citation.
    format(kind) {
      const view = this.view;
      if (!view || view.state.readOnly) return;
      if (kind in INLINE_MARK) formatInline(view, kind);
      else if (kind in LINE_PREFIX) formatLines(view, kind);
      else if (kind === "link") formatLink(view);
      else if (kind === "hr") {
        const line = view.state.doc.lineAt(view.state.selection.main.head);
        const insert = (line.length ? "\n" : "") + "---\n";
        view.dispatch({ changes: { from: line.to, insert }, selection: { anchor: line.to + insert.length } });
      }
      view.focus();
    },
    // Insère un lien interne au curseur (en remplaçant le « [[ » qui a ouvert la recherche).
    insertRef(text) {
      const view = this.view;
      if (!view || view.state.readOnly) return;
      const { from, to } = view.state.selection.main;
      const start = from >= 2 && view.state.doc.sliceString(from - 2, from) === "[[" ? from - 2 : from;
      const end = view.state.doc.sliceString(to, to + 2) === "]]" ? to + 2 : to;
      view.dispatch({ changes: { from: start, to: end, insert: text }, selection: { anchor: start + text.length } });
      view.focus();
      this.flush();
    },
  },
};
