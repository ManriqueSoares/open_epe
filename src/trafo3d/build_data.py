r"""Gera os arquivos de COORDENADAS do projeto a partir dos DXFs de origem.

Lê `data/source/*.dxf` UMA vez e grava em `data/`:
  - parte_ativa.json       (dimensões, base, centros, 3 anéis, z das bobinas)
  - parte_ativa_hull.ply   (malha do hull = só coordenadas, sem imagem)
  - bucha.json             (perfil 2D: altura, raio, envelope z/r, segmentos)

Depois disso o app roda SEM abrir DXF (sem ezdxf no runtime). Os DXFs de origem
NÃO precisam ficar no projeto — aponte para eles só na hora de regenerar.

Rodar (só quando trocar um desenho de origem):
    python -m src.trafo3d.build_data <parte_ativa.dxf> <bucha.dxf>
    # sem argumentos, procura em data/source/ (se existir)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import config, dxf_hull, buchas

SRC = os.path.join(config.DATA_DIR, "source")


def build(pa_dxf=None, b_dxf=None):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    pa_dxf = pa_dxf or os.path.join(SRC, "parte_ativa.dxf")
    b_dxf = b_dxf or os.path.join(SRC, "bucha.dxf")
    faltam = [p for p in (pa_dxf, b_dxf) if not os.path.exists(p)]
    if faltam:
        print("DXF(s) de origem não encontrado(s):", *faltam,
              "\nPasse os caminhos: python -m src.trafo3d.build_data "
              "<parte_ativa.dxf> <bucha.dxf>", sep="\n")
        return 1

    # ---- parte ativa ----
    info = dxf_hull.info_dxf(pa_dxf)              # já com 3 anéis
    hull = dxf_hull.hull_zup(pa_dxf)             # malha Z-up (metros)
    ply = "parte_ativa_hull.ply"
    hull.save(os.path.join(config.DATA_DIR, ply))
    info_out = {
        "L": info["L"], "W": info["W"], "H": info["H"], "base": info["base"],
        "centros_x": [float(c) for c in info["centros_x"]],
        "aneis": [[float(a), float(b)] for a, b in info["aneis"]],
        "z_bob": [float(z) for z in info["z_bob"]],
        "hull_ply": ply,
    }
    with open(os.path.join(config.DATA_DIR, "parte_ativa.json"), "w",
              encoding="utf-8") as f:
        json.dump(info_out, f, indent=1, ensure_ascii=False)

    # ---- bucha ----
    perf = buchas.carregar_perfil(b_dxf)
    perf_out = {
        "altura": float(perf["altura"]), "raio": float(perf["raio"]),
        "z": [float(v) for v in perf["z"]],
        "r": [float(v) for v in perf["r"]],
        "segs": [[[float(x), float(z)] for x, z in s] for s in perf["segs"]],
    }
    with open(os.path.join(config.DATA_DIR, "bucha.json"), "w",
              encoding="utf-8") as f:
        json.dump(perf_out, f, ensure_ascii=False)

    print("OK: parte_ativa.json (%d anéis), %s (%d pts), bucha.json (h=%.0f)"
          % (len(info_out["aneis"]), ply, hull.n_points, perf_out["altura"]))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("parte_ativa", nargs="?", help="DXF da parte ativa")
    ap.add_argument("bucha", nargs="?", help="DXF da bucha")
    a = ap.parse_args()
    sys.exit(build(a.parte_ativa, a.bucha))
