#!/usr/bin/env bash
# Instala las skills de este repo como symlinks en el directorio de skills del agente.
#
# Uso:
#   bash scripts/install.sh [--dry-run] [--force] [--target DIR]
#
#   --target DIR  destino (default: ~/.claude/skills; ~/.agents/skills para Codex/Gemini/Copilot)
#   --dry-run     muestra qué haría sin tocar nada
#   --force       si existe un directorio real (no symlink) con el mismo nombre, lo mueve a
#                 <target>/.backup-<timestamp>/ antes de enlazar
#
# Los runtimes descubren skills en un namespace plano (<target>/<name>/SKILL.md), por eso
# cada skills/<dominio>/<name>/ se enlaza como <target>/<name>. El índice
# skills/frontend/vercel-index.md se instala como <target>/vercel-index/SKILL.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${HOME}/.claude/skills"
DRY_RUN=0
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --force) FORCE=1 ;;
    --target) TARGET="$2"; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; exit 2 ;;
  esac
  shift
done

BACKUP_DIR="${TARGET}/.backup-$(date +%Y%m%d%H%M%S)"
run() { if [[ $DRY_RUN -eq 1 ]]; then echo "  [dry-run] $*"; else "$@"; fi; }

link() {
  local source="$1" dest="$2"
  if [[ -L "$dest" ]]; then
    if [[ "$(readlink -f "$dest")" == "$(readlink -f "$source")" ]]; then
      echo "=  $(basename "$dest") (ya enlazada)"
      return
    fi
    run rm "$dest"
  elif [[ -e "$dest" ]]; then
    if [[ $FORCE -eq 0 ]]; then
      echo "!  $(basename "$dest"): existe un directorio real; se omite (usar --force para respaldarlo y reemplazarlo)"
      return
    fi
    run mkdir -p "$BACKUP_DIR"
    run mv "$dest" "$BACKUP_DIR/"
    echo "   respaldado en $BACKUP_DIR/$(basename "$dest")"
  fi
  run ln -s "$source" "$dest"
  echo "+  $(basename "$dest") -> ${source#"$REPO_ROOT"/}"
}

run mkdir -p "$TARGET"

for skill_md in "$REPO_ROOT"/skills/*/*/SKILL.md; do
  skill_dir="$(dirname "$skill_md")"
  link "$skill_dir" "$TARGET/$(basename "$skill_dir")"
done

# Índice de Vercel: archivo suelto → skill de un solo archivo
index_dir="$TARGET/vercel-index"
if [[ -e "$index_dir" && ! -L "$index_dir/SKILL.md" && $FORCE -eq 0 ]]; then
  echo "!  vercel-index: existe y no es de este repo; se omite (usar --force)"
else
  run mkdir -p "$index_dir"
  link "$REPO_ROOT/skills/frontend/vercel-index.md" "$index_dir/SKILL.md"
fi

echo "Listo. Destino: $TARGET"
