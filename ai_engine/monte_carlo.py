import datetime
import math
import random
from typing import Dict, Any, List


def sortear_pert(rng: random.Random, minimo: float, mais_provavel: float, maximo: float, lamb: float = 4.0) -> float:
    """
    Sorteia uma variável aleatória seguindo a distribuição Beta-PERT (padrão AACE / PMI para Monte Carlo de cronogramas).
    """
    if maximo <= minimo:
        return minimo
    media = (minimo + lamb * mais_provavel + maximo) / (lamb + 2.0)
    if abs(media - mais_provavel) < 1e-6:
        alpha = (lamb / 2.0) + 1.0
    else:
        alpha = ((media - minimo) * (2.0 * mais_provavel - minimo - maximo)) / ((mais_provavel - media) * (maximo - minimo))
    if alpha <= 0:
        alpha = 2.0
    beta = alpha * (maximo - media) / max(1e-6, (media - minimo))
    if beta <= 0:
        beta = 2.0
    u = rng.betavariate(alpha, beta)
    return minimo + u * (maximo - minimo)


def executar_simulacao_monte_carlo(
    estruturas: List[Dict[str, Any]],
    limiar_risco_pct: float = 4.50,
    iteracoes: int = 2000,
    prazo_construcao_planejado_dias: float = 391.0,
    data_termino_baseline_str: str = "2023-10-15"
) -> Dict[str, Any]:
    """
    Motor Estocástico de Monte Carlo (N=2.000 iterações Beta-PERT + Eventos de Bernoulli)
    com acoplamento em Linha de Balanço (2 Frentes Paralelas e 4 Equipes) calibrado pelos documentos reais:
    1. 40-MDE-14022-619-AB0-P-RAI-00071-0.pdf (12 torres SPT > 30, 7 torres sem BSE-M, 5 torres NSPT=0)
    2. 40-LLI-14022-619-AB0-P-RAI-00001-5.xlsx (30 torres em Área Alagável Nota 12.11.1, 14 Travessias Nota 12.4)
    3. 03-CRO-14022-619-P-RAI-0001_R0D_06-09-22.mpp (391 dias de Construção + Comissionamento)
    4. Contrato EPC Cláusula 19.2.3 (Multas diárias por atraso e limite de 10% do CAPEX = R$ 15,82 MM)
    """
    torres = [e for e in estruturas if e.get("classificacao_mecanica") != "PORTICO"]

    # Semente determinística baseada no estado atual do banco para estabilidade visual entre reloads
    assinatura_estado = sum(
        (idx + 1) * (
            3 if t.get("status_fundacao") == "CONCLUIDO" else (1 if t.get("status_fundacao") == "EM_ANDAMENTO" else 0)
        ) + (
            17 if t.get("criticidade_ia") == "VERMELHO" else (7 if t.get("criticidade_ia") == "AMARELO" else 0)
        )
        for idx, t in enumerate(torres)
    ) + int(limiar_risco_pct * 100)
    rng = random.Random(20261027 + assinatura_estado)

    pendentes_fund = [t for t in torres if t.get("status_fundacao") != "CONCLUIDO"]
    pendentes_mont = [t for t in torres if t.get("status_montagem") != "CONCLUIDO"]
    pendentes_lanc = [t for t in torres if t.get("status_lancamento") != "CONCLUIDO"]

    # Separar bloqueios reais reportados em campo (exclusivos quando criticidade_ia != VERDE)
    bloqueios_geologia = [
        t for t in torres
        if t.get("criticidade_ia") in ("VERMELHO", "AMARELO") and t.get("ultimo_risco_categoria") == "TECNICO_GEOLOGIA"
    ]
    bloqueios_clima = [
        t for t in torres
        if t.get("criticidade_ia") in ("VERMELHO", "AMARELO") and t.get("ultimo_risco_categoria") == "CLIMA"
    ]
    bloqueios_travessia = [
        t for t in torres
        if t.get("criticidade_ia") in ("VERMELHO", "AMARELO") and t.get("ultimo_risco_categoria") == "FUNDIARIO_AMBIENTAL"
    ]
    bloqueios_logistica = [
        t for t in torres
        if t.get("criticidade_ia") in ("VERMELHO", "AMARELO") and t.get("ultimo_risco_categoria") == "LOGISTICA_SUPRIMENTOS"
    ]

    # Torres pendentes com riscos latentes mapeados na engenharia (ainda sem apontamento de bloqueio em campo)
    cods_bloqueados = {t["codigo_projeto"] for t in (bloqueios_geologia + bloqueios_clima + bloqueios_travessia + bloqueios_logistica)}
    latentes_spt30 = [t for t in pendentes_fund if t.get("conflito_spt_maior_30") and t["codigo_projeto"] not in cods_bloqueados]
    latentes_nspt0 = [t for t in pendentes_fund if t.get("solo_muito_mole_nspt_zero") and t["codigo_projeto"] not in cods_bloqueados]
    latentes_alagaveis = [t for t in pendentes_fund if t.get("area_alagavel") and t["codigo_projeto"] not in cods_bloqueados]
    latentes_travessias = [t for t in pendentes_lanc if t.get("travessia_critica") and t["codigo_projeto"] not in cods_bloqueados]

    # Fatores de acoplamento paralelo da Linha de Balanço (4 equipes de cravação em 2 frentes simultâneas)
    fator_caminho_critico_bloqueio = 0.52
    fator_latente_geo = 0.22
    fator_latente_hidro = 0.14
    fator_latente_trav = 0.20

    amostras_atraso_dias: List[float] = []
    soma_driver_geo = 0.0
    soma_driver_hidro = 0.0
    soma_driver_trav = 0.0
    soma_driver_prod = 0.0

    for _ in range(iteracoes):
        # 1. Risco Geotécnico (SPT > 30 / Sem BSE-M / NSPT = 0)
        d_geo = 0.0
        for t in bloqueios_geologia:
            if not t.get("opcao_2_contingencia_bse"):
                d_geo += sortear_pert(rng, 4.5, 8.0, 13.5) * fator_caminho_critico_bloqueio
            else:
                d_geo += sortear_pert(rng, 2.0, 4.2, 7.0) * fator_caminho_critico_bloqueio

        for t in latentes_spt30:
            if rng.random() < 0.35:
                if not t.get("opcao_2_contingencia_bse"):
                    d_geo += sortear_pert(rng, 2.5, 5.5, 9.5) * fator_latente_geo
                else:
                    d_geo += sortear_pert(rng, 1.2, 2.5, 4.5) * fator_latente_geo

        for t in latentes_nspt0:
            if rng.random() < 0.30:
                d_geo += sortear_pert(rng, 0.5, 1.2, 2.2) * fator_latente_geo

        # 2. Risco Hidrogeológico / Áreas Alagáveis (Nota 12.11.1 - 30 torres NA=0,00m)
        d_hidro = 0.0
        for t in bloqueios_clima:
            d_hidro += sortear_pert(rng, 3.0, 5.5, 9.5) * fator_caminho_critico_bloqueio

        for t in latentes_alagaveis:
            if rng.random() < 0.18:
                d_hidro += sortear_pert(rng, 1.0, 2.2, 4.2) * fator_latente_hidro

        # 3. Risco de Travessias Críticas (10 LTs Furnas/Enel + 4 Rodovias DER-RJ) e Fundiário
        d_trav = 0.0
        for t in bloqueios_travessia:
            d_trav += sortear_pert(rng, 4.5, 7.8, 13.0) * fator_caminho_critico_bloqueio

        for t in latentes_travessias:
            if rng.random() < 0.20:
                d_trav += sortear_pert(rng, 1.5, 3.2, 6.0) * fator_latente_trav

        # 4. Risco de Suprimentos e Variabilidade de Produtividade de Campo (Montagem Autoportantes/GNEL e Cabos)
        d_prod = 0.0
        for t in bloqueios_logistica:
            d_prod += sortear_pert(rng, 3.0, 5.2, 9.0) * fator_caminho_critico_bloqueio

        proporcao_restante = len(pendentes_mont) / max(1.0, len(torres))
        d_prod += sortear_pert(rng, -3.5 * proporcao_restante, 1.5 * proporcao_restante, 8.0 * proporcao_restante)

        # Atraso líquido no caminho crítico da Linha de Balanço
        atraso_iter = max(0.5, d_geo + d_hidro + d_trav + d_prod)
        amostras_atraso_dias.append(atraso_iter)

        soma_driver_geo += max(0.0, d_geo)
        soma_driver_hidro += max(0.0, d_hidro)
        soma_driver_trav += max(0.0, d_trav)
        soma_driver_prod += max(0.0, d_prod)

    amostras_atraso_dias.sort()

    def obter_percentil(lista_ordenada: List[float], p: float) -> float:
        idx = min(len(lista_ordenada) - 1, max(0, int(round((p / 100.0) * (len(lista_ordenada) - 1)))))
        return lista_ordenada[idx]

    p10_dias = round(obter_percentil(amostras_atraso_dias, 10), 1)
    p50_dias = round(obter_percentil(amostras_atraso_dias, 50), 1)
    p80_dias = round(obter_percentil(amostras_atraso_dias, 80), 1)
    p90_dias = round(obter_percentil(amostras_atraso_dias, 90), 1)
    media_dias = round(sum(amostras_atraso_dias) / len(amostras_atraso_dias), 1)

    p10_pct = round((p10_dias / prazo_construcao_planejado_dias) * 100.0, 2)
    p50_pct = round((p50_dias / prazo_construcao_planejado_dias) * 100.0, 2)
    p80_pct = round((p80_dias / prazo_construcao_planejado_dias) * 100.0, 2)
    p90_pct = round((p90_dias / prazo_construcao_planejado_dias) * 100.0, 2)

    spi_p10 = round(prazo_construcao_planejado_dias / (prazo_construcao_planejado_dias + p10_dias), 3)
    spi_p50 = round(prazo_construcao_planejado_dias / (prazo_construcao_planejado_dias + p50_dias), 3)
    spi_p80 = round(prazo_construcao_planejado_dias / (prazo_construcao_planejado_dias + p80_dias), 3)
    spi_p90 = round(prazo_construcao_planejado_dias / (prazo_construcao_planejado_dias + p90_dias), 3)

    limiar_dias = (limiar_risco_pct / 100.0) * prazo_construcao_planejado_dias
    qtd_estouro = sum(1 for x in amostras_atraso_dias if x > limiar_dias)
    prob_estouro_limiar_pct = round((qtd_estouro / len(amostras_atraso_dias)) * 100.0, 1)

    dt_base = datetime.date.fromisoformat(data_termino_baseline_str)
    dt_p10 = (dt_base + datetime.timedelta(days=int(round(p10_dias)))).isoformat()
    dt_p50 = (dt_base + datetime.timedelta(days=int(round(p50_dias)))).isoformat()
    dt_p80 = (dt_base + datetime.timedelta(days=int(round(p80_dias)))).isoformat()
    dt_p90 = (dt_base + datetime.timedelta(days=int(round(p90_dias)))).isoformat()

    # Multa Contratual Cláusula 19.2.3 (R$ 158.241,06/dia até teto de 10% = R$ 15.824.106,20)
    multa_diaria_brl = 158241.06
    teto_multa_brl = 15824106.20
    var_p50_brl = round(min(teto_multa_brl, p50_dias * multa_diaria_brl), 2)
    var_p80_brl = round(min(teto_multa_brl, p80_dias * multa_diaria_brl), 2)
    var_p90_brl = round(min(teto_multa_brl, p90_dias * multa_diaria_brl), 2)

    # Construir Histograma de 8 faixas para visualização no Cockpit
    min_a = amostras_atraso_dias[0]
    max_a = max(amostras_atraso_dias[-1], min_a + 8.0)
    num_bins = 8
    largura_bin = (max_a - min_a) / num_bins
    histograma = []
    for b in range(num_bins):
        ini_b = min_a + b * largura_bin
        fim_b = min_a + (b + 1) * largura_bin
        contagem = sum(
            1 for x in amostras_atraso_dias
            if (ini_b <= x < fim_b) or (b == num_bins - 1 and ini_b <= x <= fim_b)
        )
        freq_pct = round((contagem / iteracoes) * 100.0, 1)
        centro_dias = round((ini_b + fim_b) / 2.0, 1)
        centro_pct = round((centro_dias / prazo_construcao_planejado_dias) * 100.0, 2)
        histograma.append({
            "faixa_dias": f"+{ round(ini_b, 1) }d a +{ round(fim_b, 1) }d",
            "faixa_desvio_pct": f"{ round((ini_b / prazo_construcao_planejado_dias)*100, 1) }%–{ round((fim_b / prazo_construcao_planejado_dias)*100, 1) }%",
            "centro_dias": centro_dias,
            "centro_desvio_pct": centro_pct,
            "frequencia_pct": freq_pct,
            "contagem_iteracoes": contagem,
            "acima_limiar": centro_dias > limiar_dias
        })

    # Gráfico de Tornado (Sensibilidade dos Vetores de Risco)
    soma_total_drivers = max(0.001, soma_driver_geo + soma_driver_hidro + soma_driver_trav + soma_driver_prod)
    tornado = [
        {
            "driver": "Geotecnia SPT > 30 & Torres s/ Contingência BSE-M (Doc 40-MDE-00071)",
            "impacto_medio_dias": round(soma_driver_geo / iteracoes, 2),
            "participacao_variancia_pct": round((soma_driver_geo / soma_total_drivers) * 100.0, 1),
            "cor": "rose"
        },
        {
            "driver": "Interferências em Travessias Furnas 345kV / Enel / DER-RJ (Nota 12.4)",
            "impacto_medio_dias": round(soma_driver_trav / iteracoes, 2),
            "participacao_variancia_pct": round((soma_driver_trav / soma_total_drivers) * 100.0, 1),
            "cor": "amber"
        },
        {
            "driver": "Hidrogeologia / 30 Torres em Área Alagável NA=0,00m (Nota 12.11.1)",
            "impacto_medio_dias": round(soma_driver_hidro / iteracoes, 2),
            "participacao_variancia_pct": round((soma_driver_hidro / soma_total_drivers) * 100.0, 1),
            "cor": "cyan"
        },
        {
            "driver": "Logística de Suprimentos (Estacas/Aço) & Ritmo de Montagem",
            "impacto_medio_dias": round(soma_driver_prod / iteracoes, 2),
            "participacao_variancia_pct": round((soma_driver_prod / soma_total_drivers) * 100.0, 1),
            "cor": "purple"
        }
    ]
    tornado.sort(key=lambda x: x["participacao_variancia_pct"], reverse=True)

    return {
        "modelo": "Simulação Estocástica de Monte Carlo (Beta-PERT + Bernoulli)",
        "iteracoes": iteracoes,
        "prazo_base_construcao_dias": prazo_construcao_planejado_dias,
        "limiar_risco_baseline_pct": limiar_risco_pct,
        "limiar_risco_baseline_dias": round(limiar_dias, 1),
        "probabilidade_estouro_limiar_pct": prob_estouro_limiar_pct,
        "atraso_medio_dias": media_dias,
        "percentis": {
            "P10": {
                "rotulo": "P10 (Cenário Otimista)",
                "atraso_dias": p10_dias,
                "desvio_prazo_pct": p10_pct,
                "spi_projetado": spi_p10,
                "data_termino_projetada": dt_p10,
                "var_multa_contratual_brl": round(min(teto_multa_brl, p10_dias * multa_diaria_brl), 2)
            },
            "P50": {
                "rotulo": "P50 (Mediana / Mais Provável)",
                "atraso_dias": p50_dias,
                "desvio_prazo_pct": p50_pct,
                "spi_projetado": spi_p50,
                "data_termino_projetada": dt_p50,
                "var_multa_contratual_brl": var_p50_brl
            },
            "P80": {
                "rotulo": "P80 (Referência Tática AACE)",
                "atraso_dias": p80_dias,
                "desvio_prazo_pct": p80_pct,
                "spi_projetado": spi_p80,
                "data_termino_projetada": dt_p80,
                "var_multa_contratual_brl": var_p80_brl
            },
            "P90": {
                "rotulo": "P90 (Cenário Conservador Crítico)",
                "atraso_dias": p90_dias,
                "desvio_prazo_pct": p90_pct,
                "spi_projetado": spi_p90,
                "data_termino_projetada": dt_p90,
                "var_multa_contratual_brl": var_p90_brl
            }
        },
        "histograma": histograma,
        "tornado_sensibilidade": tornado,
        "contadores_exposicao": {
            "torres_spt30_pendentes": len(latentes_spt30) + len(bloqueios_geologia),
            "torres_alagaveis_pendentes": len(latentes_alagaveis) + len(bloqueios_clima),
            "travessias_pendentes": len(latentes_travessias) + len(bloqueios_travessia)
        }
    }


