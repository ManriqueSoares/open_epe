"""Configuração: fontes fixas de medidas (DXFs do projeto).

Os DXFs ficam em `data/` dentro do projeto — o app SEMPRE lê deles, sem
seleção manual. Para trocar o modelo, substitua o arquivo em `data/` (mantendo
o nome) ou edite os caminhos abaixo.
"""
from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(_ROOT, "data")

# Fontes de medidas = arquivos de COORDENADAS gerados por build_data.py
# (JSON + PLY). O runtime NÃO abre DXF. Para regenerar após trocar um DXF de
# origem em data/source/, rode:  python -m src.trafo3d.build_data
DXF_PARTE_ATIVA = os.path.join(DATA_DIR, "parte_ativa.json")
DXF_BUCHA = os.path.join(DATA_DIR, "bucha.json")
