r"""Viewer 3D das buchas (PyVista): perfil do DXF revolucionado, inclinação das
pontas, esferas de raio de proteção e campo elétrico volumétrico (dispersão).

Mesmo gradiente (turbo) da análise bobina↔tanque: quente = crítico (perto),
frio = seguro (longe). O campo irradia dos terminais das buchas.

Uso:  python -m src.trafo3d.buchas_view3d params.json [--shot out.png]
params.json = {"dxf":..., "n":3, "passo":..., "ang":..., "R_ar":..., "d_apl":...,
               "U":...}
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np
import pyvista as pv

from . import buchas as B

S = 0.001
FUNDO = "#0d1117"
COR_BUCHA = "#c9ccd1"


def _bucha_mesh(perfil):
    """Revolve o envelope do perfil em torno do eixo Z -> sólido da bucha."""
    r = np.asarray(perfil["r"]) * S
    z = np.asarray(perfil["z"]) * S
    pts = np.column_stack([r, np.zeros_like(r), z])
    line = pv.lines_from_points(pts)
    return line.extrude_rotate(resolution=56, capping=False)


def _rot_y(mesh, ang_deg, pivot):
    return mesh.rotate_y(ang_deg, point=pivot, inplace=False)


def construir(params: dict, off_screen=False):
    perfil = B.carregar_perfil(params["dxf"])
    n = int(params.get("n", 3))
    passo = float(params["passo"])
    ang = float(params.get("ang", 0.0))
    R_ar = float(params["R_ar"])
    d_apl = float(params["d_apl"])
    U = float(params.get("U", 70.0))
    h = perfil["altura"]
    base = B.centros(n, passo)

    pl = pv.Plotter(off_screen=off_screen, window_size=(1400, 900))
    pl.set_background(FUNDO)
    try:
        pl.enable_depth_peeling(10)
    except Exception:
        pass

    bucha0 = _bucha_mesh(perfil)
    terminais = []
    for i, cx in enumerate(base):
        th = -ang if i == 0 else (ang if i == n - 1 else 0.0)
        m = bucha0.copy()
        m.translate((cx * S, 0, 0), inplace=True)
        if th:
            m = _rot_y(m, th, (cx * S, 0, 0))
        pl.add_mesh(m, color=COR_BUCHA, smooth_shading=True, opacity=0.9)
        a = math.radians(th)
        tx = cx + math.sin(a) * h          # topo deslocado pela inclinação
        tz = math.cos(a) * h
        terminais.append((tx, tz))
        # esfera do raio de proteção (translúcida)
        pl.add_mesh(pv.Sphere(radius=(R_ar + d_apl / 2) * S,
                              center=(tx * S, 0, tz * S)),
                    color="#00e5ff", opacity=0.10)

    # campo elétrico volumétrico (dispersão esférica a partir dos terminais)
    r0 = max(d_apl / 2, 1.0)
    R = r0 + R_ar
    txs = [t[0] for t in terminais]
    tzs = [t[1] for t in terminais]
    pad = R * 1.2
    gx = np.linspace(min(txs) - pad, max(txs) + pad, 110)
    gy = np.linspace(-pad, pad, 70)
    gz = np.linspace(min(tzs) - pad, max(tzs) + pad, 70)
    X, Y, Z = np.meshgrid(gx, gy, gz, indexing="ij")
    E = np.zeros_like(X)
    for tx, tz in terminais:
        d = np.clip(np.sqrt((X - tx) ** 2 + Y ** 2 + (Z - tz) ** 2), r0, R)
        E = np.maximum(E, U / (d * math.log(R / r0)))
    grid = pv.ImageData(
        dimensions=E.shape,
        spacing=((gx[-1] - gx[0]) / (len(gx) - 1) * S,
                 (gy[-1] - gy[0]) / (len(gy) - 1) * S,
                 (gz[-1] - gz[0]) / (len(gz) - 1) * S),
        origin=(gx[0] * S, gy[0] * S, gz[0] * S))
    grid["E (kV/mm)"] = E.flatten(order="F")
    bar = dict(title="Campo E (kV/mm)", color="white", title_font_size=14,
               label_font_size=11, n_labels=5, vertical=True,
               position_x=0.90, position_y=0.12, height=0.7, width=0.05)
    opac = [0.0, 0.03, 0.08, 0.18, 0.38, 0.65, 0.9]
    pl.add_volume(grid, scalars="E (kV/mm)", cmap="turbo",
                  clim=[float(E.min()), float(E.max())], opacity=opac,
                  opacity_unit_distance=R * S * 0.25, scalar_bar_args=bar,
                  show_scalar_bar=True)

    pl.add_text(f"trafo3d — buchas (incl. {ang:.0f}°)", font_size=10,
                color="white")
    pl.view_isometric()
    return pl


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("params")
    ap.add_argument("--shot", default=None)
    a = ap.parse_args(argv)
    with open(a.params, "r", encoding="utf-8") as f:
        params = json.load(f)
    pl = construir(params, off_screen=bool(a.shot))
    if a.shot:
        pl.screenshot(a.shot)
        print("PNG:", a.shot)
    else:
        pl.show(title="trafo3d — buchas (PyVista)")


if __name__ == "__main__":
    sys.exit(main())
