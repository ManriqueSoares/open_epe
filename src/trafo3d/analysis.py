"""Análises sobre o conjunto parte ativa + tanque.

Primeira análise: INTERAÇÃO TANQUE <-> BOBINA.
Para cada ponto da superfície da bobina, calcula a distância até a parede
lateral interna mais próxima do tanque. Essa distância vira o campo de cor
(gradiente): pequeno = crítico (vermelho), grande = folgado (azul).

É um proxy geométrico da folga elétrica bobina->tanque. No futuro pode ser
substituído por um campo real (ex.: resultado de FEM).
"""
from __future__ import annotations

import numpy as np


# vermelho = perto (crítico) ; azul = longe (folgado). (usado como nome de cmap
# no PyVista: "RdBu" já faz esse papel; aqui mantemos a referência conceitual)
PROXIMITY_COLORSCALE = "RdBu"


def distancia_vertices_ao_tanque(x, y, tanque_int):
    """Distância lateral (plano XY) de cada ponto à parede interna + próxima."""
    cx, cy = tanque_int["cx"], tanque_int["cy"]
    hx, hy = tanque_int["hx"], tanque_int["hy"]
    dx = hx - np.abs(np.asarray(x) - cx)
    dy = hy - np.abs(np.asarray(y) - cy)
    return np.minimum(dx, dy)


def _anel_xy(cx, cy, raio, n=72):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return cx + raio * np.cos(t), cy + raio * np.sin(t)


def _tank_hxy(tr, info):
    t = tr.tanque
    if info:
        return (info["L"] / 2 + t.folga_lateral, info["W"] / 2 + t.folga_frente_tras)
    ti = tr.tanque_interno()
    return ti["hx"], ti["hy"]


def gaps_eletricos(tr, info=None):
    """Folgas críticas p/ análise de campo: [(nome, r0, distancia_mm)].

    r0 = raio externo da bobina mais externa; distância = folga até o
    contra-eletrodo (parede do tanque ou bobina vizinha).
    """
    if info:
        aneis = info.get("aneis", [])
        r0 = max((re for _, re in aneis), default=0.0)
        centros = info.get("centros_x", [0.0])
        passo = (centros[1] - centros[0]) if len(centros) > 1 else 0.0
    else:
        r0 = tr.raio_externo_max()
        centros = tr.centros_pernas_x()
        passo = tr.nucleo.passo_fases
    hx, hy = _tank_hxy(tr, info)
    gaps = [
        ("Bobina ↔ parede (Y)", r0, hy - r0),
        ("Bobina ↔ ponta (X)", r0, hx - (centros[-1] + r0)),
    ]
    if passo:
        gaps.append(("Entre fases", r0, passo - 2 * r0))
    return gaps


def faixa_global(transformador, n=72):
    """cmin/cmax da folga, varrendo os enrolamentos (raios int/ext) das fases."""
    tint = transformador.tanque_interno()
    vals = []
    for cx in transformador.centros_pernas_x():
        for e in transformador.enrolamentos:
            for raio in (e.raio_int, e.raio_ext):
                x, y = _anel_xy(cx, 0.0, raio, n=n)
                vals.append(distancia_vertices_ao_tanque(x, y, tint))
    if not vals:
        return 0.0, 1.0
    allv = np.concatenate(vals)
    return float(allv.min()), float(allv.max())
