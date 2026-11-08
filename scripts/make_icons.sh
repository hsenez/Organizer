#!/usr/bin/env bash
# Génère les icônes de l'application à partir d'un SVG (outil de développement ; les fichiers produits sont
# versionnés, les installeurs n'ont donc besoin ni de rsvg-convert ni d'ImageMagick).
#   scripts/make_icons.sh chemin/vers/icone.svg
# Produit dans organizer/client/assets/ : organizer.svg, organizer.png (256 px), organizer-<taille>.png
# (16 à 512, pour le thème d'icônes Linux) et organizer.ico (Windows, 16 à 256 px).
set -euo pipefail
SRC=${1:?usage : scripts/make_icons.sh icone.svg}
OUT="$(cd "$(dirname "$0")/.." && pwd)/organizer/client/assets"
mkdir -p "$OUT"
cp "$SRC" "$OUT/organizer.svg"
for size in 16 24 32 48 64 128 256 512; do
    rsvg-convert -w "$size" -h "$size" "$SRC" -o "$OUT/organizer-$size.png"
done
cp "$OUT/organizer-256.png" "$OUT/organizer.png"
magick "$OUT"/organizer-{16,24,32,48,64,128,256}.png "$OUT/organizer.ico"
echo "Icônes générées dans $OUT"
