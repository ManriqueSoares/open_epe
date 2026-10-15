"""
weg_dxf.py — Leitura do DXF do CORE AND COIL (gerado pelo SolidWorks).

Dois cenários suportados:

  • MODO 3D — o DXF traz a geometria com coordenadas Z reais; projetamos nas
    vistas frontal (XZ), lateral (YZ) e superior (XY).

  • MODO 2D MULTI-VISTA — o SolidWorks exporta cada vista de anotação em um
    **layout** diferente do DXF (ex.: `Model` = frontal, `_Superior` = topo,
    `_Right` = lateral). Lemos todos os layouts e mapeamos cada um para a vista
    correta pela geometria (as três vistas compartilham dimensões duas a duas).

A classe `GeometriaCC` expõe a mesma interface nos dois modos
(`projecao`, `bbox_2d`, `dimensoes`, `segmentos_3d`), de forma que o restante do
app (tanque, vistas, export, 3D) funciona sem saber qual foi a origem.

Dependência: ezdxf.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


Segmento = list[tuple[float, float, float]]      # polilinha 3D
Segmento2D = list[tuple[float, float]]           # polilinha 2D (uma vista)

VISTAS = ("frontal", "lateral", "superior")

# Palavras-chave nos nomes de layout do SolidWorks → vista.
_KW = {
    "frontal":  ("front", "frontal", "model", "alcado"),
    "superior": ("top", "superior", "sup", "planta"),
    "lateral":  ("right", "left", "lateral", "side", "direita", "esquerda"),
}


# Uma primitiva redonda (CIRCLE/ARC) preservada para o export CAD, em 2D.
#   tipo : 'circle' | 'arc'
#   cx,cy: centro (mm)          r: raio (mm)
#   a0,a1: ângulos (graus) — circle usa 0..360; arc usa start..end (CCW)
Primitiva2D = dict


@dataclass
class GeometriaCC:
    """Geometria do core-and-coil (mm). Funciona em modo 3D ou 2D multi-vista."""
    modo: str = "3d"                                   # '3d' | '2d_multiview'
    segmentos: list[Segmento] = field(default_factory=list)        # modo 3D
    vistas: dict[str, list[Segmento2D]] = field(default_factory=dict)  # modo 2D
    # Círculos/arcos verdadeiros por vista base (frontal/lateral/superior),
    # já normalizados — alimentam o export CAD com CIRCLE/ARC reais (com centro
    # que aceita snap), em vez das polilinhas facetadas.
    primitivas: dict[str, list[Primitiva2D]] = field(default_factory=dict)
    # Índices, por vista base, dos segmentos de `vistas` que são a versão
    # facetada de uma primitiva redonda — o export os descarta e desenha a
    # primitiva no lugar (evita geometria duplicada).
    circ_idx: dict[str, set] = field(default_factory=dict)
    dims: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (comprimento, largura, altura)
    n_fases: int = 3
    caminho: str = ""
    eh_3d: bool = False
    # Posicionamento real da parte ativa dentro do conjunto (mm), derivado do DXF:
    #   offset_x = deslocamento horizontal do eixo do núcleo em relação ao centro
    #              do conjunto (o suporte do comutador ocupa um lado → o núcleo
    #              fica afastado dele). >0 = núcleo deslocado no sentido +X.
    #   base_y   = altura da estrutura de base (pés/estrado) abaixo do bloco ativo;
    #              é o quanto o núcleo/bobinas começam ACIMA do fundo do tanque.
    offset_x: float = 0.0
    base_y: float = 0.0

    # ── Dimensões (comprimento, largura, altura) ──
    def dimensoes(self) -> tuple[float, float, float]:
        if self.modo == "2d_multiview":
            return self.dims
        lo, hi = self._bbox3d()
        return tuple((hi - lo).tolist())

    def _bbox3d(self):
        pts = np.array([p for seg in self.segmentos for p in seg], dtype=float)
        if len(pts) == 0:
            return np.zeros(3), np.zeros(3)
        return pts.min(axis=0), pts.max(axis=0)

    # ── Projeção / vistas ──
    def projecao(self, vista: str) -> list[Segmento2D]:
        # Vistas derivadas (traseira/lateral_direita) são o espelho horizontal
        # das vistas base — a parte ativa vista "do outro lado".
        if self.modo == "2d_multiview":
            if vista == "traseira":
                return _espelhar_x(self.vistas.get("frontal", []))
            if vista == "lateral_direita":
                return _espelhar_x(self.vistas.get("lateral", []))
            return self.vistas.get(vista, [])
        # Modo 3D: (i, j) = eixos projetados; sx = -1 espelha no horizontal.
        eixos = {
            "frontal":         (0, 2, 1), "traseira":        (0, 2, -1),
            "lateral":         (1, 2, 1), "lateral_direita": (1, 2, -1),
            "superior":        (0, 1, 1),
        }[vista]
        i, j, sx = eixos
        return [[(sx * p[i], p[j]) for p in seg] for seg in self.segmentos]

    def bbox_2d(self, vista: str) -> tuple[float, float, float, float]:
        proj = self.projecao(vista)
        pts = np.array([p for seg in proj for p in seg], dtype=float)
        if len(pts) == 0:
            return 0.0, 0.0, 0.0, 0.0
        return (pts[:, 0].min(), pts[:, 0].max(),
                pts[:, 1].min(), pts[:, 1].max())

    # ── Centro elétrico da PA (colunas do núcleo) numa vista ──
    def centro_colunas_x(self, vista: str) -> float | None:
        """X do centro das COLUNAS do núcleo (centro da PA) na vista desenhada.

        Como a vista é normalizada pelo bbox do CONJUNTO (que é assimétrico — o
        suporte do comutador estica um lado), o centro do desenho (X=0) NÃO é o
        centro elétrico da PA: as colunas ficam deslocadas. Isto devolve esse
        deslocamento (mm) para peças que devem ficar concêntricas às colunas (ex.:
        o comutador). Usa os círculos grandes (primitivas) da vista base, com o
        sinal do espelho das vistas derivadas. None se não houver círculos — aí o
        chamador cai em 0 (sem deslocamento). A superior, sem círculos próprios,
        reaproveita o deslocamento em comprimento da frontal."""
        base, mirror = _VISTA_BASE.get(vista, (vista, False))
        c = _centro_colunas(self.primitivas.get(base, []))
        if c is None:
            if base == "superior":                 # planta sem círculos → usa frontal
                return self.centro_colunas_x("frontal")
            return None
        return -c if mirror else c

    # ── Segmentos 3D (para a visualização Three.js) ──
    def segmentos_3d(self) -> list[Segmento]:
        """No modo 3D devolve a geometria real; no modo 2D reconstrói um
        core-and-coil paramétrico (cilindros) a partir das dimensões medidas."""
        if self.modo == "3d":
            return self.segmentos
        return _reconstruir_3d(self.dims, self.n_fases)

    # ── Geometria para o export CAD (polilinhas + círculos/arcos reais) ──
    def geometria_export(self, vista: str
                         ) -> tuple[list[Segmento2D], list[Primitiva2D]]:
        """Devolve (polilinhas, primitivas) de uma vista para o DXF de saída.

        As polilinhas EXCLUEM os segmentos que são a versão facetada de um
        círculo/arco; esses são devolvidos em `primitivas` para serem gravados
        como CIRCLE/ARC verdadeiros (com centro que aceita snap no CAD).
        No modo 3D (sem primitivas preservadas) devolve (projecao, [])."""
        if self.modo != "2d_multiview":
            return self.projecao(vista), []
        base, espelho = _VISTA_BASE.get(vista, (vista, False))
        segs = self.vistas.get(base, [])
        idx = self.circ_idx.get(base, set())
        polys = [s for k, s in enumerate(segs) if k not in idx]
        prims = self.primitivas.get(base, [])
        if espelho:
            polys = _espelhar_x(polys)
            prims = [_espelhar_prim(p) for p in prims]
        return polys, prims


# ─── Conversão de entidades ezdxf → segmentos ────────────────────────────────

# Vista pedida → (vista base armazenada, precisa espelhar no horizontal?).
# As vistas derivadas são o espelho X das bases (a parte ativa "do outro lado").
_VISTA_BASE = {
    "frontal":         ("frontal", False),
    "traseira":        ("frontal", True),
    "lateral":         ("lateral", False),
    "lateral_direita": ("lateral", True),
    "superior":        ("superior", False),
}


def _espelhar_x(proj: list[Segmento2D]) -> list[Segmento2D]:
    """Espelha uma vista 2D no eixo horizontal (x → -x): gera as vistas
    traseira/lateral-direita a partir da frontal/lateral."""
    return [[(-x, y) for x, y in seg] for seg in proj]


def _espelhar_prim(p: "Primitiva2D") -> "Primitiva2D":
    """Espelha uma primitiva redonda no eixo horizontal (cx → -cx).

    Círculo: só o centro muda. Arco: além do centro, o espelho troca a
    orientação (CCW→CW), então o intervalo [a0, a1] vira [180-a1, 180-a0]
    para que o CAD volte a percorrê-lo no sentido anti-horário."""
    q = dict(p)
    q["cx"] = -p["cx"]
    if p.get("tipo") == "arc":
        q["a0"] = 180.0 - p["a1"]
        q["a1"] = 180.0 - p["a0"]
    return q


def _ponto(v) -> tuple[float, float, float]:
    return (float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0)


def _arco_para_pontos(cx, cy, r, ang0, ang1, n=24) -> Segmento:
    a0, a1 = np.radians(ang0), np.radians(ang1)
    if a1 < a0:
        a1 += 2 * np.pi
    ts = np.linspace(a0, a1, n)
    return [(cx + r * np.cos(t), cy + r * np.sin(t), 0.0) for t in ts]


def _extrair(container) -> tuple[list[Segmento], list["Primitiva2D"]]:
    """Extrai (segmentos, primitivas) de um container ezdxf.

    Todo CIRCLE/ARC é achatado em polilinha (para bbox/vistas/colisão, que o
    resto do app usa) E registrado como primitiva redonda com `seg_idx` = a
    posição do seu segmento facetado, de forma que o export possa trocar um
    pelo outro sem duplicar geometria."""
    segs: list[Segmento] = []
    prims: list[Primitiva2D] = []
    for e in container:
        t = e.dxftype()
        try:
            if t == "LINE":
                segs.append([_ponto(e.dxf.start), _ponto(e.dxf.end)])
            elif t == "LWPOLYLINE":
                pts = [(_p[0], _p[1], e.dxf.elevation) for _p in e.get_points("xy")]
                if e.closed and pts:
                    pts.append(pts[0])
                segs.append([(float(x), float(y), float(z)) for x, y, z in pts])
            elif t == "POLYLINE":
                pts = [_ponto(v.dxf.location) for v in e.vertices]
                if e.is_closed and pts:
                    pts.append(pts[0])
                segs.append(pts)
            elif t == "CIRCLE":
                c = e.dxf.center
                prims.append({"tipo": "circle", "cx": float(c[0]), "cy": float(c[1]),
                              "r": float(e.dxf.radius), "a0": 0.0, "a1": 360.0,
                              "seg_idx": len(segs)})
                segs.append(_arco_para_pontos(c[0], c[1], e.dxf.radius, 0, 360, 48))
            elif t == "ARC":
                c = e.dxf.center
                prims.append({"tipo": "arc", "cx": float(c[0]), "cy": float(c[1]),
                              "r": float(e.dxf.radius),
                              "a0": float(e.dxf.start_angle),
                              "a1": float(e.dxf.end_angle), "seg_idx": len(segs)})
                segs.append(_arco_para_pontos(
                    c[0], c[1], e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle))
            elif t == "SPLINE":
                pts = [_ponto(p) for p in e.flattening(0.5)]
                if pts:
                    segs.append(pts)
            elif t == "3DFACE":
                vs = [_ponto(e.dxf.vtx0), _ponto(e.dxf.vtx1),
                      _ponto(e.dxf.vtx2), _ponto(e.dxf.vtx3)]
                segs.append(vs + [vs[0]])
            elif t == "INSERT":
                try:
                    sub_segs, sub_prims = _extrair(e.explode())
                    base = len(segs)
                    for sp in sub_prims:
                        sp["seg_idx"] += base
                    segs.extend(sub_segs)
                    prims.extend(sub_prims)
                except Exception:
                    pass
        except Exception:
            continue
    return segs, prims


def _extrair_segmentos(container) -> list[Segmento]:
    """Compat.: só os segmentos (usado onde as primitivas não interessam)."""
    return _extrair(container)[0]


def _centros_circulos(container) -> list[float]:
    """X dos centros de CIRCLE (para estimar o nº de fases na vista superior)."""
    xs = []
    for e in container:
        if e.dxftype() == "CIRCLE":
            xs.append(float(e.dxf.center[0]))
    return xs


def _bbox2d(segs) -> tuple[float, float, float, float, float, float]:
    pts = np.array([p for s in segs for p in s], dtype=float)
    xmin, xmax = pts[:, 0].min(), pts[:, 0].max()
    ymin, ymax = pts[:, 1].min(), pts[:, 1].max()
    return xmin, xmax, ymin, ymax, xmax - xmin, ymax - ymin


# ─── Normalização de uma vista 2D ────────────────────────────────────────────

def _normalizar(segs, vista) -> list[Segmento2D]:
    """Centra a vista no eixo do comprimento/largura e apoia a base em y=0.

    frontal/lateral → base (y) em 0, centrado em x;
    superior        → centrado em x e y (vista de planta).
    """
    ox, oy = _offset_normalizacao(segs, vista)
    return [[(p[0] - ox, p[1] - oy) for p in s] for s in segs]


def _offset_normalizacao(segs, vista) -> tuple[float, float]:
    """(ox, oy) subtraído por `_normalizar` — reutilizado para as primitivas,
    de modo que círculos/arcos fiquem alinhados com os segmentos da vista."""
    xmin, xmax, ymin, ymax, w, h = _bbox2d(segs)
    cx = (xmin + xmax) / 2
    if vista == "superior":
        return cx, (ymin + ymax) / 2
    return cx, ymin


def _normalizar_prims(prims, segs, vista) -> list["Primitiva2D"]:
    """Aplica o mesmo offset de `_normalizar` aos centros das primitivas."""
    ox, oy = _offset_normalizacao(segs, vista)
    out = []
    for p in prims:
        q = dict(p)
        q["cx"] = p["cx"] - ox
        q["cy"] = p["cy"] - oy
        out.append(q)
    return out


def _centro_colunas(prims) -> float | None:
    """X do centro elétrico da PA (colunas do núcleo) a partir das primitivas
    redondas JÁ normalizadas de uma vista.

    Agrupa os círculos grandes em COLUNAS (as bobinas/limbos concêntricos
    partilham o mesmo cx; o gap entre colunas é ≥ 2·rmax, os anéis de uma coluna
    ficam colados — robusto ao nº de anéis por limbo e a um círculo espúrio) e
    devolve o meio das colunas EXTERNAS. None se não houver círculos grandes."""
    circ = [p for p in prims if p.get("tipo") == "circle"]
    if not circ:
        return None
    rmax = max(p["r"] for p in circ)
    cxs = sorted(p["cx"] for p in circ if p["r"] >= 0.5 * rmax)
    if not cxs:
        return None
    gap = 2.0 * rmax
    cols = [[cxs[0]]]
    for x in cxs[1:]:
        if x - cols[-1][-1] <= gap:
            cols[-1].append(x)
        else:
            cols.append([x])
    centros = [sum(c) / len(c) for c in cols]
    return (centros[0] + centros[-1]) / 2.0


# ─── Mapeamento dos layouts → vistas ─────────────────────────────────────────

def _classificar(candidatos):
    """Recebe [(nome, segs, w, h, circ_xs)] e devolve dict vista→segs + dims.

    Estratégia: primeiro tenta pelo nome do layout; o que sobrar é resolvido
    pela geometria (as três vistas compartilham dimensões duas a duas:
    comprimento = maior largura, altura = maior altura, largura = a menor).
    """
    # 1) Dimensões globais a partir de todas as larguras/alturas.
    ws = [c[2] for c in candidatos]
    hs = [c[3] for c in candidatos]
    comprimento = max(ws + hs)                       # maior dimensão geral
    altura = max(hs)                                 # maior altura
    largura = min(ws + hs)                           # menor dimensão geral
    tol = 0.06                                       # 6 %

    def casa(a, b):
        return abs(a - b) <= tol * max(a, b, 1)

    vistas: dict[str, list] = {}
    usados = set()

    # 2) Por nome de layout.
    for i, (nome, segs, w, h, _cx) in enumerate(candidatos):
        low = nome.lower().lstrip("*_ ")
        for vista, kws in _KW.items():
            if vista not in vistas and any(k in low for k in kws):
                vistas[vista] = segs
                usados.add(i)
                break

    # 3) Por geometria (preenche o que faltou).
    perfis = {
        "frontal":  (comprimento, altura),
        "superior": (comprimento, largura),
        "lateral":  (largura, altura),
    }
    for vista, (pw, ph) in perfis.items():
        if vista in vistas:
            continue
        for i, (nome, segs, w, h, _cx) in enumerate(candidatos):
            if i in usados:
                continue
            if casa(w, pw) and casa(h, ph):
                vistas[vista] = segs
                usados.add(i)
                break

    return vistas, (comprimento, largura, altura)


# ─── Posicionamento real da parte ativa (offset horizontal + base) ───────────

# Standoff fundo do tanque → base do núcleo (mm). A parte ativa apoia em
# calços/estrado e o núcleo NÃO nasce no fundo. O DXF deste projeto não traz
# cotas (DIMENSION/TEXT) que permitam extrair geometricamente — constante
# ajustável, lida do detalhamento (image.png ≈ 72,5 mm).
BASE_NUCLEO_MM = 72.5


def _layout_por_vista(doc) -> dict:
    """Mapeia cada layout do DXF para a vista (frontal/superior/lateral) pelo nome."""
    res: dict[str, object] = {}
    for nome in doc.layout_names():
        low = nome.lower().lstrip("*_ ")
        for vista, kws in _KW.items():
            if vista not in res and any(k in low for k in kws):
                res[vista] = doc.layout(nome)
                break
    return res


def _circulos_grandes(lay) -> list[tuple[float, float, float]]:
    """Círculos com raio ≥ 50% do maior — i.e. as colunas do núcleo / bobinas,
    descartando furos de parafuso e pequenos detalhes."""
    cs = [(float(e.dxf.center[0]), float(e.dxf.center[1]), float(e.dxf.radius))
          for e in lay if e.dxftype() == "CIRCLE"]
    if not cs:
        return []
    rmax = max(c[2] for c in cs)
    return [c for c in cs if c[2] >= 0.5 * rmax]


def derivar_posicionamento(doc) -> tuple[float, float]:
    """Deriva (offset_x, base_y) do DXF (mm). Ver campos de GeometriaCC.

    • offset_x: centro das colunas do núcleo (círculos grandes) menos o centro
      do bounding box do conjunto, medido na vista frontal. Como o tanque é
      centrado no conjunto, esse é o deslocamento do núcleo dentro do tanque
      (o suporte do comutador estica o conjunto p/ um lado → o núcleo fica
      afastado dele). Robusto e medido diretamente da geometria.
    • base_y: standoff fundo→base do núcleo. O DXF não traz cota que permita
      derivá-lo da geometria, então usamos a constante BASE_NUCLEO_MM lida do
      detalhamento (image.png ≈ 72,5 mm). Ajuste por projeto se necessário.
    """
    lays = _layout_por_vista(doc)
    front = lays.get("frontal")
    sup = lays.get("superior")

    # ── offset_x (geometria) ──
    offset_x = 0.0
    if front is not None:
        segs = _extrair_segmentos(front)
        xs = [p[0] for s in segs for p in s]
        if xs:
            assembly_cx = (min(xs) + max(xs)) / 2
            big = _circulos_grandes(front)
            if not big and sup is not None:
                big = _circulos_grandes(sup)
            nucleo_cx = sum(c[0] for c in big) / len(big) if big else assembly_cx
            offset_x = nucleo_cx - assembly_cx

    return offset_x, BASE_NUCLEO_MM


def ler_dxf(caminho: str) -> GeometriaCC:
    """Carrega o DXF do core-and-coil (modo 3D ou 2D multi-vista)."""
    import ezdxf

    doc = ezdxf.readfile(caminho)
    msp = doc.modelspace()
    segs_msp = _extrair_segmentos(msp)
    if not segs_msp:
        raise ValueError("Nenhuma geometria reconhecível no modelspace do DXF.")

    zs = np.array([p[2] for seg in segs_msp for p in seg])
    eh_3d = float(zs.max() - zs.min()) > 1.0

    # ── MODO 3D ──
    if eh_3d:
        geo = GeometriaCC(modo="3d", segmentos=segs_msp, caminho=caminho, eh_3d=True)
        lo, hi = geo._bbox3d()
        cx, cy, z0 = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]
        geo.segmentos = [[(x - cx, y - cy, z - z0) for x, y, z in s] for s in segs_msp]
        geo.dims = tuple((hi - lo).tolist())
        return geo

    # ── MODO 2D MULTI-VISTA: junta modelspace + paperspace layouts ──
    # prims_map: id(segs) → primitivas redondas daquele layout (para o export).
    prims_map: dict[int, list] = {}
    candidatos = []
    for nome in doc.layout_names():
        lay = doc.layout(nome)
        segs, prims = _extrair(lay)
        if len(segs) < 5:
            continue
        prims_map[id(segs)] = prims
        _xmn, _xmx, _ymn, _ymx, w, h = _bbox2d(segs)
        candidatos.append((nome, segs, w, h, _centros_circulos(lay)))

    if not candidatos:
        _, prims_msp = _extrair(msp)
        prims_map[id(segs_msp)] = prims_msp
        candidatos = [("Model", segs_msp, *_bbox2d(segs_msp)[4:6], _centros_circulos(msp))]

    vistas_raw, dims = _classificar(candidatos)
    if "frontal" not in vistas_raw:
        # fallback: usa o modelspace como frontal.
        if id(segs_msp) not in prims_map:
            prims_map[id(segs_msp)] = _extrair(msp)[1]
        vistas_raw["frontal"] = segs_msp

    # Estima nº de fases pelos círculos da vista superior (centros X distintos).
    n_fases = 3
    for nome, segs, w, h, circ_xs in candidatos:
        if vistas_raw.get("superior") is segs and circ_xs:
            grupos = sorted(set(round(x / 50.0) for x in circ_xs))
            if 1 <= len(grupos) <= 6:
                n_fases = len(grupos)
            break

    # Posicionamento real da parte ativa (antes da normalização, que perde a
    # posição absoluta) — deslocamento p/ o comutador e altura da base.
    try:
        offset_x, base_y = derivar_posicionamento(doc)
    except Exception:
        offset_x, base_y = 0.0, 0.0

    vistas = {v: _normalizar(s, v) for v, s in vistas_raw.items()}
    # Primitivas redondas (CIRCLE/ARC) normalizadas por vista, + índices dos
    # segmentos facetados correspondentes (que o export descarta).
    primitivas: dict[str, list] = {}
    circ_idx: dict[str, set] = {}
    for v, s in vistas_raw.items():
        prims = prims_map.get(id(s), [])
        primitivas[v] = _normalizar_prims(prims, s, v)
        circ_idx[v] = {p["seg_idx"] for p in prims}

    # Re-centra cada vista no CENTRO ELÉTRICO da PA (colunas do núcleo), não no
    # centro do bbox. O layout do SolidWorks pode trazer as bobinas levemente fora
    # do centro do bbox (estruturas/protrusões assimétricas de um lado); centrar no
    # bbox deslocava a PA do eixo do tanque nas vistas — ~1 mm na lateral, onde as
    # 3 fases se sobrepõem em profundidade. Agora o eixo x=0 do desenho passa pelas
    # colunas e o tanque (centrado em 0) fica concêntrico com o núcleo. Frontal/
    # superior já vêm com as colunas no centro (dc≈0) → no-op.
    for v in list(vistas):
        dc = _centro_colunas(primitivas[v])
        if not dc:
            continue
        vistas[v] = [[(x - dc, y) for (x, y) in s] for s in vistas[v]]
        for p in primitivas[v]:
            p["cx"] -= dc
    return GeometriaCC(modo="2d_multiview", vistas=vistas, dims=dims,
                       primitivas=primitivas, circ_idx=circ_idx,
                       n_fases=n_fases, caminho=caminho, eh_3d=False,
                       offset_x=offset_x, base_y=base_y)


# ─── Reconstrução paramétrica 3D (a partir das dimensões medidas) ────────────

def _cilindro_wire(cx, r, h, z0=0.0, segs=24) -> list[Segmento]:
    out = []
    for z in (z0, z0 + h):
        ts = np.linspace(0, 2 * np.pi, segs + 1)
        out.append([(cx + r * np.cos(t), r * np.sin(t), z) for t in ts])
    for k in range(0, segs, 4):
        t = 2 * np.pi * k / segs
        x, y = cx + r * np.cos(t), r * np.sin(t)
        out.append([(x, y, z0), (x, y, z0 + h)])
    return out


def _reconstruir_3d(dims, n_fases) -> list[Segmento]:
    """Core-and-coil paramétrico para o 3D quando a origem é 2D multi-vista."""
    C, W, A = dims
    n = max(int(n_fases), 1)
    passo = C / n
    r_at = min(passo, W) * 0.42
    r_nuc = r_at * 0.62
    x0 = -C / 2 + passo / 2
    out: list[Segmento] = []
    for z in (0.0, A):
        out.append([(-C / 2, 0, z), (C / 2, 0, z)])           # travessas
    for i in range(n):
        cx = x0 + i * passo
        out += _cilindro_wire(cx, r_nuc, A)                    # núcleo
        out += _cilindro_wire(cx, r_at * 0.8, A - 80)          # BT
        out += _cilindro_wire(cx, r_at, A - 120, z0=60)        # AT
    return out


# ─── Gerador de DXF 3D de exemplo (testes) ───────────────────────────────────

def gerar_dxf_exemplo(caminho: str, n_fases: int = 3) -> None:
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for seg in _reconstruir_3d((4500.0, 1200.0, 2400.0), n_fases):
        msp.add_polyline3d(seg)
    doc.saveas(caminho)


if __name__ == "__main__":
    import sys
    alvo = sys.argv[1] if len(sys.argv) > 1 else "CORE_AND_COIL.DXF"
    geo = ler_dxf(alvo)
    print("Modo:", geo.modo, "| 3D?", geo.eh_3d, "| fases:", geo.n_fases)
    print("Dimensoes (C,L,A):", tuple(round(v, 1) for v in geo.dimensoes()))
    for v in VISTAS:
        bb = geo.bbox_2d(v)
        print(f"  {v:9s}: {len(geo.projecao(v)):4d} segs  bbox="
              f"({bb[0]:.0f},{bb[1]:.0f},{bb[2]:.0f},{bb[3]:.0f})")
