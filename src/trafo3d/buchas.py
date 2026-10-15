r"""Estudo de buchas (AT): distância entre buchas, raio de proteção, inclinação
e contato — inspirado no weg_app_full.py do EPA.

Metodologia (NÃO inventada — espelha o EPA; os números são do usuário/banco):
  - Raio de proteção no ar R_ar (por classe/NBI) traçado a partir do Ø de
    aplicação d_apl.
  - Passo mínimo entre eixos:  passo_min = R_ar + d_apl + toque
    folga (ar) = passo − R_ar − d_apl   (precisa ≥ toque).
  - Inclinação das buchas das PONTAS (topo p/ fora, pivô na tampa) afasta os
    pontos de contato por braço·sen(θ); permite passo menor sem tocar (θ ≤ ~20°).

O campo elétrico usa o MESMO modelo coaxial simplificado da análise bobina↔tanque
(E = U/(r·ln(R/r0))), aqui irradiando de cada bucha.

Perfil 3D: o DXF 2D da bucha é revolucionado em torno do eixo vertical.
"""
from __future__ import annotations

import io
import math

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import dxf_io

ANGULO_MAX = 20.0
ANGULOS_PADRAO = [0.0, 5.0, 10.0, 15.0, 20.0]


# ------------------------------------------------------------- perfil do DXF
def carregar_perfil(fonte: str, nb: int = 180) -> dict:
    """Perfil 2D da bucha (segmentos + envelope p/ revolução).

    Aceita um .dxf (extrai) ou um .json (pré-gerado, sem parse de DXF).
    """
    if fonte.endswith(".json"):
        import json
        with open(fonte, "r", encoding="utf-8") as f:
            d = json.load(f)
        d["z"] = np.asarray(d["z"], float)
        d["r"] = np.asarray(d["r"], float)
        return d
    geo = dxf_io.ler_dxf(fonte)
    segs = geo.projecao("frontal")               # [(x,z),...] em mm
    pts = np.array([p for s in segs for p in s], dtype=float)
    z0, z1 = pts[:, 1].min(), pts[:, 1].max()
    ax = np.abs(pts[:, 0])
    edges = np.linspace(z0, z1, nb + 1)
    zc = 0.5 * (edges[:-1] + edges[1:])
    r = np.zeros(nb)
    for i in range(nb):
        m = (pts[:, 1] >= edges[i]) & (pts[:, 1] <= edges[i + 1])
        r[i] = ax[m].max() if m.any() else np.nan
    # preenche vazios por interpolação
    ok = ~np.isnan(r)
    r = np.interp(zc, zc[ok], r[ok]) if ok.any() else np.full(nb, 50.0)
    segs_rel = [[(x, z - z0) for x, z in s] for s in segs]
    return {"segs": segs_rel, "z": zc - z0, "r": r,
            "altura": float(z1 - z0), "raio": float(ax.max())}


# --------------------------------------------------------- geometria/arranjo
def _ceil5(v):
    return math.ceil(v / 5.0) * 5.0


def centros(n: int, passo: float) -> list[float]:
    return [(i - (n - 1) / 2.0) * passo for i in range(n)]


def estudo_inclinacao(R_ar, d_apl, toque, braco, passo, n=3,
                      angulos=None) -> list[dict]:
    """Para cada ângulo: afastamento do contato, separação e folga no ar.

    Só as buchas das PONTAS inclinam (topo p/ fora); a central fica fixa.
    O par crítico é central↔ponta: sep = passo + braço·sen(θ).
    """
    angulos = angulos or ANGULOS_PADRAO
    base = R_ar + d_apl                 # distância de contato (eixo a eixo)
    out = []
    for th in angulos:
        desloc = braco * math.sin(math.radians(th))
        sep = passo + desloc
        folga = sep - base
        out.append({"ang": th, "desloc": desloc, "sep": sep, "folga": folga,
                    "ok": folga >= toque})
    return out


def melhor_inclinacao(opcoes, ) -> dict | None:
    for o in opcoes:                    # menor ângulo que atende o toque
        if o["ok"]:
            return o
    return None


def posicoes_topo(n, passo, R_ar, d_apl, braco, ang) -> list[dict]:
    """Posição X do ponto de contato (topo) de cada bucha, c/ inclinação."""
    desloc = braco * math.sin(math.radians(ang))
    base_c = centros(n, passo)
    tops = []
    for i, cx in enumerate(base_c):
        s = 0.0
        if i == 0:
            s = -desloc
        elif i == n - 1:
            s = +desloc
        tops.append({"x_base": cx, "x_topo": cx + s, "rotulo": f"H{i + 1}"})
    return tops


def contatos(tops, R_ar, d_apl, toque) -> list[dict]:
    """Folga no ar entre buchas vizinhas (pontos de contato no topo)."""
    base = R_ar + d_apl
    out = []
    for a, b in zip(tops, tops[1:]):
        sep = abs(b["x_topo"] - a["x_topo"])
        folga = sep - base
        out.append({"par": f"{a['rotulo']}–{b['rotulo']}", "sep": sep,
                    "folga": folga, "ok": folga >= toque})
    return out


# ----------------------------------------------------------------- campo 2D
def _campo_topo(xs_centros, r0, R, U, X, Y):
    E = np.zeros_like(X)
    for cx in xs_centros:
        r = np.clip(np.hypot(X - cx, Y), r0, R)
        E = np.maximum(E, U / (r * math.log(R / r0)))
    return E


