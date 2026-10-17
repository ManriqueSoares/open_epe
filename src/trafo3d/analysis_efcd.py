r"""Análise de distâncias elétricas bobina -> tanque (estilo EFCD).

MODELO DE CAMPO — SIMPLIFICADO (coaxial / cilindro-plano, de livro-texto):
    condutor = superfície externa da bobina (raio r0, tensão U)
    contra-eletrodo = parede do tanque (aterrada), à distância `gap`
    R = r0 + gap

    Potencial:  V(r) = U * ln(R/r) / ln(R/r0)         [kV]
    Campo:      E(r) = U / ( r * ln(R/r0) )            [kV/mm]  (U em kV, r em mm)
    distância da superfície da bobina: x = r - r0  (0 .. gap)

Este é um modelo SIMPLIFICADO para prototipagem — deve ser substituído por
cálculo de campo real (FEM / planilha / EFCD) quando disponível. Nada aqui é
valor de norma inventado: as curvas de suportabilidade Epd(d)=A*d^-B são
fornecidas pelo usuário.

Suportabilidade (curva de projeto): Epd(d) = A * d^(-B)   [kV/mm], d em mm.
Margem de segurança (comparação ponto a ponto com a curva de projeto):
    MS% = min_x ( Epd(x) - E(x) ) / Epd(x) * 100
(É a comparação stress x suportabilidade; NÃO é o integral "cumulative stress"
do EFCD — esse exige o método proprietário.)
"""
from __future__ import annotations

import io

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


# --------------------------------------------------------------- modelo campo
def perfil_campo(U: float, r0: float, gap: float, n: int = 400) -> dict:
    """Perfil radial E(x), V(x) do condutor (r0) até a parede (r0+gap)."""
    r0 = max(float(r0), 1e-3)
    gap = max(float(gap), 1e-3)
    R = r0 + gap
    lnRr = np.log(R / r0)
    x = np.linspace(0.0, gap, n)         # distância da superfície (mm)
    r = r0 + x
    E = U / (r * lnRr)                    # kV/mm
    V = U * np.log(R / r) / lnRr         # kV
    return {"x": x, "E": E, "V": V, "R": R, "r0": r0, "gap": gap,
            "E0": float(U / (r0 * lnRr)), "U": U}


def suportabilidade(x, A: float, B: float):
    """Epd(d) = A * d^(-B)  [kV/mm]; x em mm (evita x=0)."""
    xx = np.clip(np.asarray(x, float), 1e-3, None)
    return A * np.power(xx, -B)


def metricas(perfil: dict, A: float | None, B: float | None) -> dict:
    E = perfil["E"]
    out = {"E_max": float(E.max()), "E_med": float(E.mean()),
           "razao": float(E.max() / E.mean()) if E.mean() else float("nan"),
           "MS": None}
    if A and B:
        x = np.clip(perfil["x"], 1.0, None)       # curva de projeto a partir de 1 mm
        Epd = suportabilidade(x, A, B)
        margem = (Epd - E) / Epd
        out["MS"] = float(margem.min() * 100.0)
    return out


# --------------------------------------------------------------- figuras
# Mesma paleta do 3D principal: azul (junto da bobina) -> vermelho (na parede).
_CMAP_BOB_TANQUE = None


def _cmap_bob_tanque():
    global _CMAP_BOB_TANQUE
    if _CMAP_BOB_TANQUE is None:
        from matplotlib.colors import LinearSegmentedColormap
        _CMAP_BOB_TANQUE = LinearSegmentedColormap.from_list(
            "bob_tanque",
            [(0.00, "#1e5bff"),   # azul      — junto da bobina
             (0.55, "#2aa8ff"),   # azul claro
             (0.78, "#19c6e6"),   # ciano
             (0.90, "#ffb400"),   # âmbar
             (1.00, "#ff2800")])  # vermelho  — na parede do tanque
    return _CMAP_BOB_TANQUE


def fig_tensao(perfil: dict):
    fig, ax = plt.subplots(figsize=(6.2, 3.6), dpi=110)
    ax.plot(perfil["x"], perfil["V"], color="#2a7f3f", lw=2)
    ax.set_title("Tensão")
    ax.set_xlabel("Distância [mm]")
    ax.set_ylabel("Tensão [kV]")
    ax.grid(True, ls=":", alpha=0.6)
    fig.tight_layout()
    return fig


