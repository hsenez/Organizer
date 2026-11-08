// Dépôt de fichiers venus du système (gestionnaire de fichiers, bureau) sur la page. Deux sortes de cibles :
//
// - une zone data-file-drop="<id d'un ui.upload>" (l'éditeur de tâche ouvert, voir file_drop.py) : les
//   fichiers sont confiés à ce composant d'envoi (méthode addFiles de QUploader), qui les envoie aussitôt ;
// - une carte ou une ligne de tâche (data-dnd-task, posé par draggable()) : les fichiers sont gardés ici, la
//   tâche visée est annoncée au serveur (événement « card-files »), qui répond par flush() ; ils partent
//   alors par le composant d'envoi de la page (prop upload_id), à destination de cette tâche.
//
// Si le moteur ne fournit que les adresses file:// des fichiers (sans leur contenu), elles sont envoyées au
// serveur (événement « paths ») : le client bureau, qui tourne sur le même poste, lit les fichiers lui-même.
//
// Partout ailleurs, le dépôt est neutralisé (sinon le navigateur, ou la fenêtre du client bureau, ouvrirait
// le fichier à la place de l'application) et signalé (événement « missed », avec de quoi diagnostiquer).
//
// Indépendant de dnd.js (glisser des cartes), qui passe par les événements pointer / touch et non par le
// glisser-déposer HTML (dragover / drop) qu'utilisent les fichiers.
export default {
  template: "<span><slot></slot></span>",
  props: { upload_id: Number, web: Boolean },
  mounted() {
    this.highlighted = null;
    this.pending = [];
    // Fenêtre du client bureau sous Linux : adresses des fichiers glissés, relayées par GTK (window.py),
    // car WebKitGTK ne les donne pas à la page. Reçues pendant le survol, avant le dépôt.
    this.native = { uris: [], at: 0 };
    this.dragStart = 0;
    window.organizerNativeDrop = (uris) => {
      this.native = { uris, at: Date.now() };
      if (this.waitingNative) this.waitingNative();
    };
    const carriesFiles = (e) => {
      const types = Array.from((e.dataTransfer && e.dataTransfer.types) || []);
      // « Files » partout ; certains moteurs n'annoncent qu'une liste d'adresses de fichiers pendant le survol.
      return types.includes("Files") || types.includes("text/uri-list") || types.includes("application/x-moz-file");
    };
    const describe = (e) => {
      const el = e.target instanceof Element ? e.target : null;
      return el ? el.tagName.toLowerCase() + (el.className ? "." + String(el.className).split(" ")[0] : "") : "";
    };
    const targetOf = (e) => {
      const el = e.target instanceof Element ? e.target : null;
      if (!el) return null;
      const zone = el.closest("[data-file-drop]");
      if (zone) return { el: zone, kind: "zone" };
      const card = el.closest("[data-dnd-task]");
      if (card) return { el: card, kind: "card" };
      return null;
    };
    this.onOver = (e) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      if (!this.dragStart) this.dragStart = Date.now();
      const target = targetOf(e);
      e.dataTransfer.dropEffect = target ? "copy" : "none";
      this.highlight(target);
    };
    this.onLeave = (e) => {
      // Sortie de la fenêtre (aucun élément d'arrivée) : plus de surbrillance.
      if (carriesFiles(e) && !e.relatedTarget) {
        this.highlight(null);
        this.dragStart = 0;
      }
    };
    this.onDrop = (e) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      const target = targetOf(e);
      this.highlight(null);
      const started = this.dragStart;
      this.dragStart = 0;
      const files = Array.from(e.dataTransfer.files || []);
      // Repli : certains moteurs ne donnent que les adresses file:// des fichiers (le client bureau, sur le
      // même poste, sait les lire).
      const uris = files.length
        ? []
        : (e.dataTransfer.getData("text/uri-list") || "").split(/\r?\n/).filter((u) => u.startsWith("file://"));
      const sendPaths = (list) => {
        const task = target.kind === "card" ? Number(target.el.dataset.dndTask) : null;
        this.$emit("paths", { kind: target.kind, task, uris: list });
      };
      if (target && !files.length && !uris.length && !this.$props.web) {
        // Ni contenu ni adresse : attendre (brièvement) les adresses relayées par la fenêtre native.
        const since = (started || Date.now() - 5000) - 2000;
        const fresh = () => this.native.at && this.native.at >= since;
        const finish = () => {
          clearTimeout(timer);
          this.waitingNative = null;
          if (fresh()) {
            sendPaths(this.native.uris);
            this.native = { uris: [], at: 0 };
          } else this.$emit("missed", { target: describe(e), types: Array.from(e.dataTransfer.types || []), files: 0, zone: true });
        };
        const timer = setTimeout(finish, fresh() ? 0 : 800);
        this.waitingNative = finish;
        return;
      }
      if (target && uris.length) {
        sendPaths(uris);
      } else if (target && files.length && target.kind === "zone") {
        runMethod(Number(target.el.dataset.fileDrop), "addFiles", [files]);
      } else if (target && files.length && target.kind === "card") {
        this.pending = files;
        this.$emit("card-files", { task: Number(target.el.dataset.dndTask), names: files.map((f) => f.name) });
      } else {
        this.$emit("missed", {
          target: describe(e),
          types: Array.from(e.dataTransfer.types || []),
          files: files.length,
          zone: !!target,
        });
      }
    };
    this.onEnd = () => this.highlight(null);
    document.addEventListener("dragenter", this.onOver);
    document.addEventListener("dragover", this.onOver);
    document.addEventListener("dragleave", this.onLeave);
    document.addEventListener("drop", this.onDrop);
    document.addEventListener("dragend", this.onEnd);
  },
  unmounted() {
    document.removeEventListener("dragenter", this.onOver);
    document.removeEventListener("dragover", this.onOver);
    document.removeEventListener("dragleave", this.onLeave);
    document.removeEventListener("drop", this.onDrop);
    document.removeEventListener("dragend", this.onEnd);
    if (window.organizerNativeDrop) delete window.organizerNativeDrop;
  },
  methods: {
    highlight(target) {
      const el = target ? target.el : null;
      if (this.highlighted === el) return;
      if (this.highlighted) this.highlighted.classList.remove("file-drop-over", "file-drop-card");
      if (el) el.classList.add(target.kind === "zone" ? "file-drop-over" : "file-drop-card");
      this.highlighted = el;
    },
    // Appelé par le serveur une fois la tâche visée enregistrée : les fichiers gardés partent.
    flush() {
      const files = this.pending;
      this.pending = [];
      if (files.length) runMethod(this.upload_id, "addFiles", [files]);
    },
  },
};