def simular_impacto_ordem_monte_carlo(
    torre_info: Dict[str, Any],
    categoria_problema: str,
    nivel_risco: str,
    limiar_baseline_pct: float = 4.50,
    iteracoes: int = 1000
) -> Dict[str, float]:
    """
    Roda micro-simulação de Monte Carlo (1.000 iterações PERT) para dimensionar o impacto P80
    de um apontamento de campo específico ao emitir uma Ordem de Produção.
    """
    rng = random.Random(hash(torre_info.get("codigo_projeto", "0/1")) + hash(categoria_problema))
    amostras = []

    for _ in range(iteracoes):
        if categoria_problema == "TECNICO_GEOLOGIA":
            if not torre_info.get("opcao_2_contingencia_bse"):
                d = sortear_pert(rng, 5.5, 8.5, 13.0)
            else:
                d = sortear_pert(rng, 2.5, 4.5, 7.5)
        elif categoria_problema == "CLIMA":
            d = sortear_pert(rng, 3.5, 6.0, 10.0) if torre_info.get("area_alagavel") else sortear_pert(rng, 1.5, 3.0, 5.5)
        elif categoria_problema == "FUNDIARIO_AMBIENTAL":
            d = sortear_pert(rng, 5.0, 8.5, 14.0)
        else:
            d = sortear_pert(rng, 4.0, 6.5, 10.5)
        amostras.append(d)

    amostras.sort()
    p50_d = amostras[int(0.50 * (iteracoes - 1))]
    p80_d = amostras[int(0.80 * (iteracoes - 1))]
    p90_d = amostras[int(0.90 * (iteracoes - 1))]

    # Desvio projetado na frente em relação ao pacote construtivo
    risco_p80_pct = round(limiar_baseline_pct + (p80_d / 391.0) * 100.0 * 1.65, 2)
    multa_p80_brl = round(p80_d * 158241.06, 2)

    return {
        "impacto_p50_dias": round(p50_d, 1),
        "impacto_p80_dias": int(round(p80_d)),
        "impacto_p90_dias": round(p90_d, 1),
        "risco_detectado_p80_pct": risco_p80_pct,
        "multa_evitada_p80_brl": multa_p80_brl
    }


