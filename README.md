# trafo3d — Visualização 3D da Parte Ativa + Tanque

Protótipo em **Python** para visualizar em 3D a **parte ativa** de um
transformador (núcleo + bobinas + armaduras/ferragens) dentro do **tanque**, com
diferentes vistas e uma **análise por gradiente de cores** da interação
tanque ↔ bobina.

- **Painel de controle:** **Flet** (janela desktop) — dimensões, vistas, exibição
  de partes, análise, preview e tabela de folgas.
- **3D:** **PyVista / VTK** em **janela nativa própria** (interativa: rotaciona,
  zoom, pan), no estilo do 3D "oficial" do EPA APP. Roda como **processo
  separado** — sem navegador, sem WebView.

> Todas as medidas atuais são **fictícias**, só para gerar o modelo. No futuro
> virão de folhas de cálculo / análises (ver "Próximos passos").

## Como rodar

```bat
run.bat
```
ou:
```bat
.venv\Scripts\python.exe -m src.trafo3d.app
```

Abre a janela do **painel** (Flet). Clique em **"Abrir janela 3D interativa"**
para a cena PyVista. O **preview** no painel atualiza sozinho a cada mudança.

Recriar o ambiente, se necessário:
```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## O que a aplicação faz

O app tem **quatro abas**: **Modelo 3D**, **Análise**, **Buchas** e **TCs**.

### Aba "Modelo 3D"
- **Vista:** Isométrica, Frontal (XZ), Lateral (YZ), Superior (XY), Corte frontal.
- **Tanque:** retangular ou oblongo.
- **Parte ativa:** lida da fonte fixa `data/parte_ativa.json` (ver abaixo).
- **Análise (gradiente):** liga o **campo elétrico bobina → tanque** como VOLUME
  na cena 3D — irradia da bobina até a parede: **quente = crítico** (perto),
  **frio = seguro** (longe). Visto de cima fica como o heatmap da aba Análise.
  Usa a tensão U e o modelo coaxial simplificado.
- **Exibir:** núcleo, bobinas, armadura, tanque, cotas.
- **Enrolamentos:** lista editável (adicionar/remover).
- **Dimensões (mm):** campos editáveis (núcleo, armadura, folgas).
- **Preview** (PNG off-screen) + **tabela de folgas geométricas**.

### Aba "Análise" (distâncias elétricas, estilo EFCD)
- **Campo bobina → tanque** por um **modelo coaxial SIMPLIFICADO**
  `E(d) = U / (d · ln(R/r0))` — rotulado como tal, para trocar por FEM/planilha.
- Entrada: **Tensão U [kV]** da bobina e a **folga** a analisar.
- **Curvas de suportabilidade** `Epd(d)=A·d^-B` em tabela **editável** (você
  preenche A, B, stress máx — nada de valores de norma inventados).
- Saídas: **Tensão × distância**, **Campo: Stress × Suportabilidade** (margem de
  segurança), **heatmap 2D** do campo, **tabela de distâncias** (E_max, MS%).
- **Exportar PDF:** relatório com parâmetros, tabela e gráficos.

### Aba "Buchas" (raio de proteção + inclinação, estilo EPA)
- Usa a bucha **fixa** (`data/bucha.json`) — o perfil 2D é desenhado na elevação
  e **revolucionado** para o 3D. Sem seleção manual.
- Metodologia espelhada do EPA (números seus/do banco, não inventados):
  `passo_min = R_ar + d_apl + toque`; folga = passo − R_ar − d_apl; a
  **inclinação das pontas** afasta os pontos de contato por `braço·sen(θ)`.
- Entradas: **nº buchas, R_ar, Ø aplicação, toque, passo, U, inclinação**.
- Saídas:
  - **Vista superior**: campo (mesmo gradiente turbo) + Ø + raio de proteção +
    folga entre pares (verde/vermelho);
  - **Elevação**: perfis reais inclinados + pontos de contato + proteção;
  - **Estudo de inclinação**: folga no ar × ângulo (+ menor ângulo que resolve);
  - **Tabela de contato** entre buchas vizinhas (OK / CONTATO);
  - **Abrir 3D das buchas**: janela PyVista com buchas revolucionadas, inclinação,
    esferas de proteção e **campo elétrico volumétrico** irradiando dos terminais.

### Aba "TCs" (espaço para TCs no caneco)
- **Zona segura** para o TC (livre de campo): cilindro de altura **L6** e raio
  `caneco/2 − 40`, começando 40 mm abaixo do flange; abaixo de L6 o espaço
  **decai num cone de 60°**. Gradiente: **azul dentro** (seguro) → **quente saindo**.
- Entradas: **Ø caneco, L6, raio da bucha**, e por **fase (H1/H2/H3)** a lista de
  **TCs** (nome, DINT, DEXT, ALT, KG). Regras do EPA: 40 mm parede/vizinho,
  3 mm empilhados, **empilhar por peso** (mais pesado embaixo).
- Usa a **bucha, o passo e a inclinação** definidos na aba Buchas.
- Saídas:
  - **Elevação 2D** com o gradiente, a zona segura, o caneco e os TCs empilhados
    (amarelo = cabe, vermelho = fura);
  - **Viabilidade** por fase (radial, cone, altura da pilha vs L6);
  - **Abrir 3D dos TCs**: janela PyVista com buchas inclinadas, canecos, TCs
    empilhados e o **volume do gradiente** da zona segura (mesmo turbo).

Cena 3D (PyVista) — dois modos:

**Paramétrico (sem DXF):**
- **Núcleo:** pernas (cilindros) + culatras/jugos (caixas).
- **Enrolamentos:** LISTA de anéis concêntricos por fase (paleta categórica).
  Adicione/remova no painel — sem limite fixo.
- **Armadura:** frame azul translúcido paramétrico (clamps + montantes + base/pés).

**Fonte FIXA de coordenadas — sem seleção manual, sem DXF no runtime:**
O app lê sempre de `data/parte_ativa.json` (+ `parte_ativa_hull.ply`) e
`data/bucha.json` (definidos em `config.py`). Esses arquivos são **só
coordenadas**, gerados dos DXFs por `build_data.py`. Os DXFs de origem **não
ficam no projeto** (não são versionados). Para regenerar a partir dos seus
desenhos locais: `python -m src.trafo3d.build_data <parte_ativa.dxf> <bucha.dxf>`.
Cada fase mostra **3 anéis concêntricos**.
- **Armadura = silhueta REAL** (visual hull das 3 vistas do DXF), azul
  translúcida — reproduz clamps/estrutura/base/pés de verdade.
- **Bobinas e centros de coluna** extraídos do próprio DXF (vista superior).
- **Dimensões, base e cotas** vêm do DXF.

Comum aos dois:
- Bobinas coloridas por fase; com a análise ligada, um **campo elétrico
  volumétrico** irradia da bobina ao tanque (quente = crítico, frio = seguro).
- **Tanque retangular OU oblongo** (seletor), translúcido + arestas; PA dentro.
- **Cotas:** entre fases, bob↔tanque, bob↔ponta, topo↔tampa, fundo↔núcleo.
- **Corte frontal:** oculta as faces translúcidas do tanque (só as arestas).

## Arquitetura

```
data/             # fontes FIXAS de medidas = só COORDENADAS (sem DXF no runtime)
├── parte_ativa.json       # dimensões, base, centros, 3 anéis, z das bobinas
├── parte_ativa_hull.ply   # malha do hull (coordenadas, gerada)
└── bucha.json             # perfil da bucha (envelope + segmentos)
# os DXFs de origem NÃO ficam no projeto (ver build_data.py p/ regenerar)
src/trafo3d/
├── config.py     # caminhos das fontes em data/
├── build_data.py # gera os .json/.ply a partir de data/source/*.dxf
├── model.py      # dataclasses (núcleo, enrolamentos[], armadura, tanque) + derivados
├── analysis.py   # campo de cor: folga bobina -> parede do tanque (numpy)
├── view3d.py     # ★ viewer PyVista (janela nativa). Modos paramétrico e DXF
├── app.py        # ★ app Flet (abas Modelo 3D + Análise); lança o view3d
├── analysis_efcd.py  # campo elétrico (coaxial simplificado) + gráficos + PDF
├── buchas.py     # estudo de buchas: proteção, inclinação, contato + figuras 2D
├── buchas_view3d.py  # viewer PyVista das buchas (revolução + campo + proteção)
├── tcs.py        # espaço para TCs: zona segura (L6+cone 60°), empilhamento, 2D
├── tcs_view3d.py # viewer PyVista dos TCs (canecos + TCs + gradiente da zona)
├── dxf_hull.py   # visual hull do DXF (Z-up) + extração de bobinas/centros
└── dxf_io.py     # leitor de DXF (3 vistas) — portado do EPA (weg_dxf.py)
```

Sistema de coordenadas: **X** = largura (fases), **Y** = profundidade,
**Z** = altura.

### Decisões de projeto
- Flet 1.0 não tem 3D nativo e seu **WebView não roda em janela desktop no
  Windows** (testado). Por isso o 3D usa **PyVista em janela própria**, lançado
  como processo separado — padrão já usado no EPA APP para evitar conflito de
  loop de eventos. Sem embedding web = sem a fragilidade que víamos.
- O painel comunica com o viewer por um **JSON de parâmetros** (`params.json`).

### Viewer isolado (sem o painel)
```bat
.venv\Scripts\python.exe -m src.trafo3d.view3d params.json
.venv\Scripts\python.exe -m src.trafo3d.view3d params.json --shot preview.png
```

## Próximos passos (sugeridos)
- `io_folha.py`: ler dimensões de `.xlsx/.xlsm` (openpyxl) → `Transformador`.
- Alturas das bobinas no modo DXF a partir das vistas frontal/lateral (hoje são
  estimadas como fração da altura do conjunto).
- Mais análises: bobina↔núcleo, verificação contra distâncias de norma (semáforo),
  colorir também as paredes do tanque; campos elétrico/magnético (como no EPA).
- Live-update da janela 3D (watch no `params.json`) em vez de reabrir.
- Canecos/buchas e comutador (alinhar com o EPA APP).

