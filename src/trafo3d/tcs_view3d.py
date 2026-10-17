r"""Viewer 3D do espaço para TCs (PyVista).

Mostra, por fase: bucha (revolucionada, inclinada), caneco, TCs empilhados
(por peso) e o VOLUME do gradiente da zona segura — AZUL dentro (seguro) ->
cores quentes saindo. Tudo acompanha a inclinação das buchas.

Uso:  python -m src.trafo3d.tcs_view3d params.json [--shot out.png]
params = {dxf, n, passo, ang, caneco_d, L6, bucha_r, tcs:[[...],[...],[...]]}
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np
import pyvista as pv

from . import buchas as BU
from . import buchas_view3d as BV
from . import tcs as T

S = 0.001
FUNDO = "#0d1117"


def _down_dir(phi_deg):
    """Direção (unit) do eixo da bucha apontando p/ baixo (dentro do tanque)."""
    p = math.radians(phi_deg)
    return np.array([-math.sin(p), 0.0, -math.cos(p)])


def _ring(cx, r_int, r_ext, z0, z1):
    disc = pv.Disc(center=(0, 0, 0), inner=r_int * S, outer=r_ext * S,
                   normal=(0, 0, 1), r_res=2, c_res=48)
    tubo = disc.extrude((0, 0, (z1 - z0) * S), capping=True)
    tubo.translate((cx * S, 0, z0 * S), inplace=True)
    return tubo


def construir(params, off_screen=False):
    perfil = BU.carregar_perfil(params["dxf"])
    n = int(params.get("n", 3))
    passo = float(params["passo"])
    ang = float(params.get("ang", 0.0))
    caneco_d = float(params["caneco_d"])
    L6 = float(params["L6"])
    bucha_r = float(params.get("bucha_r", 60.0))
    tcs_fases = params.get("tcs", [[] for _ in range(n)])
    # foco_fase: -1 = todas as fases; 0/1/2 = isola essa bucha e foca nos TCs
    foco = params.get("foco_fase", -1)
    try:
        foco = int(foco)
    except (TypeError, ValueError):
        foco = -1
    base = BU.centros(n, passo)
    Rs = T.raio_seguro(caneco_d)
    rc = caneco_d / 2
    end = T.zmax_zona(L6, Rs, bucha_r)

    pl = pv.Plotter(off_screen=off_screen, window_size=(1400, 900))
    pl.set_background(FUNDO)
    try:
        pl.enable_depth_peeling(10)
    except Exception:
        pass

    bucha0 = BV._bucha_mesh(perfil)
    fases = []
    for i, cx in enumerate(base):
        if 0 <= foco < n and i != foco:
            continue                               # mostra só a fase em foco
        phi = -ang if i == 0 else (ang if i == n - 1 else 0.0)
        fases.append((cx, phi))
        # bucha (porcelana, acima da tampa)
        m = bucha0.copy(); m.translate((cx * S, 0, 0), inplace=True)
        if phi:
            m = m.rotate_y(phi, point=(cx * S, 0, 0), inplace=False)
        pl.add_mesh(m, color="#c9ccd1", opacity=0.85, smooth_shading=True)
        # caneco (abaixo da tampa), translúcido
        can = pv.Cylinder(center=(cx * S, 0, -(L6 + 80) / 2 * S),
                          direction=(0, 0, 1), radius=rc * S,
                          height=(L6 + 80) * S, resolution=48)
        if phi:
            can = can.rotate_y(phi, point=(cx * S, 0, 0), inplace=False)
        pl.add_mesh(can, color="#7fb3c4", opacity=0.10, smooth_shading=True)
        pl.add_mesh(can.extract_feature_edges(), color="#7fb3c4", line_width=1)
        # TCs empilhados (por peso), em torno do eixo, abaixo da tampa
        for t in T.empilhar(tcs_fases[i] if i < len(tcs_fases) else []):
            dint = float(t.get("DINT", 0) or 0)
            dext = float(t["DEXT"])
            z0 = -(T.TOPO_GAP + t["z1"])          # topo+ p/ baixo
            z1 = -(T.TOPO_GAP + t["z0"])
            cor = "#ffd400" if dext / 2 <= Rs else "#ff3b30"
            ring = _ring(cx, dint / 2, dext / 2, z0, z1)
            if phi:
                ring = ring.rotate_y(phi, point=(cx * S, 0, 0), inplace=False)
            pl.add_mesh(ring, color=cor, opacity=0.9, smooth_shading=True)

    # volume do gradiente da zona segura — só DENTRO dos canecos (fora = oculto)
    L_can = L6 + 80
    xs_t = [cx + _down_dir(phi)[0] * L_can for cx, phi in fases]
    xmin = min(min(cx for cx, _ in fases), min(xs_t)) - rc - 10
    xmax = max(max(cx for cx, _ in fases), max(xs_t)) + rc + 10
    nx, ny, nz = 170, 70, 120
    gx = np.linspace(xmin, xmax, nx)
    gy = np.linspace(-rc - 10, rc + 10, ny)
    gz = np.linspace(-(L_can + 10), T.TOPO_GAP + 10, nz)
    X, Y, Z = np.meshgrid(gx, gy, gz, indexing="ij")
    Dmin = np.full(X.shape, np.nan)
    for cx, phi in fases:
        d = _down_dir(phi)
        px, py, pz = X - cx, Y, Z
        depth = px * d[0] + py * d[1] + pz * d[2]
        rx = px - depth * d[0]; ry = py - depth * d[1]; rz = pz - depth * d[2]
        r = np.sqrt(rx ** 2 + ry ** 2 + rz ** 2)
        dentro = (r <= rc) & (depth >= 0) & (depth <= L_can)   # dentro do caneco
        dval = T.dist_fora(r, depth, L6, Rs, rc, bucha_r)
        cur = np.where(dentro, dval, np.nan)
        Dmin = np.where(np.isnan(Dmin), cur,
                        np.where(np.isnan(cur), Dmin, np.minimum(Dmin, cur)))
    grid = pv.ImageData(
        dimensions=(nx, ny, nz),
        spacing=((gx[-1] - gx[0]) / (nx - 1) * S, (gy[-1] - gy[0]) / (ny - 1) * S,
                 (gz[-1] - gz[0]) / (nz - 1) * S),
        origin=(gx[0] * S, gy[0] * S, gz[0] * S))
    grid["fora (mm)"] = Dmin.flatten(order="F")
    bar = dict(title="Fora da zona (mm)", color="white", title_font_size=13,
               label_font_size=11, n_labels=5, vertical=True,
               position_x=0.90, position_y=0.12, height=0.7, width=0.05)
    # azul no centro (seguro) -> quente na parede. clim = folga até a parede.
    cmax = max(rc - Rs, 20.0)
    opac = [0.18, 0.16, 0.16, 0.2, 0.28, 0.4, 0.5]   # transparente p/ ver os TCs
    pl.add_volume(grid, scalars="fora (mm)", cmap="turbo", clim=[0.0, cmax],
                  opacity=opac, opacity_unit_distance=rc * S * 0.6,
                  scalar_bar_args=bar, show_scalar_bar=True)

    rotulo = f"trafo3d — espaço para TCs (incl. {ang:.0f}°)"
    if 0 <= foco < n:
        rotulo += f" — foco fase H{foco + 1}"
    pl.add_text(rotulo, font_size=10, color="white")

    pl.view_isometric()
    # com foco: enquadra a câmera na região do caneco/TCs (ignora a porcelana alta)
    if 0 <= foco < n and fases:
        cxf, phif = fases[0]
        dxf_end = cxf + _down_dir(phif)[0] * L_can
        xlo = min(cxf, dxf_end) - rc - 10
        xhi = max(cxf, dxf_end) + rc + 10
        zlo, zhi = -(L_can + 10), T.TOPO_GAP + 60
        fp = np.array([(xlo + xhi) / 2, 0.0, (zlo + zhi) / 2]) * S
        tam = max(xhi - xlo, zhi - zlo, 2 * (rc + 10)) * S
        dirv = np.array([1.0, -1.0, 0.45]); dirv /= np.linalg.norm(dirv)
        pl.camera.focal_point = tuple(fp)
        pl.camera.position = tuple(fp + dirv * tam * 2.2)
        pl.camera.up = (0.0, 0.0, 1.0)
        pl.reset_camera_clipping_range()
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
        pl.show(title="trafo3d — TCs (PyVista)")


if __name__ == "__main__":
    sys.exit(main())
