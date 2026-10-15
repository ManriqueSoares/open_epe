r"""Estudo do espaço para TCs nas buchas/canecos.

Zona segura para TC (livre de interação de campo) — conforme ESPAÇO PARA TCS.png:
  - cilindro de altura L6 e raio Rs = raio_caneco − folga_parede (40 mm),
    começando `topo_gap` (40 mm) abaixo do flange;
  - abaixo de L6 o espaço decai num CONE de 60° (meio-ângulo 30° do eixo),
    convergindo para o eixo da bucha.

Gradiente: AZUL dentro da zona (seguro) -> cores quentes SAINDO dela. O escalar
é a distância (mm) para fora da zona segura (0 dentro).

Regras de TC (do weg_app_full.py do EPA — números do usuário/banco):
  - folga TC -> parede/TC vizinho = 40 mm;
  - separação entre TCs empilhados = 3 mm;
  - empilhar por PESO (mais pesado embaixo, evita esmagamento).
TC: dict com nome, DINT, DEXT, ALT, KG (mm / kg).
"""
from __future__ import annotations

import io
import math

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FOLGA_PAREDE = 40.0       # TC -> parede do caneco / TC vizinho
SEP_EMPILHADO = 3.0       # entre TCs empilhados
TOPO_GAP = 40.0           # flange -> topo da zona L6
MEIO_ANGULO = 30.0        # graus (cone de 60° total)


# ----------------------------------------------------------- zona segura
def raio_seguro(caneco_d: float) -> float:
    return max(caneco_d / 2 - FOLGA_PAREDE, 1.0)


CANECO_EXTRA = 80.0       # comprimento do caneco = L6 + 80 (EPA)


def delta_cone(Rs, bucha_r):
    """Profundidade extra do cone 60° no raio seguro (a partir do corpo da bucha)."""
    tan = math.tan(math.radians(MEIO_ANGULO))        # 30° do eixo (60° total)
    return max(Rs - bucha_r, 0.0) * tan


def fundo_zona(x, L6, Rs, bucha_r):
    """Profundidade do FUNDO da zona segura num dado raio.

    Cilindro até L6 (r ≤ Rs); abaixo de L6 o espaço abre num cone 60° que parte
    do CORPO DA BUCHA (r=bucha_r, depth=L6) até a parede segura (r=Rs): o fundo
    fica mais profundo quanto maior o raio.
    """
    tan = math.tan(math.radians(MEIO_ANGULO))
    rr = np.clip(np.abs(x), bucha_r, Rs)
    return L6 + (rr - bucha_r) * tan


def zmax_zona(L6, Rs=None, bucha_r=0.0):
    z = L6 + CANECO_EXTRA
    if Rs is not None:
        z = max(z, L6 + delta_cone(Rs, bucha_r))
    return z


def dist_fora(x, depth, L6, Rs, rc, bucha_r=0.0):
    """Distância (mm) p/ fora da zona segura; 0 dentro (p/ o gradiente).

    Zona = cilindro (r ≤ Rs, 0 ≤ depth ≤ L6) + saia cônica 60° abaixo de L6
    (fundo inclinado partindo do corpo da bucha até a parede segura).
    """
    r = np.abs(x)
    fundo = fundo_zona(r, L6, Rs, bucha_r)
    d_rad = np.maximum(0.0, r - Rs)
    d_ax = np.maximum.reduce([np.zeros_like(depth), -depth, depth - fundo])
    return np.sqrt(d_rad ** 2 + d_ax ** 2)


# ----------------------------------------------------------- empilhamento
def empilhar(tcs: list[dict]) -> list[dict]:
    """Empilha com o mais LEVE em cima e o mais PESADO embaixo.

    depth 0 = topo da pilha. Os mais leves (KG menor) ficam no topo (menor
    profundidade) e os mais pesados embaixo (maior profundidade)."""
    val = [t for t in tcs if t.get("DEXT") and t.get("ALT")]
    val = sorted(val, key=lambda t: float(t.get("KG", 0)))    # leve primeiro (topo)
    z = 0.0
    out = []
    for i, t in enumerate(val):
        h = float(t["ALT"])
        out.append({**t, "z0": z, "z1": z + h})   # z0 topo, z1 fundo (p/ baixo+)
        z += h + (SEP_EMPILHADO if i < len(val) - 1 else 0.0)
    return out


def altura_pilha(tcs: list[dict]) -> float:
    e = empilhar(tcs)
    return e[-1]["z1"] if e else 0.0


