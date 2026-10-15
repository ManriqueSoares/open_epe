r"""Viewer 3D em PyVista (janela nativa VTK) — estilo EPA APP.

Dois modos:
  - PARAMÉTRICO (sem DXF): núcleo + enrolamentos (lista) + armadura paramétrica.
  - DXF (opts["dxf"]): armadura = SILHUETA REAL (visual hull do DXF, azul
    translúcida); bobinas e centros de coluna extraídos do próprio DXF.

Tanque: retangular ou oblongo (tr.tanque.tipo). A parte ativa fica dentro.

Uso:  python -m src.trafo3d.view3d params.json [--shot out.png]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pyvista as pv

from .model import Transformador, cor_enrol

S = 0.001  # mm -> m

VISTAS = ["Isométrica", "Frontal (XZ)", "Lateral (YZ)", "Superior (XY)",
          "Corte frontal"]

COR_NUCLEO = (0.55, 0.58, 0.62)
FUNDO = "#0d1117"
CMAP_FOLGA = "RdBu"


# ======================================================= geometria básica
def _box(bounds):
    return pv.Box(bounds=tuple(b * S for b in bounds))


def _tubo(cx, r_int, r_ext, z0, z1):
    disc = pv.Disc(center=(0, 0, 0), inner=r_int * S, outer=r_ext * S,
                   normal=(0, 0, 1), r_res=2, c_res=72)
    tubo = disc.extrude((0, 0, (z1 - z0) * S), capping=True)
    tubo.translate((cx * S, 0, z0 * S), inplace=True)
    return tubo


# ======================================================= specs (modo-agnóstico)
def _coil_specs(tr: Transformador, info):
    """Lista (cx, r_int, r_ext, z0, z1, cor) para as bobinas."""
    specs = []
    if info:
        z0, z1 = info.get("z_bob", (0.15 * info["H"], 0.85 * info["H"]))
        for cx in info["centros_x"]:
            for i, (ri, re) in enumerate(info["aneis"]):
                specs.append((cx, ri, re, z0, z1, cor_enrol(i)))
    else:
        for cx in tr.centros_pernas_x():
            for i, e in enumerate(tr.enrolamentos):
                zz0, zz1 = tr.z_enrolamento(e)
                specs.append((cx, e.raio_int, e.raio_ext, zz0, zz1,
                              e.cor or cor_enrol(i)))
    return specs


def _tank_dims(tr: Transformador, info):
    t = tr.tanque
    if info:
        return {"cx": 0.0, "cy": 0.0,
                "hx": info["L"] / 2 + t.folga_lateral,
                "hy": info["W"] / 2 + t.folga_frente_tras,
                "z0": -t.folga_fundo, "z1": info["H"] + t.folga_topo}
    return tr.tanque_interno()


def _col_info(tr: Transformador, info):
    """centros de coluna, raio de perna e faixa z das bobinas."""
    if info:
        centros = info["centros_x"]
        r_int_min = min((ri for ri, _ in info["aneis"]), default=160.0)
        z = info.get("z_bob", (0.15 * info["H"], 0.85 * info["H"]))
        return centros, 0.9 * r_int_min, z
    centros = tr.centros_pernas_x()
    z = (tr.nucleo.altura_culatra, tr.nucleo.altura_culatra + tr.nucleo.altura_janela)
    return centros, tr.nucleo.diametro_perna / 2, z


# ======================================================= elementos de cena
def _nucleo(pl, tr, info):
    """Núcleo completo: 3 pernas (cilindros) + culatras sup/inf (jugos)."""
    centros, r, (zc0, zc1) = _col_info(tr, info)
    yoke_h = 1.6 * r if info else tr.nucleo.altura_culatra
    # pernas (da culatra inferior à superior)
    for cx in centros:
        pl.add_mesh(pv.Cylinder(center=(cx * S, 0, (zc0 + zc1) / 2 * S),
                                direction=(0, 0, 1), radius=r * S,
                                height=(zc1 - zc0) * S, resolution=48),
                    color=COR_NUCLEO, smooth_shading=True)
    # culatras (jugos) horizontais ligando as pernas, abaixo e acima da janela
    x0, x1 = centros[0], centros[-1]
    for (za, zb) in ((zc0 - yoke_h, zc0), (zc1, zc1 + yoke_h)):
        pl.add_mesh(_box((x0 - r, x1 + r, -r, r, za, zb)), color=COR_NUCLEO,
                    smooth_shading=True)


def _bobinas(pl, specs):
    for cx, ri, re, z0, z1, cor in specs:
        tubo = _tubo(cx, ri, re, z0, z1)
        pl.add_mesh(tubo, color=cor, smooth_shading=True, opacity=0.95)


def _campo_eletrico_vol(pl, specs, dims, U, nx=120, ny=90, nz=40):
    """Campo elétrico bobina->tanque como VOLUME (irradia da bobina à parede).

    Quente = campo alto (distância crítica, perto da bobina);
    frio = campo baixo (folga segura, perto do tanque).
    Modelo coaxial simplificado por coluna: E = U / (r·ln(R/r0)).
    """
    # raio externo e faixa z por coluna
    cols = {}
    for cx, _ri, re, z0, z1, _c in specs:
        c = cols.setdefault(cx, {"r": 0.0, "z0": z0, "z1": z1})
        c["r"] = max(c["r"], re)
        c["z0"], c["z1"] = min(c["z0"], z0), max(c["z1"], z1)
    if not cols:
        return
    hx, hy = dims["hx"], dims["hy"]
    r0 = max(c["r"] for c in cols.values())
    R = r0 + max(hy - r0, 1.0)
    zc0 = min(c["z0"] for c in cols.values())
    zc1 = max(c["z1"] for c in cols.values())

    xs = np.linspace(-hx, hx, nx)
    ys = np.linspace(-hy, hy, ny)
    zs = np.linspace(zc0, zc1, nz)
    X, Y, _Z = np.meshgrid(xs, ys, zs, indexing="ij")
    E = np.zeros_like(X)
    for cx, c in cols.items():
        r = np.hypot(X - cx, Y)
        rc = np.clip(r, c["r"], R)
        Ec = U / (rc * np.log(R / c["r"]))
        E = np.maximum(E, Ec)

    grid = pv.ImageData(
        dimensions=(nx, ny, nz),
        spacing=(2 * hx / (nx - 1) * S, 2 * hy / (ny - 1) * S,
                 (zc1 - zc0) / (nz - 1) * S),
        origin=(-hx * S, -hy * S, zc0 * S))
    grid["E (kV/mm)"] = E.flatten(order="F")
    emin, emax = float(E.min()), float(E.max())
    bar = dict(title="Campo E (kV/mm)", color="white", title_font_size=14,
               label_font_size=11, n_labels=5, vertical=True,
               position_x=0.90, position_y=0.12, height=0.7, width=0.05)
    # frio (seguro): visível, só levemente transparente -> quente (crítico): opaco.
    # Piso de opacidade mantém o azul visível; decaimento p/ transparente bem menor.
    opac = [0.14, 0.18, 0.24, 0.32, 0.45, 0.65, 0.9]
    pl.add_volume(grid, scalars="E (kV/mm)", cmap="turbo", clim=[emin, emax],
                  opacity=opac, opacity_unit_distance=max(hy, hx) * S * 0.25,
                  scalar_bar_args=bar, show_scalar_bar=True)


def _armadura_param(pl, tr):
    """Armadura paramétrica (fallback sem DXF): frame azul translúcido."""
    a = tr.armadura
    centros = tr.centros_pernas_x()
    rmax = tr.raio_externo_max()
    hw = tr.extensao_x_pa() / 2 + a.folga_lateral
    hd = rmax + a.folga_lateral
    z_top = tr.altura_total_pa()
    m = a.montante
    pecas = [_box((-hw, hw, -hd, hd, -a.espessura, 0.0)),
             _box((-hw, hw, -hd, hd, z_top, z_top + a.espessura))]
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = sx * (hw - m / 2), sy * (hd - m / 2)
            pecas.append(_box((cx - m / 2, cx + m / 2, cy - m / 2, cy + m / 2,
                               0.0, z_top)))
    zb0 = -a.espessura - a.base_altura
    pecas.append(_box((-hw, hw, -hd, hd, zb0, -a.espessura)))
    for sx in (-1, 1):
        cx = sx * (hw * 0.6)
        pecas.append(_box((cx - m, cx + m, -hd, hd, zb0 - a.base_altura, zb0)))
    for pc in pecas:
        pl.add_mesh(pc, color=a.cor, opacity=a.opacidade, smooth_shading=True,
                    specular=0.4, specular_power=12)
        pl.add_mesh(pc.extract_feature_edges(), color="#bfe3f0", line_width=1)


def _armadura_hull(pl, tr, dxf):
    """Armadura = silhueta REAL do DXF (visual hull azul translúcido)."""
    from . import dxf_hull
    mesh = dxf_hull.hull_zup(dxf)
    a = tr.armadura
    pl.add_mesh(mesh, color=a.cor, opacity=a.opacidade, smooth_shading=True,
                specular=0.3, specular_power=12)
    pl.add_mesh(mesh.extract_feature_edges(feature_angle=35), color="#bfe3f0",
                line_width=1)


# ----------------------------------------------------------------- tanque
def _contorno_oblongo(hx, hy, n=28):
    a, b = hx, hy
    sx = max(a - b, 1.0)
    pts = []
    for k in range(n):                        # semicírculo direito (-90 -> +90)
        t = -np.pi / 2 + np.pi * k / (n - 1)
        pts.append((sx + b * np.cos(t), b * np.sin(t)))
    for k in range(n):                        # semicírculo esquerdo (+90 -> +270)
        t = np.pi / 2 + np.pi * k / (n - 1)
        pts.append((-sx + b * np.cos(t), b * np.sin(t)))
    return np.array(pts)


def _tanque(pl, tr, dims, corte):
    cor = tr.tanque.cor
    op = 0.0 if corte else max(0.0, min(float(tr.tanque.opacidade), 1.0))
    z0, z1 = dims["z0"], dims["z1"]
    if tr.tanque.tipo == "oblongo":
        c = _contorno_oblongo(dims["hx"], dims["hy"])
        n = len(c)
        anel0 = np.column_stack([c[:, 0], c[:, 1], np.full(n, z0)]) * S
        anel1 = np.column_stack([c[:, 0], c[:, 1], np.full(n, z1)]) * S
        poly = pv.PolyData(np.vstack([anel0, anel1]))
        faces = []
        for i in range(n):
            j = (i + 1) % n
            faces += [4, i, j, n + j, n + i]
        poly.faces = np.array(faces)
        if op > 0:
            pl.add_mesh(poly, color=cor, opacity=op, smooth_shading=True,
                        specular=0.5, specular_power=15)
        for anel in (anel0, anel1):
            loop = np.vstack([anel, anel[0]])
            pl.add_mesh(pv.lines_from_points(loop), color="#7fb3c4", line_width=3)
    else:
        box = _box((dims["cx"] - dims["hx"], dims["cx"] + dims["hx"],
                    dims["cy"] - dims["hy"], dims["cy"] + dims["hy"], z0, z1))
        if op > 0:
            pl.add_mesh(box, color=cor, opacity=op, smooth_shading=True,
                        specular=0.5, specular_power=15)
        pl.add_mesh(box.extract_feature_edges(), color="#7fb3c4", line_width=3)


# ----------------------------------------------------------------- cotas
def _cotas(pl, tr, specs, dims):
    if not specs:
        return
    rmax = max(re for _, _, re, *_ in specs)
    centros = sorted({cx for cx, *_ in specs})
    z0 = min(s[3] for s in specs)
    z1 = max(s[4] for s in specs)
    zc = (z0 + z1) / 2
    xc = centros[len(centros) // 2]
    cor = "#f5c542"
    pts, labels = [], []

    def cota(a, b, val, nome):
        pl.add_mesh(pv.Line(np.array(a) * S, np.array(b) * S), color=cor,
                    line_width=4)
        pts.append((((np.array(a) + np.array(b)) / 2) * S).tolist())
        labels.append(f"{nome} {val:.0f} mm")

    if len(centros) > 1:
        cota((centros[0] + rmax, 0, zc), (centros[1] - rmax, 0, zc),
             (centros[1] - centros[0]) - 2 * rmax, "entre fases")
    cota((xc, rmax, zc), (xc, dims["hy"], zc), dims["hy"] - rmax, "bob<->tanque")
    cota((centros[-1] + rmax, 0, zc), (dims["hx"], 0, zc),
         dims["hx"] - (centros[-1] + rmax), "bob<->ponta")
    cota((xc, 0, z1), (xc, 0, dims["z1"]), dims["z1"] - z1, "topo<->tampa")
    cota((xc, 0, 0), (xc, 0, dims["z0"]), -dims["z0"], "fundo<->nucleo")

    pl.add_point_labels(np.array(pts), labels, font_size=11, text_color="white",
                        shape_color="#1b2838", shape_opacity=0.7, point_size=6,
                        point_color=cor, always_visible=True)


# ----------------------------------------------------------------- build
def _aplicar_vista(pl, vista):
    if vista.startswith("Frontal"):
        pl.view_xz()
    elif vista.startswith("Lateral"):
        pl.view_yz()
    elif vista.startswith("Superior"):
        pl.view_xy()
    else:
        pl.view_isometric()


def construir(tr: Transformador, opts: dict, off_screen=False):
    dxf = opts.get("dxf") or ""
    info = None
    if dxf and os.path.exists(dxf):
        try:
            from . import dxf_hull
            info = dxf_hull.info_dxf(dxf)
        except Exception as e:
            print("[dxf] falhou ao ler:", e)
            info = None

    corte = opts.get("vista", "") == "Corte frontal"
    analise = bool(opts.get("analise_interacao", False))
    dims = _tank_dims(tr, info)
    specs = _coil_specs(tr, info)

    pl = pv.Plotter(off_screen=off_screen, window_size=(1400, 900))
    pl.set_background(FUNDO)
    try:
        pl.enable_depth_peeling(10)
    except Exception:
        pass

    if opts.get("mostrar_nucleo", True):
        _nucleo(pl, tr, info)
    if opts.get("mostrar_bobinas", True):
        _bobinas(pl, specs)
    if analise:
        try:
            _campo_eletrico_vol(pl, specs, dims, float(opts.get("U", 70.0)))
        except Exception as e:
            print("[campo] falhou:", e)
    if opts.get("mostrar_armadura", True):
        if info:
            _armadura_hull(pl, tr, dxf)
        else:
            _armadura_param(pl, tr)
    if opts.get("mostrar_tanque", True):
        _tanque(pl, tr, dims, corte)
    if opts.get("cotas", True):
        _cotas(pl, tr, specs, dims)

    modo = "DXF" if info else "paramétrico"
    pl.add_text(f"trafo3d — {modo}", font_size=10, color="white")
    _aplicar_vista(pl, opts.get("vista", "Isométrica"))
    return pl


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("params")
    ap.add_argument("--shot", default=None)
    a = ap.parse_args(argv)
    with open(a.params, "r", encoding="utf-8") as f:
        dados = json.load(f)
    tr = Transformador.from_dict(dados["transformador"])
    opts = dados.get("opcoes", {})
    pl = construir(tr, opts, off_screen=bool(a.shot))
    if a.shot:
        pl.screenshot(a.shot)
        print("PNG:", a.shot)
    else:
        pl.show(title="trafo3d — 3D (PyVista)")


if __name__ == "__main__":
    sys.exit(main())
