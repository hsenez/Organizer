#!/usr/bin/env bash
# Génère les icônes de l'application (outil de développement ; les fichiers produits sont versionnés, les
# installeurs et le serveur n'ont donc besoin ni de rsvg-convert ni d'ImageMagick).
#   scripts/make_icons.sh icone.svg icone-pleine.svg
# - icone.svg : l'icône (coins arrondis transparents) ;
# - icone-pleine.svg : même dessin sur un fond carré plein, contenu dans le cercle central de 80 % (icône
#   « maskable » d'Android, icône d'écran d'accueil d'iOS qui n'accepte pas la transparence).
# Produit dans organizer/assets/ : organizer.svg, organizer-full.svg, organizer-<taille>.png (16 à 512),
# organizer.png (256), organizer.ico (Windows), organizer-maskable-512.png, apple-touch-icon.png (180).
set -euo pipefail
SRC=${1:?usage : scripts/make_icons.sh icone.svg icone-pleine.svg}
FULL=${2:?usage : scripts/make_icons.sh icone.svg icone-pleine.svg}
OUT="$(cd "$(dirname "$0")/.." && pwd)/organizer/assets"
mkdir -p "$OUT"
cp "$SRC" "$OUT/organizer.svg"
cp "$FULL" "$OUT/organizer-full.svg"
for size in 16 24 32 48 64 128 192 256 512; do
    rsvg-convert -w "$size" -h "$size" "$SRC" -o "$OUT/organizer-$size.png"
done
cp "$OUT/organizer-256.png" "$OUT/organizer.png"
magick "$OUT"/organizer-{16,24,32,48,64,128,256}.png "$OUT/organizer.ico"
rsvg-convert -w 512 -h 512 "$FULL" -o "$OUT/organizer-maskable-512.png"
rsvg-convert -w 180 -h 180 "$FULL" -o "$OUT/apple-touch-icon.png"
echo "Icônes générées dans $OUT"