def fig_stress(perfil: dict, A=None, B=None, nome=""):
    fig, ax = plt.subplots(figsize=(6.2, 3.6), dpi=110)
    ax.plot(perfil["x"], perfil["E"], color="#2a7f3f", lw=2, label="Stress E(d)")
    if A and B:
        x = np.clip(perfil["x"], 1.0, None)
        ax.plot(perfil["x"], suportabilidade(x, A, B), color="#e08a00", lw=2,
                label=f"Suportabilidade {nome}: {A:g}·d^-{B:g}")
    ax.set_title("Campo elétrico: Stress × Suportabilidade")
    ax.set_xlabel("Distância [mm]")
    ax.set_ylabel("Campo elétrico [kV/mm]")
    ax.grid(True, ls=":", alpha=0.6)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig


def fig_campo2d(perfil: dict, npx: int = 260):
    """Heatmap radial por PROXIMIDADE (igual ao 3D principal):
    azul junto da bobina (distância 0) -> vermelho na parede (distância = gap)."""
    R, r0, gap = perfil["R"], perfil["r0"], perfil["gap"]
    g = np.linspace(-R, R, npx)
    X, Y = np.meshgrid(g, g)
    rr = np.hypot(X, Y)
    dist = np.full_like(rr, np.nan)
    mask = (rr >= r0) & (rr <= R)
    dist[mask] = rr[mask] - r0                  # distância da superfície da bobina
    fig, ax = plt.subplots(figsize=(4.2, 4.0), dpi=110)
    im = ax.imshow(dist, extent=[-R, R, -R, R], origin="lower",
                   cmap=_cmap_bob_tanque(), vmin=0.0, vmax=gap)
    circ = plt.Circle((0, 0), r0, color="white", zorder=3)
    ax.add_patch(circ)
    ax.set_title("Proximidade bobina → tanque")
    ax.set_xlabel("[mm]")
    ax.set_ylabel("[mm]")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04,
                 label="Distância da bobina [mm]")
    fig.tight_layout()
    return fig


def fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# --------------------------------------------------------------- tabela gaps
def analisar_gaps(U: float, gaps: list[tuple], A=None, B=None) -> list[dict]:
    """gaps = [(nome, r0, distancia)]; retorna linhas com E_max e MS."""
    linhas = []
    for nome, r0, d in gaps:
        if d <= 0 or r0 <= 0:
            linhas.append({"nome": nome, "d": d, "r0": r0, "E_max": None, "MS": None})
            continue
        perf = perfil_campo(U, r0, d)
        m = metricas(perf, A, B)
        linhas.append({"nome": nome, "d": d, "r0": r0,
                       "E_max": m["E_max"], "MS": m["MS"]})
    return linhas


# --------------------------------------------------------------- relatório PDF
def gerar_pdf(caminho: str, titulo: str, resumo: list[tuple], perfil: dict,
              gaps_tab: list[dict], A=None, B=None, nome_curva=""):
    with PdfPages(caminho) as pdf:
        # página 1: capa + resumo + tabela de distâncias
        fig = plt.figure(figsize=(8.27, 11.69), dpi=110)   # A4
        fig.suptitle(titulo, fontsize=15, y=0.97)
        ax = fig.add_axes([0.08, 0.60, 0.84, 0.30]); ax.axis("off")
        txt = "Parâmetros\n" + "\n".join(f"  {k}: {v}" for k, v in resumo)
        txt += ("\n\nModelo de campo: coaxial simplificado "
                "E(d)=U/(d·ln(R/r0)) — substituir por FEM/planilha.")
        if A and B:
            txt += f"\nCurva de projeto: {nome_curva}  Epd(d)={A:g}·d^-{B:g} kV/mm"
        ax.text(0, 1, txt, va="top", ha="left", fontsize=10, family="monospace")

        axt = fig.add_axes([0.08, 0.30, 0.84, 0.26]); axt.axis("off")
        axt.set_title("Distâncias elétricas", loc="left", fontsize=11)
        cols = ["Gap", "d [mm]", "r0 [mm]", "E_max [kV/mm]", "MS [%]"]
        cells = []
        for g in gaps_tab:
            cells.append([g["nome"], f"{g['d']:.0f}", f"{g['r0']:.0f}",
                          "-" if g["E_max"] is None else f"{g['E_max']:.2f}",
                          "-" if g["MS"] is None else f"{g['MS']:.1f}"])
        if cells:
            t = axt.table(cellText=cells, colLabels=cols, loc="center",
                          cellLoc="center")
            t.auto_set_font_size(False); t.set_fontsize(9); t.scale(1, 1.4)
        pdf.savefig(fig); plt.close(fig)

        # página 2: gráficos
        for f in (fig_tensao(perfil), fig_stress(perfil, A, B, nome_curva),
                  fig_campo2d(perfil)):
            pdf.savefig(f); plt.close(f)
    return caminho
