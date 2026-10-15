r"""Reconstrução 3D da parte ativa a partir do DXF (visual hull) — porte do
`weg_hull_dxf.py` do EPA APP, adaptado ao trafo3d.

- `hull_zup(dxf)`  -> malha PyVista do conjunto, no frame do trafo3d
                      (X=comprimento/fases, Y=profundidade, Z=altura; base em z=0),
                      em metros. É a silhueta REAL da armadura+estrutura.
- `info_dxf(dxf)`  -> dims (L,W,H), base, centros das colunas e os anéis
                      (enrolamentos) concêntricos extraídos da vista superior.

Técnica do hull: as 3 vistas ortográficas são silhuetas por 3 eixos; esculpe-se
um bloco de voxels mantendo só os que caem dentro das 3 silhuetas (carving) e
gera-se a malha por marching cubes + suavização.
"""
from __future__ import annotations

import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import pyvista as pv

from . import dxf_io

S = 0.001  # mm -> m


def _tres_aneis(r_in, r_out):
    """3 enrolamentos concêntricos no intervalo radial [r_in, r_out] (p/ visual)."""
    if r_out <= r_in:
        r_out = r_in + 60.0
    step = (r_out - r_in) / 3.0
    aneis = []
    for i in range(3):
        ri = r_in + i * step
        re = ri + step * 0.72
        aneis.append((ri, re))
    aneis[-1] = (aneis[-1][0], r_out)
    return aneis


# --------------------------------------------------------------- visual hull
def _mask(geo, view: str, nu: int):
    proj = geo.projecao(view)
    xs = [p[0] for s in proj for p in s]
    ys = [p[1] for s in proj for p in s]
    umin, umax, vmin, vmax = min(xs), max(xs), min(ys), max(ys)
    nv = max(8, int(round(nu * (vmax - vmin) / (umax - umin))))
    pad = 3
    img = Image.new("L", (nu + 2 * pad, nv + 2 * pad), 0)
    d = ImageDraw.Draw(img)
    for seg in proj:
        px = [((u - umin) / (umax - umin) * (nu - 1) + pad,
               (v - vmin) / (vmax - vmin) * (nv - 1) + pad) for u, v in seg]
        if len(px) >= 2:
            d.line(px, fill=255, width=2)
    img = img.filter(ImageFilter.MaxFilter(3))
    fill = img.copy()
    ImageDraw.floodfill(fill, (0, 0), 128)
    inside = (np.array(fill) != 128)
    inside = inside[pad:-pad, pad:-pad]
    M = np.flipud(inside).T
    return M, (umin, umax, vmin, vmax)


def _idx(coords, cmin, cmax, n):
    t = np.clip((coords - cmin) / (cmax - cmin), 0, 1)
    return (t * (n - 1)).round().astype(int)


def construir_hull(dxf: str, res: int = 150):
    """Malha PyVista do conjunto (frame EPA: X=compr, Y=altura, Z=largura)."""
    geo = dxf_io.ler_dxf(dxf)
    Mf, (fx0, fx1, fy0, fy1) = _mask(geo, "frontal", res)
    Ml, (lz0, lz1, ly0, ly1) = _mask(geo, "lateral", res)
    Ms, (sx0, sx1, sz0, sz1) = _mask(geo, "superior", res)

    Xmin, Xmax = fx0, fx1
    Ymin, Ymax = fy0, fy1
    Zmin, Zmax = lz0, lz1
    dv = (Xmax - Xmin) / (res - 1)
    nx, ny, nz = res, max(8, int((Ymax - Ymin) / dv)), max(8, int((Zmax - Zmin) / dv))
    xs = np.linspace(Xmin, Xmax, nx)
    ys = np.linspace(Ymin, Ymax, ny)
    zs = np.linspace(Zmin, Zmax, nz)

    Ff = Mf[np.ix_(_idx(xs, fx0, fx1, Mf.shape[0]), _idx(ys, fy0, fy1, Mf.shape[1]))]
    Fl = Ml[np.ix_(_idx(zs, lz0, lz1, Ml.shape[0]), _idx(ys, ly0, ly1, Ml.shape[1]))]
    Fs = Ms[np.ix_(_idx(xs, sx0, sx1, Ms.shape[0]), _idx(zs, sz0, sz1, Ms.shape[1]))]
    solid = (Ff[:, :, None] & Fl.T[None, :, :] & Fs[:, None, :])

    grid = pv.ImageData(
        dimensions=solid.shape,
        spacing=((Xmax - Xmin) / (nx - 1) * S, (Ymax - Ymin) / (ny - 1) * S,
                 (Zmax - Zmin) / (nz - 1) * S),
        origin=(Xmin * S, Ymin * S, Zmin * S))
    grid.point_data["v"] = solid.astype(np.float32).flatten(order="F")
    mesh = grid.contour([0.5], scalars="v")
    if mesh.n_points:
        mesh = mesh.smooth(n_iter=25, relaxation_factor=0.1)
    return mesh


