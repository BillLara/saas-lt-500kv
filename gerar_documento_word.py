import os
import zipfile
import datetime
from xml.sax.saxutils import escape


def criar_docx_openxml(caminho_saida: str):
    """
    Gera um arquivo Microsoft Word (.docx) nativo no padrão Office OpenXML (ECMA-376)
    com formatação executiva completa (títulos, tabelas estilizadas, listas e blocos de destaque).
    """
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

    rels_root = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>
        <w:sz w:val="22"/>
        <w:szCs w:val="22"/>
        <w:lang w:val="pt-BR"/>
      </w:rPr>
    </w:rPrDefault>
  </w:docDefaults>
</w:styles>"""

    body_parts = []

    def p_titulo_principal(texto: str, subtitulo: str):
        body_parts.append(f"""
        <w:p>
          <w:pPr>
            <w:shd w:val="clear" w:color="auto" w:fill="0F172A"/>
            <w:spacing w:before="120" w:after="60" w:line="300" w:lineRule="auto"/>
            <w:ind w:left="140" w:right="140"/>
          </w:pPr>
          <w:r>
            <w:rPr><w:b/><w:color w:val="38BDF8"/><w:sz w:val="34"/><w:szCs w:val="34"/></w:rPr>
            <w:t>{escape(texto)}</w:t>
          </w:r>
        </w:p>
        <w:p>
          <w:pPr>
            <w:shd w:val="clear" w:color="auto" w:fill="0F172A"/>
            <w:spacing w:before="0" w:after="240" w:line="260" w:lineRule="auto"/>
            <w:ind w:left="140" w:right="140"/>
          </w:pPr>
          <w:r>
            <w:rPr><w:color w:val="E2E8F0"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr>
            <w:t>{escape(subtitulo)}</w:t>
          </w:r>
        </w:p>""")

    def p_h1(texto: str):
        body_parts.append(f"""
        <w:p>
          <w:pPr>
            <w:pBdr><w:bottom w:val="single" w:sz="12" w:space="4" w:color="0284C7"/></w:pBdr>
            <w:spacing w:before="280" w:after="120"/>
          </w:pPr>
          <w:r>
            <w:rPr><w:b/><w:color w:val="0F172A"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr>
            <w:t>{escape(texto)}</w:t>
          </w:r>
        </w:p>""")

    def p_h2(texto: str):
        body_parts.append(f"""
        <w:p>
          <w:pPr><w:spacing w:before="180" w:after="80"/></w:pPr>
          <w:r>
            <w:rPr><w:b/><w:color w:val="0369A1"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr>
            <w:t>{escape(texto)}</w:t>
          </w:r>
        </w:p>""")

    def p_texto(texto: str, negrito_prefixo: str = ""):
        r_pref = ""
        if negrito_prefixo:
            r_pref = f"""<w:r><w:rPr><w:b/><w:color w:val="0F172A"/></w:rPr><w:t xml:space="preserve">{escape(negrito_prefixo)} </w:t></w:r>"""
        body_parts.append(f"""
        <w:p>
          <w:pPr>
            <w:jc w:val="both"/>
            <w:spacing w:before="40" w:after="100" w:line="276" w:lineRule="auto"/>
          </w:pPr>
          {r_pref}
          <w:r>
            <w:rPr><w:color w:val="1E293B"/></w:rPr>
            <w:t xml:space="preserve">{escape(texto)}</w:t>
          </w:r>
        </w:p>""")

    def p_bullet(prefixo_negrito: str, texto: str):
        body_parts.append(f"""
        <w:p>
          <w:pPr>
            <w:jc w:val="both"/>
            <w:spacing w:before="30" w:after="70" w:line="264" w:lineRule="auto"/>
            <w:ind w:left="360" w:hanging="180"/>
          </w:pPr>
          <w:r><w:rPr><w:b/><w:color w:val="0284C7"/></w:rPr><w:t xml:space="preserve">• </w:t></w:r>
          <w:r><w:rPr><w:b/><w:color w:val="0F172A"/></w:rPr><w:t xml:space="preserve">{escape(prefixo_negrito)} </w:t></w:r>
          <w:r><w:rPr><w:color w:val="1E293B"/></w:rPr><w:t xml:space="preserve">{escape(texto)}</w:t></w:r>
        </w:p>""")

    def p_destaque(titulo_box: str, texto: str):
        body_parts.append(f"""
        <w:p>
          <w:pPr>
            <w:pBdr><w:left w:val="single" w:sz="24" w:space="8" w:color="0284C7"/></w:pBdr>
            <w:shd w:val="clear" w:color="auto" w:fill="F1F5F9"/>
            <w:spacing w:before="120" w:after="140" w:line="264" w:lineRule="auto"/>
            <w:ind w:left="200" w:right="200"/>
          </w:pPr>
          <w:r><w:rPr><w:b/><w:color w:val="0369A1"/></w:rPr><w:t xml:space="preserve">{escape(titulo_box)}: </w:t></w:r>
          <w:r><w:rPr><w:color w:val="0F172A"/></w:rPr><w:t xml:space="preserve">{escape(texto)}</w:t></w:r>
        </w:p>""")

    def tabela(cabecalhos, linhas):
        ths = ""
        for h in cabecalhos:
            ths += f"""
            <w:tc>
              <w:tcPr>
                <w:shd w:val="clear" w:color="auto" w:fill="0F172A"/>
                <w:tcMar><w:top w:w="80" w:type="dxa"/><w:bottom w:w="80" w:type="dxa"/><w:left w:w="120" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tcMar>
              </w:tcPr>
              <w:p>
                <w:pPr><w:spacing w:before="20" w:after="20"/></w:pPr>
                <w:r><w:rPr><w:b/><w:color w:val="FFFFFF"/><w:sz w:val="20"/></w:rPr><w:t>{escape(h)}</w:t></w:r>
              </w:p>
            </w:tc>"""

        trs = f"<w:tr>{ths}</w:tr>"
        for idx, row in enumerate(linhas):
            fill = "F8FAFC" if idx % 2 == 1 else "FFFFFF"
            tcs = ""
            for c_idx, cell in enumerate(row):
                bold_tag = "<w:b/>" if c_idx == 0 else ""
                tcs += f"""
                <w:tc>
                  <w:tcPr>
                    <w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>
                    <w:tcMar><w:top w:w="70" w:type="dxa"/><w:bottom w:w="70" w:type="dxa"/><w:left w:w="120" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tcMar>
                  </w:tcPr>
                  <w:p>
                    <w:pPr><w:spacing w:before="20" w:after="20"/></w:pPr>
                    <w:r><w:rPr>{bold_tag}<w:color w:val="1E293B"/><w:sz w:val="20"/></w:rPr><w:t xml:space="preserve">{escape(str(cell))}</w:t></w:r>
                  </w:p>
                </w:tc>"""
            trs += f"<w:tr>{tcs}</w:tr>"

        body_parts.append(f"""
        <w:tbl>
          <w:tblPr>
            <w:tblW w:w="5000" w:type="pct"/>
            <w:tblBorders>
              <w:top w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>
              <w:left w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>
              <w:bottom w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>
              <w:right w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>
              <w:insideH w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>
              <w:insideV w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>
            </w:tblBorders>
          </w:tblPr>
          {trs}
        </w:tbl>
        <w:p><w:pPr><w:spacing w:before="40" w:after="80"/></w:pPr></w:p>""")

    # =========================================================================
    # CONTEÚDO DIDÁTICO E OBJETIVO DO DOCUMENTO
    # =========================================================================
    p_titulo_principal(
        "PLATAFORMA SaaS DE GESTÃO TÁTICA E INTELIGÊNCIA PREDITIVA PARA CONSTRUÇÃO DE LINHAS DE TRANSMISSÃO",
        "Descrição Funcional, Arquitetura Operacional e Validação no Projeto Piloto LT 500 kV SE UTE GNA II – SE Campos 2"
    )

    p_h1("1. Visão Geral e Propósito da Plataforma")
    p_texto(
        "Esta plataforma SaaS (Software as a Service) autônoma e multi-tenant foi projetada especificamente para o Gestor do Empreendimento de Linhas de Transmissão (LT). Seu objetivo central é transformar apontamentos operacionais coletados em campo pelos fiscais em inteligência tática em tempo real, antecipando atrasos físicos, desvios de caminho crítico e exposições a multas contratuais."
    )
    p_destaque(
        "Premissa Arquitetural Enxuta (Zero Legados)",
        "A plataforma opera de forma 100% independente, sem necessidade de integração com ERPs pesados (SAP/Totvs), softwares legados em nuvem ou captura por satélites/drones. Toda a inteligência nasce do cruzamento entre a Baseline de Engenharia e a coleta móvel Offline-First dos fiscais no trecho."
    )

    p_h1("2. Como Funciona na Prática: O Ciclo em 4 Etapas")
    p_bullet(
        "Etapa 1 — Setup Inteligente da Baseline:",
        "O Gestor realiza o upload dos documentos fundamentais da obra: o Cronograma MS Project (.mpp), a Lista de Construção (.xlsx), a Memória de Tipificação de Fundações/Sondagens (.pdf) e os marcos do Contrato EPC. O motor de engenharia da plataforma cruza essas bases automaticamente usando o Código da Torre como chave única."
    )
    p_bullet(
        "Etapa 2 — Emissão da Ordem de Batalha (Plano de Ataque Inicial):",
        "Assim que a Baseline é validada, a IA audita conflitos técnicos (como sondagens com SPT > 30, áreas alagáveis e travessias críticas), calcula o Limiar de Risco Tolerável (%) do projeto e emite a Ordem de Batalha Inicial (OB-001), definindo as frentes de trabalho, sentidos de avanço e dimensionamento de equipes."
    )
    p_bullet(
        "Etapa 3 — Coleta de Campo Offline-First com Trava Geográfica (Geofencing):",
        "Os fiscais percorrem a faixa de servidão utilizando o aplicativo móvel leve com banco SQLite local (sem depender de internet). Em cada torre, o aplicativo valida via GPS se o fiscal está dentro do raio de 50 metros da estrutura, apresenta um checklist específico para o tipo de fundação/torre e permite relatar ocorrências por voz ou texto. Quando há sinal de rede, a fila local sincroniza com a nuvem."
    )
    p_bullet(
        "Etapa 4 — Motor de IA, Simulação de Monte Carlo e Ordens de Produção:",
        "Na nuvem, a IA recalcula proporcionalmente o avanço físico (%) de cada atividade do MS Project, atualiza a Curva S (Valor Planejado vs. Valor Agregado) e executa 2.000 iterações de Monte Carlo (Beta-PERT). Se o risco de atraso ultrapassar o Limiar da Baseline, o sistema emite automaticamente uma Ordem de Produção prescritiva para manobra de equipes e mitigação de multas."
    )

    p_h1("3. Estrutura do Cockpit Executivo (As 6 Abas da Plataforma)")
    tabela(
        ["Aba do Sistema", "Objetivo Tático", "Principais Funcionalidades e Indicadores"],
        [
            [
                "1. Cockpit Georreferenciado & Linha de Balanço",
                "Visão situacional imediata do traçado e do risco probabilístico de prazo.",
                "Mapa interativo georreferenciado (SIRGAS 2000 -> WGS84) com semáforo por torre (Verde/Amarelo/Vermelho), ficha geotécnica completa (NSPT, NA, Contingência BSE-M), Linha de Balanço linear das 86 estruturas e Painel de Monte Carlo (P10, P50, P80, P90, Histograma e Gráfico de Tornado)."
            ],
            [
                "2. Cronograma MS Project (.mpp) & Avanço IA",
                "Acompanhamento físico-financeiro automatizado dos pacotes construtivos.",
                "Leitura nativa das 92 atividades da EAP do MS Project, ordenação por ID Relativo (Linha 1 a 92) ou ID Absoluto (Unique ID), e cálculo automático do avanço (%) e Valor Agregado (EV) proporcional às torres concluídas (todas as 84 torres, 51 autoportantes, 33 estaiadas GNEL, 14 travessias ou 27 ancoragens)."
            ],
            [
                "3. Curva S & Tendência IA (EVA / Monte Carlo)",
                "Monitoramento da evolução acumulada e previsão da data real de conclusão.",
                "Gráfico vetorial interativo e tabela mensal (Set/2022 a Nov/2023) cruzando 4 curvas: Baseline Planejada (R0D), Curva Realizada de Campo, Tendência IA P50 (Mais Provável) e Tendência IA P80 (Conservadora AACE), com filtro por disciplina e alternância entre % e R$ Milhões."
            ],
            [
                "4. Ordem de Batalha & Ordens de Produção",
                "Comando e controle das frentes de ataque e ações corretivas.",
                "Diagnóstico de auditoria da Baseline, detalhamento das Frentes 01 e 02 da Ordem de Batalha (OB-001) e painel de aprovação das Ordens de Produção (OP-001 a OP-004) geradas pela IA com cálculo da multa contratual evitada (VaR P80)."
            ],
            [
                "5. Simulador App Mobile do Fiscal",
                "Operação em campo sem internet e validação de presença física.",
                "Interface móvel com fila SQLite local, validação de Geofencing (raio máximo de 50m da coordenada oficial da torre), checklists dinâmicos (torque lb.ft em estacas helicoidais, prumo e estais em torres GNEL) e gatilhos rápidos de desvios."
            ],
            [
                "6. Governança & Revisão de Baseline",
                "Controle formal de mudanças e rastreabilidade (Compliance).",
                "Registro auditável de novas versões da Baseline (V1, V2...), ajuste do Limiar de Risco Tolerável (%) e repactuação formal da Ordem de Batalha."
            ]
        ]
    )

    p_h1("4. Inteligência Artificial e Engenharia de Dados Aplicadas")
    p_h2("4.1. Cálculo Proporcional Automatizado no Cronograma")
    p_texto(
        "Em vez de exigir que o planejador digite percentuais subjetivos no MS Project, a plataforma vincula cada pacote da EAP ao seu universo exato de estruturas da Lista de Construção:"
    )
    p_bullet("Pacotes Gerais (84 torres):", "Cada torre concluída em campo adiciona automaticamente +1,1905% (1/84) ao pacote correspondente (ex: Escavação/Cravação, Concretagem, Aterramento).")
    p_bullet("Pacotes de Torres Autoportantes (51 torres):", "Vinculados exclusivamente às estruturas GNSL, GNSE, GNAA, GNAE e GNAT (+1,9608% por torre).")
    p_bullet("Pacotes de Torres Estaiadas (33 torres):", "Vinculados exclusivamente às estruturas monomastro GNEL (+3,0303% por torre).")
    p_bullet("Pacotes de Travessias (14 estruturas) e Jumpers (27 ancoragens):", "Calculados estritamente sobre as torres que possuem interferências ou cadeias de ancoragem.")

    p_h2("4.2. Modelo Estocástico de Monte Carlo (2.000 Iterações Beta-PERT)")
    p_texto(
        "Para superar a limitação de cálculos lineares simples, o motor de risco executa 2.000 sorteios probabilísticos (distribuição Beta-PERT combinada com eventos de Bernoulli) acoplados ao paralelismo das frentes da Linha de Balanço. O modelo pondera quatro vetores reais de engenharia:"
    )
    p_bullet("1. Risco Geotécnico (Doc. 40-MDE-00071):", "Probabilidade de recusa de cravação helicoidal nas 12 torres com NSPT > 30 (agravada nas 7 torres que não possuem fundação alternativa BSE-M pré-dimensionada) e necessidade de extensões metálicas adicionais nas 5 torres de solo muito mole (NSPT = 0).")
    p_bullet("2. Risco Hidrogeológico (Nota 12.11.1):", "Impacto de lâmina d'água e necessidade de ensecadeira/estiva nas 30 torres localizadas em áreas alagáveis (NA = 0,00m e afloramento mínimo de 60cm).")
    p_bullet("3. Risco de Travessias Críticas (Nota 12.4):", "Incerteza na liberação de janelas de desligamento e programação de Linha Viva nas 10 travessias elétricas (Furnas 345 kV e Enel 138 kV) e 4 rodovias estaduais (DER-RJ).")
    p_bullet("4. Risco Logístico e de Produtividade:", "Flutuação no fornecimento de componentes metálicos e no ritmo diário de montagem e lançamento de cabos.")

    p_h1("5. Síntese dos Dados Reais Validados no Projeto Piloto")
    p_texto(
        "O protótipo funcional foi integralmente calibrado com a documentação executiva real da Linha de Transmissão LT 500 kV SE UTE GNA II – SE Campos 2:"
    )
    tabela(
        ["Parâmetro do Empreendimento Piloto", "Valor / Especificação Técnica Extraída da Engenharia"],
        [
            ["Empreendimento / Contrato EPC", "LT 500 kV SE UTE GNA II – SE Campos 2 (GNA x Consórcio Alubar / Railec)"],
            ["Valor Global do Contrato (CAPEX)", "R$ 158.241.062,00 (Cláusula 19.2.3: multa diária de 0,2% a 0,5% limitada a 10% do contrato)"],
            ["Extensão Total e Geodésia", "37,464 km em Circuito Simples (SIRGAS 2000 UTM Fuso 24K – Porto do Açu a Campos dos Goytacazes/RJ)"],
            ["Total de Estruturas na Linha", "86 estruturas (84 torres numeradas das séries 0/1 a 37/2 + 2 Pórticos nas subestações)"],
            ["Tipologia Mecânica das Torres", "51 Torres Autoportantes (GNSL, GNSE, GNAA, GNAE, GNAT) e 33 Torres Estaiadas Monomastro (GNEL)"],
            ["Fundações Principais e Contingência", "Estacas Metálicas Helicoidais (HEL-091 a HEL-100) com controle de torque (Anexo I) e opção BSE-M"],
            ["Restrições Críticas Mapeadas", "30 torres em área alagável (Nota 12.11.1), 12 torres com SPT > 30 e 14 travessias críticas (Nota 12.4)"],
            ["Prazo Planejado (MS Project R0D)", "518 dias corridos totais (391 dias de Construção e Comissionamento: 19/09/2022 a 15/10/2023)"]
        ]
    )

    p_h1("6. Benefícios Diretos para o Gestor do Empreendimento")
    p_bullet("Visibilidade Fiel do Caminho Crítico:", "Elimina o descolamento entre o cronograma do escritório e a realidade física da faixa de servidão.")
    p_bullet("Auditoria Geotécnica Preventiva:", "Cruza automaticamente normas executivas com boletins de sondagem por torre antes que a máquina sofra recusa ou dano em campo.")
    p_bullet("Garantia de Presença Física (Compliance):", "A trava de Geofencing de 50m assegura que toda inspeção registrada no banco ocorreu presencialmente na praça da torre.")
    p_bullet("Proteção Financeira do Contrato (Mitigação de Multas):", "Converte desvios técnicos em Ordens de Produção quantificadas financeiramente pelo Value at Risk (VaR P80) de Monte Carlo.")

    data_emissao = datetime.datetime.now().strftime("%d/%m/%Y")
    p_texto(f"Documento emitido automaticamente pela Engenharia de Dados da Plataforma em {data_emissao}.", "Status do Protótipo:")

    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {''.join(body_parts)}
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>"""

    os.makedirs(os.path.dirname(os.path.abspath(caminho_saida)), exist_ok=True)
    with zipfile.ZipFile(caminho_saida, "w", compression=zipfile.ZIP_DEFLATED) as docx_zip:
        docx_zip.writestr("[Content_Types].xml", content_types)
        docx_zip.writestr("_rels/.rels", rels_root)
        docx_zip.writestr("word/_rels/document.xml.rels", doc_rels)
        docx_zip.writestr("word/styles.xml", styles_xml)
        docx_zip.writestr("word/document.xml", document_xml)


if __name__ == "__main__":
    p1 = r"c:\Users\larar\Downloads\ProjectAV\Descricao_Executiva_SaaS_LT_500kV.docx"
    p2 = r"c:\Users\larar\Downloads\ProjectAV\saas-lt-mvp\Descricao_Executiva_SaaS_LT_500kV.docx"
    criar_docx_openxml(p1)
    criar_docx_openxml(p2)
    print("Arquivos Word (.docx) gerados com sucesso:")
    print(" ->", p1, f"({os.path.getsize(p1)} bytes)")
    print(" ->", p2, f"({os.path.getsize(p2)} bytes)")
