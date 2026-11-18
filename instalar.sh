#!/bin/bash
# Instala (ou atualiza) o Clipper AO VIVO no Mac/Linux com um comando só:
#   curl -fsSL https://raw.githubusercontent.com/jamalkkj/clipper-aovivo/main/instalar.sh | bash
set -e
PY="$HOME/clipper-gta6/ambiente/bin/python"
if [ ! -x "$PY" ]; then
  echo "Primeiro instalando o Clipper do GTA 6 (é a base do modo ao vivo)…"
  curl -fsSL https://raw.githubusercontent.com/davixavier-coder/skill-clips/main/instalar.sh | bash
fi
DEST="$HOME/.claude/skills/clipper-aovivo"
echo "Baixando o Clipper AO VIVO pra $DEST…"
mkdir -p "$DEST"
curl -fsSL https://github.com/jamalkkj/clipper-aovivo/archive/refs/heads/main.tar.gz \
  | tar -xz --strip-components=1 -C "$DEST"
"$PY" "$DEST/scripts/aovivo.py" instalar