def gerar_curva_s_eva(
    pacotes_calculados: List[Dict[str, Any]],
    mc_resultado: Dict[str, Any],
    avanco_global_pct: float
) -> Dict[str, Any]:
    """
    Gera os vetores mensais da Curva S (Set/2022 a Nov/2023) para os escopos:
    GLOBAL, FUNDACAO, MONTAGEM e LANCAMENTO.
    Contém 4 séries por escopo:
    1. Baseline Planejada (extraída das datas de início/fim de cada pacote no MS Project R0D)
    2. Curva Realizada Atual (acumulada até a data de corte da medição de campo)
    3. Curva de Tendência IA - Cenário P50 (Mediana Monte Carlo)
    4. Curva de Tendência IA - Cenário P80 (Referência Tática AACE Monte Carlo)
    """
    periodos = [
        ("2022-09-30", "Set/22"),
        ("2022-10-31", "Out/22"),
        ("2022-11-30", "Nov/22"),
        ("2022-12-31", "Dez/22"),
        ("2023-01-31", "Jan/23"),
        ("2023-02-28", "Fev/23"),
        ("2023-03-31", "Mar/23"),
        ("2023-04-30", "Abr/23"),
        ("2023-05-31", "Mai/23"),
        ("2023-06-30", "Jun/23"),
        ("2023-07-31", "Jul/23"),
        ("2023-08-31", "Ago/23"),
        ("2023-09-30", "Set/23"),
        ("2023-10-31", "Out/23"),
        ("2023-11-30", "Nov/23"),
    ]

    pacotes_folha = [p for p in pacotes_calculados if not p.get("eh_resumo_eap", False)]
    atraso_p50_dias = mc_resultado["percentis"]["P50"]["atraso_dias"]
    atraso_p80_dias = mc_resultado["percentis"]["P80"]["atraso_dias"]

    def frac_ate_data(dt_ini_str: str, dt_fim_str: str, dt_ref: datetime.date, shift_dias: float = 0.0) -> float:
        if not dt_ini_str or not dt_fim_str:
            return 0.0
        d_ini = datetime.date.fromisoformat(dt_ini_str) + datetime.timedelta(days=int(round(shift_dias * 0.25)))
        d_fim = datetime.date.fromisoformat(dt_fim_str) + datetime.timedelta(days=int(round(shift_dias)))
        if dt_ref <= d_ini:
            return 0.0
        if dt_ref >= d_fim:
            return 1.0
        total_d = max(1, (d_fim - d_ini).days)
        decorrido_d = (dt_ref - d_ini).days
        # Aplicar leve perfil sigmoidal (Curva S Beta 3x^2 - 2x^3) dentro do pacote
        x = max(0.0, min(1.0, decorrido_d / total_d))
        return (3.0 * (x ** 2)) - (2.0 * (x ** 3))

    escopos = ["GLOBAL", "FUNDACAO", "MONTAGEM", "LANCAMENTO"]
    series_por_escopo: Dict[str, Any] = {}

    for esc in escopos:
        if esc == "GLOBAL":
            pacs = pacotes_folha
        else:
            pacs = [p for p in pacotes_folha if p.get("etapa_macro") == esc]

        pv_total = sum(p.get("custo_planejado_pv_brl", 0.0) for p in pacs) or 1.0
        ev_atual = sum(p.get("valor_agregado_ev_brl", 0.0) for p in pacs)
        avanco_atual_esc_pct = round((ev_atual / pv_total) * 100.0, 2)

        # 1. Calcular Curva Baseline Planejada mês a mês (Set/22 a Nov/23)
        bl_pcts: List[float] = []
        bl_pvs: List[float] = []
        raw_p50_pcts: List[float] = []
        raw_p80_pcts: List[float] = []

        for dt_str, _ in periodos:
            dt_ref = datetime.date.fromisoformat(dt_str)
            soma_pv_mes = 0.0
            soma_p50_mes = 0.0
            soma_p80_mes = 0.0
            for p in pacs:
                pv_p = p.get("custo_planejado_pv_brl", 0.0)
                f_bl = frac_ate_data(p.get("data_inicio_planejada"), p.get("data_fim_planejada"), dt_ref, 0.0)
                f_p50 = frac_ate_data(p.get("data_inicio_planejada"), p.get("data_fim_planejada"), dt_ref, atraso_p50_dias)
                f_p80 = frac_ate_data(p.get("data_inicio_planejada"), p.get("data_fim_planejada"), dt_ref, atraso_p80_dias)
                soma_pv_mes += pv_p * f_bl
                soma_p50_mes += pv_p * f_p50
                soma_p80_mes += pv_p * f_p80

            bl_pcts.append(round((soma_pv_mes / pv_total) * 100.0, 2))
            bl_pvs.append(round(soma_pv_mes, 2))
            raw_p50_pcts.append(round((soma_p50_mes / pv_total) * 100.0, 2))
            raw_p80_pcts.append(round((soma_p80_mes / pv_total) * 100.0, 2))

        # Determinar índice do mês de corte atual
        # Quando há medição de campo (avanco_global_pct > 0), posiciona o corte no mês correspondente do cronograma (Mai/23 = idx 8)
        if avanco_global_pct <= 0.01:
            idx_corte = 0
        else:
            # Encontrar o mês onde a baseline mais se aproxima da meta planejada atual (ou Mai/23 = idx 8)
            idx_corte = 8

        bl_no_corte = max(0.5, bl_pcts[idx_corte])
        fator_real = avanco_atual_esc_pct / bl_no_corte

        real_pcts: List[Any] = []
        real_evs: List[Any] = []
        tend_p50_pcts: List[Any] = []
        tend_p80_pcts: List[Any] = []
        tend_p50_evs: List[Any] = []
        tend_p80_evs: List[Any] = []

        # Construir Curva Realizada (até idx_corte) e Curvas de Tendência P50/P80 (de idx_corte até o fim)
        restante_pct = max(0.0, 100.0 - avanco_atual_esc_pct)
        base_futura_p50 = max(0.1, 100.0 - raw_p50_pcts[idx_corte])
        base_futura_p80 = max(0.1, 100.0 - raw_p80_pcts[idx_corte])

        for i in range(len(periodos)):
            if i < idx_corte:
                # Histórico anterior ao mês de corte
                r_pct = round(min(avanco_atual_esc_pct, bl_pcts[i] * fator_real), 2)
                real_pcts.append(r_pct)
                real_evs.append(round((r_pct / 100.0) * pv_total, 2))
                tend_p50_pcts.append(None)
                tend_p80_pcts.append(None)
                tend_p50_evs.append(None)
                tend_p80_evs.append(None)
            elif i == idx_corte:
                # Ponto de corte exato (conecta Realizado com início das Tendências P50 e P80)
                r_pct = round(avanco_atual_esc_pct, 2)
                real_pcts.append(r_pct)
                real_evs.append(round((r_pct / 100.0) * pv_total, 2))
                tend_p50_pcts.append(r_pct)
                tend_p80_pcts.append(r_pct)
                tend_p50_evs.append(round((r_pct / 100.0) * pv_total, 2))
                tend_p80_evs.append(round((r_pct / 100.0) * pv_total, 2))
            else:
                # Meses futuros projetados pelo Motor de Monte Carlo (P50 e P80)
                real_pcts.append(None)
                real_evs.append(None)

                ganho_p50 = max(0.0, raw_p50_pcts[i] - raw_p50_pcts[idx_corte]) / base_futura_p50
                ganho_p80 = max(0.0, raw_p80_pcts[i] - raw_p80_pcts[idx_corte]) / base_futura_p80

                # No penúltimo mês (Out/23, i=13), aplica a defasagem proporcional ao atraso P50 e P80
                if i == len(periodos) - 2:
                    teto_out_p50 = round(100.0 - min(18.0, (atraso_p50_dias / 391.0) * 100.0 * 1.15), 2)
                    teto_out_p80 = round(100.0 - min(22.0, (atraso_p80_dias / 391.0) * 100.0 * 1.25), 2)
                    val_p50 = min(teto_out_p50, round(avanco_atual_esc_pct + restante_pct * ganho_p50, 2))
                    val_p80 = min(teto_out_p80, round(avanco_atual_esc_pct + restante_pct * ganho_p80, 2))
                elif i == len(periodos) - 1:
                    val_p50 = 100.0
                    val_p80 = 100.0
                else:
                    val_p50 = min(99.0, round(avanco_atual_esc_pct + restante_pct * (ganho_p50 ** 1.08), 2))
                    val_p80 = min(98.5, round(avanco_atual_esc_pct + restante_pct * (ganho_p80 ** 1.18), 2))

                tend_p50_pcts.append(val_p50)
                tend_p80_pcts.append(val_p80)
                tend_p50_evs.append(round((val_p50 / 100.0) * pv_total, 2))
                tend_p80_evs.append(round((val_p80 / 100.0) * pv_total, 2))

        series_por_escopo[esc] = {
            "pv_total_brl": round(pv_total, 2),
            "ev_atual_brl": round(ev_atual, 2),
            "avanco_atual_pct": avanco_atual_esc_pct,
            "planejado_no_corte_pct": bl_pcts[idx_corte],
            "desvio_no_corte_pct": round(avanco_atual_esc_pct - bl_pcts[idx_corte], 2),
            "indice_mes_corte": idx_corte,
            "rotulo_mes_corte": periodos[idx_corte][1],
            "baseline_pct": bl_pcts,
            "baseline_pv_brl": bl_pvs,
            "realizado_pct": real_pcts,
            "realizado_ev_brl": real_evs,
            "tendencia_p50_pct": tend_p50_pcts,
            "tendencia_p50_ev_brl": tend_p50_evs,
            "tendencia_p80_pct": tend_p80_pcts,
            "tendencia_p80_ev_brl": tend_p80_evs,
        }

    return {
        "rotulos_meses": [p[1] for p in periodos],
        "datas_meses": [p[0] for p in periodos],
        "escopos": series_por_escopo
    }