# ----------------------------------------------------------- viabilidade
def viabilidade(tcs, caneco_d, L6, bucha_r=0.0) -> dict:
    Rs = raio_seguro(caneco_d)
    rc = caneco_d / 2
    pilha = empilhar(tcs)
    h = pilha[-1]["z1"] if pilha else 0.0
    itens = []
    ok_global = True
    for t in pilha:
        dext = float(t["DEXT"])
        dint = float(t.get("DINT", 0) or 0)
        fora_raio = dext / 2 - Rs             # >0 fura a parede segura (radial)
        fura_bucha = (bucha_r - dint / 2) if bucha_r else -1  # >0 bate na bucha
        # fundo da zona no raio INTERNO do TC (ponto mais raso disponível)
        fundo = float(fundo_zona(np.array([max(dint / 2, bucha_r)]),
                                 L6, Rs, bucha_r)[0])
        fora_fundo = t["z1"] - fundo          # >0 passa do fundo da zona
        ok = fora_raio <= 0 and fura_bucha <= 0 and fora_fundo <= 0
        ok_global = ok_global and ok
        itens.append({"nome": t.get("nome", t.get("TC", "?")), "dext": dext,
                      "fora_raio": fora_raio, "fora_cone": fora_fundo,
                      "fura_bucha": fura_bucha, "ok": ok})
    # altura: a pilha pode passar de L6 graças ao cone (espaço extra)
    fundo_max = L6 + delta_cone(Rs, bucha_r)
    cabe_altura = h <= fundo_max
    folga_altura = fundo_max - h
    return {"Rs": Rs, "altura_pilha": h, "cabe_altura": cabe_altura,
            "folga_altura": folga_altura, "itens": itens,
            "ok": ok_global and cabe_altura}


def contato_massas(fases: list[dict], caneco_d, passo, desloc_topo=0.0) -> list[dict]:
    """Impacto entre massas de canecos vizinhos (considera inclinação)."""
    out = []
    rc = caneco_d / 2
    xs = [f["x_topo"] for f in fases]
    for a, b in zip(range(len(xs)), range(1, len(xs))):
        sep = abs(xs[b] - xs[a])
        folga = sep - 2 * rc            # parede externa a parede externa
        out.append({"par": f"{fases[a]['rotulo']}–{fases[b]['rotulo']}",
                    "sep": sep, "folga": folga, "ok": folga >= 0})
    return out


# ----------------------------------------------------------- figura 2D
def fig_elevacao_tc(tcs, caneco_d, L6, bucha_r=60.0, titulo=""):
    """Elevação de UMA fase: gradiente + zona segura + caneco + TCs empilhados."""
    Rs = raio_seguro(caneco_d)
    rc = caneco_d / 2
    fundo_Rs = L6 + delta_cone(Rs, bucha_r)       # fundo da zona na parede segura
    end = max(zmax_zona(L6), fundo_Rs)
    pilha = empilhar(tcs)
    zmax = max(end, (pilha[-1]["z1"] if pilha else 0)) + 40

    gx = np.linspace(-rc * 1.25, rc * 1.25, 260)
    gz = np.linspace(-TOPO_GAP - 20, zmax, 300)
    X, Z = np.meshgrid(gx, gz)
    D = dist_fora(X, Z, L6, Rs, rc, bucha_r)
    fig, ax = plt.subplots(figsize=(5.2, 6.4), dpi=110)
    im = ax.pcolormesh(X, Z, D, cmap="turbo", shading="auto",
                       vmin=0, vmax=max(rc - Rs, 20))
    # contorno da zona segura (azul): cilindro + saia cônica 60° (meia direita)
    meia = [(Rs, 0), (Rs, fundo_Rs), (bucha_r, L6), (bucha_r, 0)]
    outline = meia + [(-x, z) for x, z in reversed(meia)]
    xs_o = [p[0] for p in outline] + [outline[0][0]]
    zs_o = [p[1] for p in outline] + [outline[0][1]]
    ax.plot(xs_o, zs_o, color="#00e5ff", lw=1.8)
    # caneco (paredes)
    for s in (-1, 1):
        ax.plot([s * rc, s * rc], [-TOPO_GAP, end], color="white", lw=1.2)
    # bucha (eixo)
    ax.plot([bucha_r, bucha_r, -bucha_r, -bucha_r], [zmax, 0, 0, zmax],
            color="#9fb3c4", lw=1.0)
    # TCs empilhados (retângulos dos dois lados)
    for t in pilha:
        dint = float(t.get("DINT", 0) or 0)
        dext = float(t["DEXT"])
        cor = "#ffd400" if dext / 2 <= Rs else "#ff3b30"
        w = (dext - dint) / 2
        for s in (-1, 1):
            x0 = min(s * dint / 2, s * dext / 2)
            ax.add_patch(plt.Rectangle((x0, t["z0"]), w, t["z1"] - t["z0"],
                                       fc=cor, ec="#333", alpha=0.6, lw=0.6))
    ax.invert_yaxis()                      # profundidade p/ baixo
    ax.set_aspect("equal")
    ax.set_title(titulo or "Espaço para TCs (azul = seguro)")
    ax.set_xlabel("raio [mm]"); ax.set_ylabel("profundidade [mm]")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04,
                 label="distância fora da zona [mm]")
    fig.tight_layout()
    return fig


def fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
