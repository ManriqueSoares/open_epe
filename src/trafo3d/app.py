"""Aplicação Flet (janela desktop): painel de controle do modelo + folgas.

O 3D roda em janela própria do PyVista (motor VTK), lançada como processo
separado — robusto, sem WebView/navegador. O painel Flet:
  - edita dimensões (fictícias), vista, exibição de partes e análise;
  - gerencia uma LISTA de enrolamentos concêntricos (adicionar/remover);
  - mostra um PREVIEW (PNG off-screen) que atualiza a cada mudança;
  - calcula e lista as FOLGAS geométricas principais (mm);
  - abre a JANELA 3D INTERATIVA com um clique.

Rodar:  .venv\\Scripts\\python.exe -m src.trafo3d.app
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile

import flet as ft

from .model import Transformador, Enrolamento, cor_enrol
from .view3d import VISTAS
from . import analysis as an
from . import analysis_efcd as efcd


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYEXE = sys.executable

# Campos estáticos: (chave, rótulo, (objeto, atributo))
CAMPOS = {
    "Núcleo": [
        ("nuc_diam", "Diâmetro da perna", ("nucleo", "diametro_perna")),
        ("nuc_jan", "Altura da janela", ("nucleo", "altura_janela")),
        ("nuc_cul", "Altura da culatra", ("nucleo", "altura_culatra")),
        ("nuc_passo", "Passo entre fases", ("nucleo", "passo_fases")),
    ],
    "Armadura (azul)": [
        ("arm_e", "Espessura clamp", ("armadura", "espessura")),
        ("arm_fl", "Folga lateral", ("armadura", "folga_lateral")),
        ("arm_m", "Montante", ("armadura", "montante")),
        ("arm_b", "Base/pés", ("armadura", "base_altura")),
    ],
    "Tanque (folgas)": [
        ("tq_fl", "Folga lateral (X)", ("tanque", "folga_lateral")),
        ("tq_ft", "Folga frente/trás (Y)", ("tanque", "folga_frente_tras")),
        ("tq_ft2", "Folga topo", ("tanque", "folga_topo")),
        ("tq_ff", "Folga fundo", ("tanque", "folga_fundo")),
    ],
}


def main(page: ft.Page):
    page.title = "trafo3d — Parte Ativa + Tanque"
    page.padding = 0
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window.width = 1180
    page.window.height = 860
    page.window.min_width = 960
    page.window.min_height = 660

    tr = Transformador()
    opts = {
        "mostrar_nucleo": True, "mostrar_bobinas": True, "mostrar_armadura": True,
        "mostrar_tanque": True, "analise_interacao": False,
        "vista": "Isométrica", "cotas": True, "dxf": "",
    }

    file_picker = ft.FilePicker()
    try:
        page.services.append(file_picker)
    except Exception:
        pass

    tmpdir = tempfile.mkdtemp(prefix="trafo3d_")
    params_path = os.path.join(tmpdir, "params.json")
    preview_path = os.path.join(tmpdir, "preview.png")
    proc3d = {"p": None}

    campos_ref: dict[str, ft.TextField] = {}
    enrol_refs: list[dict] = []            # [{ri, re, h}] alinhado a tr.enrolamentos
    enrol_box = ft.Column(spacing=6)
    folgas_box = ft.Column(spacing=2)
    status = ft.Text("", size=12)
    preview_img = ft.Image(src="", fit=ft.BoxFit.CONTAIN, expand=True,
                           border_radius=8)

    # ------------------------------------------------------------- modelo/IO
    def aplicar_campos() -> bool:
        ok = True

        def ler(tf):
            val = float(str(tf.value).replace(",", "."))
            if val <= 0:
                raise ValueError
            return val

        for itens in CAMPOS.values():
            for chave, _rot, (obj, attr) in itens:
                tf = campos_ref[chave]
                try:
                    setattr(getattr(tr, obj), attr, ler(tf))
                    tf.error_text = None
                except (ValueError, TypeError):
                    tf.error_text = "inválido"
                    ok = False
        for e, ref in zip(tr.enrolamentos, enrol_refs):
            for attr, tf in (("raio_int", ref["ri"]), ("raio_ext", ref["re"]),
                             ("altura", ref["h"])):
                try:
                    setattr(e, attr, ler(tf))
                    tf.error_text = None
                except (ValueError, TypeError):
                    tf.error_text = "inv"
                    ok = False
        return ok

    def escrever_params():
        try:
            opts["U"] = float(str(u_field.value).replace(",", "."))
        except (ValueError, TypeError, NameError):
            opts["U"] = 70.0
        with open(params_path, "w", encoding="utf-8") as f:
            json.dump({"transformador": tr.to_dict(), "opcoes": opts}, f)

    def folgas():
        ti = tr.tanque_interno()
        c = tr.centros_pernas_x()
        rmax = tr.raio_externo_max()
        linhas = [
            ("Bobina ext ↔ ponta (X)", ti["hx"] - (c[-1] + rmax)),
            ("Bobina ext ↔ parede (Y)", ti["hy"] - rmax),
            ("Entre fases", tr.nucleo.passo_fases - 2 * rmax),
            ("Topo PA ↔ tampa", ti["z1"] - (tr.altura_total_pa()
                                            + tr.armadura.espessura)),
        ]
        # folgas radiais entre enrolamentos vizinhos
        for a, b in zip(tr.enrolamentos, tr.enrolamentos[1:]):
            linhas.append((f"{a.nome} ↔ {b.nome} (radial)", b.raio_int - a.raio_ext))
        return linhas

    def atualizar_folgas():
        ctrl = [ft.Text("Folgas geométricas (mm)", weight=ft.FontWeight.BOLD, size=13)]
        for nome, val in folgas():
            cor = ft.Colors.RED_700 if val < 0 else ft.Colors.BLACK
            ctrl.append(ft.Row([
                ft.Text(nome, size=12, expand=True),
                ft.Text(f"{val:.0f}", size=12, weight=ft.FontWeight.BOLD, color=cor),
            ]))
        folgas_box.controls = ctrl

    # --------------------------------------------------------------- preview
    def gerar_preview():
        try:
            r = subprocess.run(
                [PYEXE, "-m", "src.trafo3d.view3d", params_path,
                 "--shot", preview_path],
                cwd=ROOT, capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and os.path.exists(preview_path):
                with open(preview_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                preview_img.src = f"data:image/png;base64,{b64}"
                return True
            print(r.stderr[-1000:] if r.stderr else "sem stderr")
        except Exception as ex:
            print("preview erro:", ex)
        return False

    def atualizar(_=None):
        valido = aplicar_campos()
        escrever_params()
        atualizar_folgas()
        ok = gerar_preview()
        if ok:
            msg = "Modelo atualizado" if valido else "Campos inválidos ignorados"
            status.value = f"{msg} • vista: {opts['vista']}"
            status.color = ft.Colors.GREEN_800 if valido else ft.Colors.ORANGE_800
        else:
            status.value = "⚠ Falha ao gerar preview (veja o console)."
            status.color = ft.Colors.ORANGE_800
        page.update()

    def abrir_3d(_=None):
        aplicar_campos()
        escrever_params()
        p = proc3d["p"]
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
        proc3d["p"] = subprocess.Popen(
            [PYEXE, "-m", "src.trafo3d.view3d", params_path], cwd=ROOT)
        status.value = "Janela 3D interativa aberta (rotacione/zoom)."
        status.color = ft.Colors.BLUE_800
        page.update()

    # ----------------------------------------------------- campos estáticos
    def campo(chave, rotulo, valor, largura=150):
        tf = ft.TextField(
            label=rotulo, value=f"{valor:g}", width=largura, dense=True,
            text_size=13, suffix=ft.Text("mm", size=11, color=ft.Colors.GREY_600),
            on_submit=atualizar, on_blur=atualizar)
        campos_ref[chave] = tf
        return tf

    def secoes_estaticas():
        blocos = []
        for sec, itens in CAMPOS.items():
            linhas, linha = [], []
            for chave, rotulo, (obj, attr) in itens:
                linha.append(campo(chave, rotulo, getattr(getattr(tr, obj), attr)))
                if len(linha) == 2:
                    linhas.append(ft.Row(linha, spacing=8)); linha = []
            if linha:
                linhas.append(ft.Row(linha, spacing=8))
            blocos.append(ft.Container(
                content=ft.Column([ft.Text(sec, weight=ft.FontWeight.BOLD, size=13,
                                           color=ft.Colors.BLUE_900)] + linhas,
                                  spacing=6),
                padding=ft.Padding(10, 8, 10, 8), border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.5, ft.Colors.BLUE_50)))
        return blocos

    # ----------------------------------------------------- enrolamentos (lista)
    def tf_enrol(valor):
        return ft.TextField(value=f"{valor:g}", width=78, dense=True, text_size=12,
                            on_submit=atualizar, on_blur=atualizar)

    def render_enrol():
        enrol_refs.clear()
        rows = [ft.Row([
            ft.Container(width=18), ft.Text("nome", size=11, width=52),
            ft.Text("r_int", size=11, width=78), ft.Text("r_ext", size=11, width=78),
            ft.Text("altura", size=11, width=78),
        ], spacing=6)]
        for i, e in enumerate(tr.enrolamentos):
            cor = e.cor or cor_enrol(i)
            ref = {"ri": tf_enrol(e.raio_int), "re": tf_enrol(e.raio_ext),
                   "h": tf_enrol(e.altura)}
            enrol_refs.append(ref)

            def remover(_, idx=i):
                if len(tr.enrolamentos) > 1:
                    tr.enrolamentos.pop(idx)
                    render_enrol()
                    atualizar()

            rows.append(ft.Row([
                ft.Container(width=18, height=18, border_radius=4, bgcolor=cor),
                ft.Text(e.nome, size=12, width=52),
                ref["ri"], ref["re"], ref["h"],
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=18,
                              tooltip="remover", on_click=remover),
            ], spacing=6))

        def adicionar(_):
            rmax = tr.raio_externo_max()
            i = len(tr.enrolamentos)
            tr.enrolamentos.append(Enrolamento(
                nome=f"E{i + 1}", raio_int=rmax + 20, raio_ext=rmax + 70,
                altura=800.0, cor=cor_enrol(i)))
            render_enrol()
            atualizar()

        rows.append(ft.TextButton("Adicionar enrolamento", icon=ft.Icons.ADD,
                                  on_click=adicionar))
        enrol_box.controls = rows

    # ------------------------------------------------------------- switches
    def make_switch(label, attr, cor=None):
        def on_change(e):
            opts[attr] = e.control.value
            atualizar()
        return ft.Switch(label=label, value=opts[attr], on_change=on_change,
                         active_color=cor)

    sw_nucleo = make_switch("Núcleo", "mostrar_nucleo")
    sw_bob = make_switch("Bobinas", "mostrar_bobinas", ft.Colors.GREEN)
    sw_arm = make_switch("Armadura", "mostrar_armadura", ft.Colors.CYAN)
    sw_tq = make_switch("Tanque", "mostrar_tanque", ft.Colors.BLUE)
    sw_cotas = make_switch("Cotas", "cotas", ft.Colors.AMBER)

    def on_vista(e):
        opts["vista"] = e.control.value
        atualizar()

    dd_vista = ft.Dropdown(
        label="Vista", value=opts["vista"],
        options=[ft.DropdownOption(key=k, text=k) for k in VISTAS],
        on_select=on_vista, width=300, dense=True)

    def on_analise(e):
        opts["analise_interacao"] = e.control.value
        atualizar()

    sw_analise = ft.Switch(label="Interação tanque ↔ bobina (gradiente)",
                           value=opts["analise_interacao"], on_change=on_analise,
                           active_color=ft.Colors.PURPLE)

    # DXF + tipo de tanque
    dxf_label = ft.Text("DXF: nenhum (modo paramétrico)", size=11,
                        color=ft.Colors.GREY_700)

    async def carregar_dxf(e):
        files = await file_picker.pick_files(
            dialog_title="Selecione o DXF da parte ativa",
            allowed_extensions=["dxf", "DXF"], allow_multiple=False)
        if files and files[0].path:
            opts["dxf"] = files[0].path
            dxf_label.value = f"DXF: {os.path.basename(files[0].path)}"
            dxf_label.color = ft.Colors.GREEN_800
            atualizar()

    def remover_dxf(e):
        opts["dxf"] = ""
        dxf_label.value = "DXF: nenhum (modo paramétrico)"
        dxf_label.color = ft.Colors.GREY_700
        atualizar()

    def on_tipo(e):
        tr.tanque.tipo = e.control.value
        atualizar()

    dd_tipo = ft.Dropdown(
        label="Tanque", value=tr.tanque.tipo,
        options=[ft.DropdownOption(key="retangular", text="Retangular"),
                 ft.DropdownOption(key="oblongo", text="Oblongo")],
        on_select=on_tipo, width=300, dense=True)

    def on_opac(e):
        tr.tanque.opacidade = round(float(e.control.value), 2)
        atualizar()

    sl_opac = ft.Slider(min=0.0, max=1.0, divisions=20, value=tr.tanque.opacidade,
                        label="{value}", on_change_end=on_opac, expand=True)

    def restaurar(_):
        nonlocal tr
        tr = Transformador()
        for itens in CAMPOS.values():
            for chave, _rot, (obj, attr) in itens:
                campos_ref[chave].value = f"{getattr(getattr(tr, obj), attr):g}"
        render_enrol()
        atualizar()

    render_enrol()

    painel = ft.Container(
        width=380, bgcolor=ft.Colors.GREY_50, padding=14,
        content=ft.Column([
            ft.Text("trafo3d", size=22, weight=ft.FontWeight.BOLD,
                    color=ft.Colors.BLUE_900),
            ft.Text("Parte ativa + tanque — 3D (PyVista)", size=12,
                    color=ft.Colors.GREY_700),
            ft.Divider(height=8),
            ft.Row([dd_vista], spacing=8),
            dd_tipo,
            ft.Row([ft.Text("Transparência do tanque", size=12), sl_opac],
                   spacing=6),
            ft.Container(content=ft.Column([
                ft.Row([
                    ft.FilledTonalButton("Carregar DXF", icon=ft.Icons.UPLOAD_FILE,
                                         on_click=carregar_dxf),
                    ft.IconButton(ft.Icons.CLOSE, tooltip="remover DXF",
                                  on_click=remover_dxf),
                ], spacing=6),
                dxf_label,
            ], spacing=4), padding=10, border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.4, ft.Colors.CYAN_50)),
            ft.Container(content=ft.Column([
                ft.Text("Análise", weight=ft.FontWeight.BOLD, size=13,
                        color=ft.Colors.PURPLE_900), sw_analise], spacing=4),
                padding=10, border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.4, ft.Colors.PURPLE_50)),
            ft.Text("Exibir", weight=ft.FontWeight.BOLD, size=13),
            ft.Row([sw_nucleo, sw_bob, sw_arm], spacing=2),
            ft.Row([sw_tq, sw_cotas], spacing=2),
            ft.Divider(height=8),
            ft.Text("Enrolamentos (concêntricos)", weight=ft.FontWeight.BOLD,
                    size=14, color=ft.Colors.BLUE_900),
            ft.Container(content=enrol_box, padding=ft.Padding(8, 8, 8, 8),
                         border_radius=8,
                         bgcolor=ft.Colors.with_opacity(0.5, ft.Colors.GREEN_50)),
            ft.Divider(height=8),
            ft.Text("Dimensões (fictícias)", weight=ft.FontWeight.BOLD, size=14),
            *secoes_estaticas(),
            ft.TextButton("Restaurar padrões",
                          icon=ft.Icons.SETTINGS_BACKUP_RESTORE, on_click=restaurar),
        ], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True))

    direita = ft.Container(
        expand=True, padding=14,
        content=ft.Column([
            ft.Row([
                ft.FilledButton("Abrir janela 3D interativa",
                                icon=ft.Icons.VIEW_IN_AR, on_click=abrir_3d),
                ft.OutlinedButton("Atualizar preview", icon=ft.Icons.REFRESH,
                                  on_click=atualizar),
            ], spacing=8),
            ft.Container(content=preview_img, expand=True, border_radius=8,
                         bgcolor="#0d1117", padding=4),
            ft.Container(content=folgas_box, padding=ft.Padding(4, 6, 4, 4)),
            status,
        ], spacing=8, expand=True))

    aba_modelo = ft.Row([painel, direita], spacing=0, expand=True)

    # ===================================================== ABA ANÁLISE
    def _info():
        p = opts.get("dxf") or ""
        if p and os.path.exists(p):
            try:
                from . import dxf_hull
                return dxf_hull.info_dxf(p)
            except Exception as ex:
                print("info_dxf:", ex)
        return None

    def _datauri(b):
        return f"data:image/png;base64,{base64.b64encode(b).decode()}"

    u_field = ft.TextField(label="Tensão da bobina U", value="70", width=170,
                           dense=True, text_size=13,
                           suffix=ft.Text("kV", size=11, color=ft.Colors.GREY_600))
    gap_dd = ft.Dropdown(label="Folga para os gráficos", width=260, dense=True,
                         options=[])
    curvas: list[dict] = []
    curva_refs: list[dict] = []
    curvas_box = ft.Column(spacing=6)
    ativa = ft.RadioGroup(content=curvas_box)
    dist_table = ft.Column(spacing=2)
    status2 = ft.Text("", size=12)
    img_tensao = ft.Image(src="", fit=ft.BoxFit.CONTAIN, width=540)
    img_stress = ft.Image(src="", fit=ft.BoxFit.CONTAIN, width=540)
    img_heat = ft.Image(src="", fit=ft.BoxFit.CONTAIN, width=420)

    def _tf(val, w):
        return ft.TextField(value=str(val), width=w, dense=True, text_size=12)

    def render_curvas():
        curva_refs.clear()
        rows = [ft.Row([
            ft.Text("ativa", size=10, width=42), ft.Text("Nome", size=10, width=92),
            ft.Text("A", size=10, width=58), ft.Text("B", size=10, width=58),
            ft.Text("Stress máx", size=10, width=70),
        ], spacing=6)]
        for i, c in enumerate(curvas):
            ref = {"nome": _tf(c["nome"], 92), "A": _tf(c["A"], 58),
                   "B": _tf(c["B"], 58), "smax": _tf(c["smax"], 70)}
            curva_refs.append(ref)

            def rem(_, idx=i):
                curvas.pop(idx)
                render_curvas()
                page.update()

            rows.append(ft.Row([
                ft.Radio(value=str(i)), ref["nome"], ref["A"], ref["B"], ref["smax"],
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=16, on_click=rem),
            ], spacing=6))

        def add(_):
            curvas.append({"nome": f"Curva {len(curvas) + 1}", "A": "", "B": "",
                           "smax": ""})
            render_curvas()
            page.update()

        rows.append(ft.TextButton("Adicionar curva", icon=ft.Icons.ADD, on_click=add))
        curvas_box.controls = rows

    def ler_curvas():
        for c, ref in zip(curvas, curva_refs):
            c["nome"] = ref["nome"].value
            c["A"], c["B"], c["smax"] = ref["A"].value, ref["B"].value, ref["smax"].value

    def curva_ativa():
        try:
            i = int(ativa.value)
            c = curvas[i]
            return c["nome"], float(c["A"]), float(c["B"])
        except (ValueError, TypeError, IndexError):
            return "", None, None

    render_curvas()

    def _perfil_sel(U, gaps):
        sel = [g for g in gaps if g[0] == gap_dd.value] or gaps
        if not sel:
            return None
        _n, r0, d = sel[0]
        if r0 <= 0 or d <= 0:
            return None
        return efcd.perfil_campo(U, r0, d)

    def calcular_analise(_=None):
        ler_curvas()
        try:
            U = float(str(u_field.value).replace(",", "."))
        except (ValueError, TypeError):
            status2.value = "⚠ Tensão U inválida."
            status2.color = ft.Colors.ORANGE_800
            page.update()
            return
        info = _info()
        gaps = an.gaps_eletricos(tr, info)
        gap_dd.options = [ft.DropdownOption(key=g[0], text=g[0]) for g in gaps]
        if gap_dd.value not in [g[0] for g in gaps]:
            gap_dd.value = gaps[0][0] if gaps else None
        nome, A, B = curva_ativa()

        linhas = efcd.analisar_gaps(U, [(g[0], g[1], g[2]) for g in gaps], A, B)
        tab = [ft.Row([
            ft.Text("Gap", size=12, width=150, weight=ft.FontWeight.BOLD),
            ft.Text("d [mm]", size=12, width=60, weight=ft.FontWeight.BOLD),
            ft.Text("E_max [kV/mm]", size=12, width=110, weight=ft.FontWeight.BOLD),
            ft.Text("MS [%]", size=12, width=70, weight=ft.FontWeight.BOLD),
        ], spacing=6)]
        for L in linhas:
            ms = L["MS"]
            cor = (ft.Colors.BLACK if ms is None else
                   (ft.Colors.RED_700 if ms < 0 else ft.Colors.GREEN_800))
            tab.append(ft.Row([
                ft.Text(L["nome"], size=12, width=150),
                ft.Text(f"{L['d']:.0f}", size=12, width=60),
                ft.Text("-" if L["E_max"] is None else f"{L['E_max']:.3f}",
                        size=12, width=110),
                ft.Text("-" if ms is None else f"{ms:.1f}", size=12, width=70,
                        color=cor, weight=ft.FontWeight.BOLD),
            ], spacing=6))
        dist_table.controls = tab

        perf = _perfil_sel(U, gaps)
        if perf:
            img_tensao.src = _datauri(efcd.fig_to_png(efcd.fig_tensao(perf)))
            img_stress.src = _datauri(efcd.fig_to_png(efcd.fig_stress(perf, A, B, nome)))
            img_heat.src = _datauri(efcd.fig_to_png(efcd.fig_campo2d(perf)))
        status2.value = ("Análise calculada." if A and B else
                         "Análise calculada (sem curva Epd → sem margem).")
        status2.color = ft.Colors.GREEN_800
        page.update()

    async def exportar_pdf(_=None):
        ler_curvas()
        try:
            U = float(str(u_field.value).replace(",", "."))
        except (ValueError, TypeError):
            status2.value = "⚠ Tensão U inválida."
            status2.color = ft.Colors.ORANGE_800
            page.update()
            return
        info = _info()
        gaps = an.gaps_eletricos(tr, info)
        nome, A, B = curva_ativa()
        perf = _perfil_sel(U, gaps)
        if perf is None:
            status2.value = "⚠ Sem folga válida para o relatório."
            status2.color = ft.Colors.ORANGE_800
            page.update()
            return
        path = await file_picker.save_file(
            dialog_title="Salvar relatório PDF", file_name="relatorio_trafo3d.pdf",
            allowed_extensions=["pdf"])
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        resumo = [("Tensão U", f"{U:g} kV"),
                  ("Modo", "DXF" if info else "paramétrico"),
                  ("Folga dos gráficos", gap_dd.value or "-")]
        efcd.gerar_pdf(path, "trafo3d — Relatório de Distâncias Elétricas", resumo,
                       perf, efcd.analisar_gaps(
                           U, [(g[0], g[1], g[2]) for g in gaps], A, B),
                       A, B, nome)
        try:
            os.startfile(path)   # type: ignore[attr-defined]
        except Exception:
            pass
        status2.value = f"PDF salvo: {os.path.basename(path)}"
        status2.color = ft.Colors.BLUE_800
        page.update()

    gap_dd.on_select = calcular_analise

    analise_painel = ft.Container(
        width=470, bgcolor=ft.Colors.GREY_50, padding=14,
        content=ft.Column([
            ft.Text("Análise de distâncias elétricas", size=18,
                    weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
            ft.Text("Campo bobina → tanque. Modelo coaxial SIMPLIFICADO "
                    "E(d)=U/(d·ln(R/r0)) — trocar por FEM/planilha depois.",
                    size=11, color=ft.Colors.GREY_700),
            ft.Divider(height=8),
            ft.Row([u_field, gap_dd], spacing=8),
            ft.Divider(height=8),
            ft.Text("Curvas de suportabilidade  Epd(d)=A·d^-B  [kV/mm]",
                    weight=ft.FontWeight.BOLD, size=13, color=ft.Colors.ORANGE_900),
            ft.Text("Preencha com seus dados / norma.", size=11,
                    color=ft.Colors.GREY_700),
            ativa,
            ft.Divider(height=8),
            ft.Row([
                ft.FilledButton("Calcular", icon=ft.Icons.CALCULATE,
                                on_click=calcular_analise),
                ft.OutlinedButton("Exportar PDF", icon=ft.Icons.PICTURE_AS_PDF,
                                  on_click=exportar_pdf),
            ], spacing=8),
            status2,
        ], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True))

    analise_dir = ft.Container(
        expand=True, padding=14,
        content=ft.Column([
            ft.Text("Distâncias elétricas", weight=ft.FontWeight.BOLD, size=14),
            dist_table,
            ft.Divider(),
            ft.Row([img_tensao, img_heat], wrap=True, spacing=10),
            img_stress,
        ], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True))

    aba_analise = ft.Row([analise_painel, analise_dir], spacing=0, expand=True)

    tabs = ft.Tabs(
        length=2, expand=True,
        content=ft.Column([
            ft.TabBar(tabs=[ft.Tab(label="Modelo 3D", icon=ft.Icons.VIEW_IN_AR),
                            ft.Tab(label="Análise", icon=ft.Icons.INSIGHTS)]),
            ft.TabBarView(controls=[aba_modelo, aba_analise], expand=True),
        ], expand=True))

    page.add(tabs)
    atualizar()
    calcular_analise()   # popula a aba Análise já na abertura


def run():
    ft.run(main)


if __name__ == "__main__":
    run()
