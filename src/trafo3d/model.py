"""Modelo de dados do transformador.

Todas as medidas em milímetros (mm). Os valores padrão são FICTÍCIOS,
apenas para gerar o modelo 3D. No futuro virão de folhas de cálculo/análises.

Sistema de coordenadas:
    X -> largura   (as 3 fases se alinham ao longo de X)
    Y -> profundidade
    Z -> altura    (eixo vertical; eixo das bobinas/pernas)
Origem no centro da base da parte ativa.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


# Paleta categórica dos enrolamentos (interno -> externo), estilo EPA.
PALETA = ["#3a86ff", "#2ec4b6", "#8ac926", "#ffbe0b", "#fb5607", "#d62828"]


def cor_enrol(i: int) -> str:
    return PALETA[i % len(PALETA)]


@dataclass
class Nucleo:
    """Núcleo de 3 pernas (core-type trifásico)."""
    n_fases: int = 3
    diametro_perna: float = 320.0      # diâmetro equivalente da perna
    altura_janela: float = 1000.0      # altura livre entre culatras
    altura_culatra: float = 260.0      # altura (espessura vertical) de cada culatra
    passo_fases: float = 900.0         # distância entre centros de pernas vizinhas
    #   (> 2*raio_ext do enrolamento mais externo p/ não sobrepor)


@dataclass
class Enrolamento:
    """Um enrolamento concêntrico (anel) em torno de uma perna."""
    nome: str
    raio_int: float
    raio_ext: float
    altura: float
    cor: str = ""                      # vazio -> definida pela paleta no índice


def _enrolamentos_padrao() -> list[Enrolamento]:
    return [
        Enrolamento("BT", 185.0, 245.0, 950.0, PALETA[0]),
        Enrolamento("AT", 270.0, 335.0, 900.0, PALETA[1]),
        Enrolamento("REG", 360.0, 400.0, 820.0, PALETA[2]),
    ]


@dataclass
class Armadura:
    """Ferragens de aperto + base/pés, desenhadas como silhueta translúcida.

    Envolvem a parte ativa (clamps topo/fundo, montantes de canto, base e pés).
    """
    espessura: float = 90.0            # espessura das vigas de clamp (topo/fundo)
    folga_lateral: float = 70.0        # quanto ultrapassa as bobinas em X/Y
    montante: float = 70.0             # seção dos montantes de canto
    base_altura: float = 70.0          # altura da base/pés sob o núcleo
    cor: str = "#64b1d0"               # azul claro (estilo hull do EPA)
    opacidade: float = 0.45


@dataclass
class Tanque:
    """Invólucro. Definido por folgas (clearances) a partir da parte ativa."""
    folga_lateral: float = 170.0       # folga em X (parede <-> enrol mais externo)
    folga_frente_tras: float = 180.0   # folga em Y
    folga_topo: float = 220.0          # folga acima da parte ativa
    folga_fundo: float = 150.0         # folga abaixo da parte ativa (base/pés)
    espessura_parede: float = 12.0
    cor: str = "#9fc0d4"
    tipo: str = "retangular"           # "retangular" ou "oblongo"
    opacidade: float = 0.5             # transparência das paredes (0=invisível, 1=sólido)


@dataclass
class Transformador:
    nucleo: Nucleo = field(default_factory=Nucleo)
    enrolamentos: list[Enrolamento] = field(default_factory=_enrolamentos_padrao)
    armadura: Armadura = field(default_factory=Armadura)
    tanque: Tanque = field(default_factory=Tanque)

    # ---- geometria derivada ----------------------------------------------
    def centros_pernas_x(self) -> list[float]:
        n = self.nucleo.n_fases
        p = self.nucleo.passo_fases
        x0 = -(n - 1) * p / 2.0
        return [x0 + i * p for i in range(n)]

    def raio_externo_max(self) -> float:
        return max((e.raio_ext for e in self.enrolamentos), default=0.0)

    def altura_total_pa(self) -> float:
        """Altura da parte ativa (culatra inf + janela + culatra sup)."""
        return self.nucleo.altura_janela + 2 * self.nucleo.altura_culatra

    def extensao_x_pa(self) -> float:
        """Largura ocupada (fase externa a fase externa, pelo enrol externo)."""
        centros = self.centros_pernas_x()
        return (centros[-1] - centros[0]) + 2 * self.raio_externo_max()

    def z_enrolamento(self, e: Enrolamento) -> tuple[float, float]:
        z0 = self.nucleo.altura_culatra + (self.nucleo.altura_janela - e.altura) / 2
        return z0, z0 + e.altura

    def tanque_interno(self) -> dict:
        """Dimensões internas do tanque (centro e meias-extensões).

        Engloba a parte ativa inteira, inclusive armadura e base/pés.
        """
        t = self.tanque
        a = self.armadura
        rmax = self.raio_externo_max()
        hx = self.extensao_x_pa() / 2 + a.folga_lateral + t.folga_lateral
        hy = rmax + a.folga_lateral + t.folga_frente_tras
        z_base = -a.base_altura - a.espessura - t.folga_fundo
        z_topo = self.altura_total_pa() + a.espessura + t.folga_topo
        return {
            "cx": 0.0, "cy": 0.0, "hx": hx, "hy": hy,
            "z0": z_base, "z1": z_topo,
            "cz": (z_base + z_topo) / 2, "hz": (z_topo - z_base) / 2,
        }

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transformador":
        return cls(
            nucleo=Nucleo(**d["nucleo"]),
            enrolamentos=[Enrolamento(**e) for e in d["enrolamentos"]],
            armadura=Armadura(**d["armadura"]),
            tanque=Tanque(**d["tanque"]),
        )