# ----------------------------------------------------------------- figuras
def fig_topo(tops, R_ar, d_apl, U, ct=None):
    """Vista de cima: campo (turbo) + Ø de aplicação + raio de proteção."""
    r0 = max(d_apl / 2, 1.0)
    R = r0 + R_ar
    xs = [t["x_topo"] for t in tops]
    span = max(xs) - min(xs) + 2 * R
    cxmid = (max(xs) + min(xs)) / 2
    gx = np.linspace(cxmid - span / 2, cxmid + span / 2, 320)
    gy = np.linspace(-R * 1.3, R * 1.3, 170)
    X, Y = np.meshgrid(gx, gy)
    E = _campo_topo(xs, r0, R, U, X, Y)
    fig, ax = plt.subplots(figsize=(8.6, 3.4), dpi=110)
    im = ax.pcolormesh(X, Y, E, cmap="turbo", shading="auto")
    for t in tops:
        ax.add_patch(plt.Circle((t["x_topo"], 0), r0, color="white", zorder=4))
        ax.add_patch(plt.Circle((t["x_topo"], 0), R, fill=False,
                                 ec="#00e5ff", lw=1.3, ls="--", zorder=5))
        ax.text(t["x_topo"], R * 1.05, t["rotulo"], ha="center", color="white",
                fontsize=9, zorder=6)
    # folga entre Ø vizinhos (contato quando a proteção alcança o Ø do vizinho)
    for i, c in enumerate(ct or []):
        xa, xb = tops[i]["x_topo"] + r0, tops[i + 1]["x_topo"] - r0
        cor = "#39d353" if c["ok"] else "#ff3b30"
        ax.annotate("", (xb, 0), (xa, 0),
                    arrowprops=dict(arrowstyle="<->", color=cor, lw=1.6), zorder=7)
        ax.text((xa + xb) / 2, R * 0.55, f"{c['folga']:.0f}", ha="center",
                color=cor, fontsize=9, fontweight="bold", zorder=7,
                bbox=dict(fc="#101418", ec="none", alpha=0.7, pad=1))
    ax.set_aspect("equal")
    ax.set_title("Vista superior — campo + raio de proteção (folga em mm)")
    ax.set_xlabel("[mm]"); ax.set_ylabel("[mm]")
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, label="E [kV/mm]")
    fig.tight_layout()
    return fig


def fig_elevacao(perfil, tops, R_ar, d_apl, ang, braco):
    """Elevação: perfis das buchas (inclinadas) + pontos de contato + proteção."""
    fig, ax = plt.subplots(figsize=(8.6, 4.4), dpi=110)
    z = perfil["z"]
    r = perfil["r"]
    h = perfil["altura"]
    outline = np.array(list(zip(r, z)) + list(zip(-r[::-1], z[::-1])))
    for i, t in enumerate(tops):
        # pivô na BASE (tampa); só as buchas externas inclinam, topo p/ FORA.
        th = 0.0
        if i == 0:
            th = +ang          # bucha esquerda: topo vai para -x (fora)
        elif i == len(tops) - 1:
            th = -ang          # bucha direita: topo vai para +x (fora)
        a = math.radians(th)
        ca, sa = math.cos(a), math.sin(a)
        # rotaciona o perfil em torno da base (pivô na tampa) e translada em X
        xr = outline[:, 0] * ca - outline[:, 1] * sa + t["x_base"]
        zr = outline[:, 0] * sa + outline[:, 1] * ca
        ax.plot(xr, zr, color="#9fb3c4", lw=1.2)
        # ponto de contato (topo) + círculo de proteção
        xtop = -math.sin(a) * h + t["x_base"]
        ztop = math.cos(a) * h
        ax.add_patch(plt.Circle((xtop, ztop), R_ar + d_apl / 2, fill=False,
                                 ec="#00e5ff", lw=1.3, ls="--"))
        ax.plot([xtop], [ztop], "o", color="#ffd400")
        ax.text(xtop, ztop + (R_ar + d_apl / 2) * 1.05, t["rotulo"],
                ha="center", color="#333", fontsize=9)
    ax.set_aspect("equal")
    ax.set_title(f"Elevação — buchas externas inclinadas {ang:.0f}° "
                 f"(pivô na base, topo p/ fora)")
    ax.set_xlabel("[mm]"); ax.set_ylabel("altura [mm]")
    ax.grid(True, ls=":", alpha=0.4)
    fig.tight_layout()
    return fig


def fig_estudo(opcoes, toque):
    fig, ax = plt.subplots(figsize=(6.0, 3.4), dpi=110)
    ang = [o["ang"] for o in opcoes]
    fol = [o["folga"] for o in opcoes]
    ax.plot(ang, fol, "-o", color="#2a6f97")
    ax.axhline(toque, color="#e07000", ls="--", label=f"toque mín {toque:.0f} mm")
    ax.set_title("Estudo de inclinação — folga no ar × ângulo")
    ax.set_xlabel("Inclinação [°]"); ax.set_ylabel("Folga no ar [mm]")
    ax.grid(True, ls=":", alpha=0.5); ax.legend(fontsize=8)
    fig.tight_layout()
    return fig


def fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