def hull_zup(fonte: str, res: int = 150):
    """Hull no frame do trafo3d (Z-up, base em z=0), em metros.

    Aceita um .dxf (reconstrói o hull) ou um .json (carrega o .ply pré-gerado).
    """
    if fonte.endswith(".json"):
        with open(fonte, "r", encoding="utf-8") as f:
            d = json.load(f)
        ply = os.path.join(os.path.dirname(fonte), d["hull_ply"])
        return pv.read(ply)
    mesh = construir_hull(fonte, res=res)
    mesh = mesh.flip_y(inplace=False)                 # desfaz espelhamento vertical
    p = mesh.points
    mesh.points = np.column_stack([p[:, 0], p[:, 2], p[:, 1]])  # (x, z, y) -> Z-up
    zmin = mesh.bounds[4]
    if abs(zmin) > 1e-9:                              # apoia a base em z=0
        mesh.translate((0, 0, -zmin), inplace=True)
    return mesh


# --------------------------------------------------------- dados paramétricos
def _circulos(geo, view):
    out = []
    for x in geo.primitivas.get(view, []):
        d = x if isinstance(x, dict) else getattr(x, "__dict__", {})
        if "r" in d and "cx" in d:
            out.append((float(d["cx"]), float(d.get("cy", 0.0)), float(d["r"])))
    return out


def _cluster(vals, tol):
    vals = sorted(vals)
    grupos = [[vals[0]]]
    for v in vals[1:]:
        if v - grupos[-1][-1] <= tol:
            grupos[-1].append(v)
        else:
            grupos.append([v])
    return [float(np.mean(g)) for g in grupos]


def _altura_bobinas(geo, H):
    """Faixa vertical (z0, z1) das bobinas, da vista frontal.

    As bobinas aparecem como retângulos altos; pegamos os segmentos VERTICAIS
    longos (bordas dos enrolamentos) e tomamos sua extensão vertical dominante.
    """
    spans = []
    for seg in geo.projecao("frontal"):
        for i in range(len(seg) - 1):
            (x0, y0), (x1, y1) = seg[i], seg[i + 1]
            if abs(x1 - x0) < 2 and abs(y1 - y0) > 0.4 * H:
                spans.append((min(y0, y1), max(y0, y1)))
    if not spans:
        return 0.15 * H, 0.85 * H
    y0 = float(np.median([s[0] for s in spans]))
    y1 = float(np.median([s[1] for s in spans]))
    return y0, y1


def info_dxf(fonte: str) -> dict:
    """Dimensões, base, centros de coluna, anéis e altura das bobinas.

    Aceita um .dxf (extrai) ou um .json (pré-gerado, sem parse de DXF).
    """
    if fonte.endswith(".json"):
        with open(fonte, "r", encoding="utf-8") as f:
            d = json.load(f)
        d["aneis"] = [tuple(a) for a in d["aneis"]]
        d["z_bob"] = tuple(d["z_bob"])
        return d

    geo = dxf_io.ler_dxf(fonte)
    L, W, H = (float(v) for v in geo.dimensoes())
    base = float(getattr(geo, "base_y", 0.0))

    circ = _circulos(geo, "superior")
    rmin = 0.25 * max((r for _, _, r in circ), default=1.0)
    circ = [c for c in circ if c[2] >= rmin]

    centros = _cluster(sorted({cx for cx, _, _ in circ}), tol=120) if circ else [0.0]
    cx0 = min(centros, key=abs)
    raios = sorted({r for cx, _, r in circ if abs(cx - cx0) <= 120})
    raios = _cluster(raios, tol=18) if raios else []
    # intervalo radial real -> 3 enrolamentos concêntricos (melhor visualização)
    r_in = raios[0] if raios else 160.0
    r_out = raios[-1] if raios else 400.0
    aneis = _tres_aneis(r_in, r_out)

    z0, z1 = _altura_bobinas(geo, H)
    return {"L": L, "W": W, "H": H, "base": base,
            "centros_x": sorted(centros), "aneis": aneis,
            "z_bob": (z0, z1)}


if __name__ == "__main__":
    import sys
    info = info_dxf(sys.argv[1])
    print("dims L,W,H:", round(info["L"]), round(info["W"]), round(info["H"]))
    print("base:", round(info["base"]))
    print("centros_x:", [round(c) for c in info["centros_x"]])
    print("aneis (r_int,r_ext):", [(round(a), round(b)) for a, b in info["aneis"]])
