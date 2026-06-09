#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/4] Creando venv..."
python3 -m venv .venv
source .venv/bin/activate

echo "[2/4] Instalando dependencias..."
pip install --upgrade pip setuptools wheel -q
pip install -r requirements.txt -q
pip install -e . -q

echo "[3/4] Verificando CLI..."
fortisiem-sim --list-events | head -5
fortisiem-sim --validate --config scenarios/ransomware-tabletop.yml

echo "[4/4] Listo."
echo ""
echo "  source .venv/bin/activate"
echo "  fortisiem-sim --config scenarios/ransomware-tabletop.yml --phase recon_and_access"
echo ""
echo "  Envío real (sudo + ruta completa):"
echo "  sudo .venv/bin/fortisiem-sim --config scenarios/ransomware-tabletop.yml --phase recon_and_access --send --no-spoof"
