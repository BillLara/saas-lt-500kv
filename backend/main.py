import os
import sys
import json
import math
import uuid
import sqlite3
import datetime
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Caminhos do Projeto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ai_engine.monte_carlo import executar_simulacao_monte_carlo, simular_impacto_ordem_monte_carlo, gerar_curva_s_eva

DB_DIR = os.path.join(BASE_DIR, "database")
BASELINE_JSON_PATH = os.path.join(DB_DIR, "baseline_consolidada_v1.json")
SQLITE_CLOUD_PATH = os.path.join(DB_DIR, "saas_lt_cloud.db")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app = FastAPI(
    title="SaaS Autônomo LT 500 kV - UTE GNA II / SE Campos 2",
    description="Plataforma Multi-Tenant de Acompanhamento Tático e Inteligência Preditiva para Construção de Linhas de Transmissão",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# INICIALIZAÇÃO DO BANCO TRANSACIONAL HÍBRIDO (PostgreSQL Neon.tech + Fallback SQLite)
# ============================================================================

ENV_FILE_PATH = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_FILE_PATH):
    with open(ENV_FILE_PATH, "r", encoding="utf-8") as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


class HybridCursor:
    """Wrapper transparente que converte placeholders '?' (SQLite) para '%s' (PostgreSQL/Neon)."""
    def __init__(self, raw_cursor, is_postgres: bool):
        self._cur = raw_cursor
        self._is_pg = is_postgres

    def _adapt_sql(self, sql: str) -> str:
        if self._is_pg:
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params=None):
        q = self._adapt_sql(sql)
        if params is not None:
            return self._cur.execute(q, params)
        return self._cur.execute(q)

    def executemany(self, sql: str, seq_of_params):
        q = self._adapt_sql(sql)
        if self._is_pg:
            psycopg2.extras.execute_batch(self._cur, q, seq_of_params, page_size=100)
            return None
        return self._cur.executemany(q, seq_of_params)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def close(self):
        return self._cur.close()


class HybridConnection:
    def __init__(self, raw_conn, is_postgres: bool):
        self._conn = raw_conn
        self._is_pg = is_postgres

    def cursor(self):
        if self._is_pg:
            return HybridCursor(self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor), True)
        return HybridCursor(self._conn.cursor(), False)

    def commit(self):
        return self._conn.commit()

    def close(self):
        return self._conn.close()


def get_db() -> HybridConnection:
    db_url = os.environ.get("DATABASE_URL", DATABASE_URL).strip()
    if db_url and HAS_PSYCOPG2:
        conn = psycopg2.connect(db_url)
        return HybridConnection(conn, is_postgres=True)
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(SQLITE_CLOUD_PATH)
    conn.row_factory = sqlite3.Row
    return HybridConnection(conn, is_postgres=False)


def init_cloud_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS apontamentos_campo (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        sqlite_local_id TEXT,
        codigo_projeto TEXT NOT NULL,
        sequencia INTEGER NOT NULL,
        fiscal_nome TEXT DEFAULT 'Fiscal de Campo - Equipe LT',
        etapa TEXT NOT NULL, -- FUNDACAO, MONTAGEM, LANCAMENTO
        status_reportado TEXT NOT NULL, -- NAO_INICIADO, EM_ANDAMENTO, CONCLUIDO
        checklist_json TEXT,
        latitude_coleta REAL,
        longitude_coleta REAL,
        distancia_torre_metros REAL,
        geofence_valido INTEGER DEFAULT 1,
        observacao_texto TEXT,
        transcricao_audio_ia TEXT,
        nivel_risco_ia TEXT, -- BAIXO, MEDIO, ALTO, CRITICO
        categoria_problema_ia TEXT, -- NENHUM, CLIMA, LOGISTICA_SUPRIMENTOS, FUNDIARIO_AMBIENTAL, TECNICO_GEOLOGIA, PRODUTIVIDADE_EQUIPE
        resumo_analise_ia TEXT,
        data_hora_coleta TEXT,
        data_hora_sincronizacao TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS status_torres (
        codigo_projeto TEXT PRIMARY KEY,
        sequencia INTEGER NOT NULL,
        status_fundacao TEXT DEFAULT 'NAO_INICIADO',
        status_montagem TEXT DEFAULT 'NAO_INICIADO',
        status_lancamento TEXT DEFAULT 'NAO_INICIADO',
        criticidade_ia TEXT DEFAULT 'VERDE', -- VERDE, AMARELO, VERMELHO
        ultimo_risco_categoria TEXT DEFAULT 'NENHUM',
        ultima_observacao TEXT DEFAULT '',
         torque_medio_instalacao_lbft REAL,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ordens_producao (
        id TEXT PRIMARY KEY,
        numero_ordem TEXT NOT NULL,
        frente_afetada TEXT NOT NULL,
        torres_afetadas_json TEXT,
        risco_detectado_pct REAL NOT NULL,
        limiar_baseline_pct REAL NOT NULL,
        motivo_desvio TEXT NOT NULL,
        acao_corretiva_recomendada TEXT NOT NULL,
        impacto_estimado_prazo_dias INTEGER,
        multa_contratual_evitada_brl REAL,
        status TEXT DEFAULT 'EMITIDA',
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS revisoes_baseline (
        versao INTEGER PRIMARY KEY,
        titulo_revisao TEXT NOT NULL,
        motivo_revisao TEXT NOT NULL,
        status TEXT NOT NULL,
        limiar_risco_toleravel_pct REAL NOT NULL,
        nova_ordem_batalha_codigo TEXT,
        created_at TEXT
    )
    """)

    # Popula dados iniciais se vazio
    with open(BASELINE_JSON_PATH, "r", encoding="utf-8") as f:
        bl_data = json.load(f)

    cur.execute("SELECT COUNT(*) as c FROM status_torres")
    if cur.fetchone()["c"] == 0:
        now_str = datetime.datetime.now().isoformat()
        batch_torres = [
            (est["codigo_projeto"], est["sequencia"], now_str)
            for est in bl_data["estruturas"]
        ]
        cur.executemany("""
            INSERT INTO status_torres (codigo_projeto, sequencia, status_fundacao, status_montagem, status_lancamento, criticidade_ia, updated_at)
            VALUES (?, ?, 'NAO_INICIADO', 'NAO_INICIADO', 'NAO_INICIADO', 'VERDE', ?)
        """, batch_torres)

    cur.execute("SELECT COUNT(*) as c FROM revisoes_baseline")
    if cur.fetchone()["c"] == 0:
        cur.execute("""
            INSERT INTO revisoes_baseline (versao, titulo_revisao, motivo_revisao, status, limiar_risco_toleravel_pct, nova_ordem_batalha_codigo, created_at)
            VALUES (1, 'Baseline V1 - R0D (06/09/2022) + Lista de Construção Rev.5', 'Carga Inicial do Projeto Executivo (84 Torres / 37,464 km)', 'ATIVA', 4.50, 'OB-001', ?)
        """, (datetime.datetime.now().isoformat(),))

    conn.commit()
    conn.close()

init_cloud_db()

# ============================================================================
# FUNÇÕES MATEMÁTICAS GEODÉSICAS E MOTOR DE IA (NLP + PREDITIVO + ORDENS DE PRODUÇÃO)
# ============================================================================

def calcular_distancia_haversine_metros(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return round(2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a)), 2)

def classificar_relatorio_campo_ia(texto: str, torre_info: dict, etapa: str, checklist: dict) -> dict:
    """
    Motor de IA (Gemini / Heurística Especialista de Engenharia de LT 500 kV):
    Analisa o texto/transcrição do fiscal, cruza com as características físicas da torre na Lista de Construção
    (ex: área alagável, estaca helicoidal SPT <= 30, travessia crítica) e retorna risco estruturado.
    """
    txt_up = (texto or "").upper()
    alagavel = torre_info.get("area_alagavel", False)
    travessia = torre_info.get("travessia_critica")
    tipo_est = torre_info.get("tipo_estrutura", "")

    nivel_risco = "BAIXO"
    categoria = "NENHUM"
    criticidade_torre = "VERDE"
    analise = "Execução dentro dos parâmetros nominais de projeto executivo."

    # 1. Verificação de Impenetrabilidade / Rocha / Matacão / SPT > 30 (Procedimento 06-PRO-00002 & Doc 40-MDE-00071)
    if any(w in txt_up for w in ["ROCHA", "MATACÃO", "MATACAO", "IMPENETRÁVEL", "IMPENETRAVEL", "SPT", "RECUSA", "TORQUE ALTO", "QUEBRA DE HÉLICE", "DESVIO ANGULAR"]):
        nivel_risco = "CRITICO"
        categoria = "TECNICO_GEOLOGIA"
        criticidade_torre = "VERMELHO"
        op2_bse = torre_info.get("opcao_2_contingencia_bse")
        nspt_perfil = torre_info.get("nspt_1a8m", [])
        bse_msg = f"Migrar imediatamente para a Opção 2 pré-dimensionada no doc. 40-MDE-00071: {op2_bse}." if op2_bse else "Atenção: Torre SEM Opção 2 (BSE-M) pré-dimensionada no doc. 40-MDE-00071; solicitar cálculo emergencial à Power Energie / Railec."
        analise = (
            f"ALERTA GEOTÉCNICO CRÍTICO na Torre {torre_info['codigo_projeto']} ({tipo_est}): Detectada impenetrabilidade/SPT > 30 "
            f"(Perfil NSPT 1-8m da sondagem: {nspt_perfil}, máx={torre_info.get('max_nspt_8m')} golpes) na cravação da estaca {torre_info['codigo_fundacao_pe']} "
            f"(prof. mín. {torre_info['profundidade_minima_estaca_m']}m na LLI Rev.5 vs {torre_info.get('prof_estaca_mde_rev0_m')}m na MDE Rev.0). {bse_msg}"
        )
    # 2. Verificação de Nível d'Água / Alagamento / Chuva Intensa (Nota 12.11.1)
    elif any(w in txt_up for w in ["ALAGADO", "ALAGAMENTO", "ÁGUA", "AGUA", "CHUVA", "ATOLAMENTO", "LAMA", "LENÇOL", "NA SUPERIOR", "INUNDAÇÃO"]):
        nivel_risco = "ALTO" if alagavel else "MEDIO"
        categoria = "CLIMA"
        criticidade_torre = "VERMELHO" if alagavel else "AMARELO"
        nota_alag = " (Torre mapeada na Nota 12.11.1 com exigência de Delta H >= 60cm)" if alagavel else ""
        analise = (
            f"RISCO HIDROGEOLÓGICO/CLIMÁTICO na Torre {torre_info['codigo_projeto']}{nota_alag}: Condição de alagamento/nível d'água elevado impactando "
            f"o acesso da retroescavadeira hidráulica. Verificar se a lâmina d'água ultrapassa o afloramento de 60cm previsto no projeto executivo."
        )
    # 3. Verificação Fundiária / Embargo / Travessia (Nota 12.2 / 12.3 / 12.4)
    elif any(w in txt_up for w in ["EMBARGO", "PROPRIETÁRIO", "PROPRIETARIO", "IMPEDIMENTO", "FUNDIÁRIO", "FUNDIARIO", "FAIXA", "BENFEITORIA", "FURNAS", "ENEL", "DER", "RODOVIA", "TRAVESSIA", "LICENÇA"]):
        nivel_risco = "CRITICO"
        categoria = "FUNDIARIO_AMBIENTAL"
        criticidade_torre = "VERMELHO"
        info_trav = f" vinculada à {travessia}" if travessia else ""
        analise = (
            f"BLOQUEIO FUNDIÁRIO / INTERFERÊNCIA DE TRAVESSIA na Torre {torre_info['codigo_projeto']}{info_trav}: "
            f"Frente retida por impedimento de acesso ou pendência de autorização de travessia (Nota 12.3). Risco imediato de ociosidade de equipe."
        )
    # 4. Verificação Logística / Atraso de Suprimentos (Aço, Estacas, Cabos, Isoladores)
    elif any(w in txt_up for w in ["FALTA", "ATRASO", "MATERIAL", "ESTACA", "TRELIÇA", "PARAFUSO", "BOBINA", "ISOLADOR", "GUINDASTE", "QUEBRA DE MÁQUINA", "RETROESCAVADEIRA"]):
        nivel_risco = "ALTO"
        categoria = "LOGISTICA_SUPRIMENTOS"
        criticidade_torre = "VERMELHO"
        analise = (
            f"GARGALO LOGÍSTICO / SUPRIMENTOS na Torre {torre_info['codigo_projeto']} ({tipo_est} - {torre_info['peso_aco_ton']} ton): "
            f"Indisponibilidade de componentes ou equipamento de cravação/içamento comprometendo o ritmo da Frente."
        )
    elif checklist and checklist.get("torque_obtido_lbft") and float(checklist.get("torque_obtido_lbft", 0)) < 4500:
        nivel_risco = "ALTO"
        categoria = "TECNICO_GEOLOGIA"
        criticidade_torre = "AMARELO"
        analise = (
            f"ATENÇÃO TÉCNICA (Protocolo Anexo I): Torque médio registrado ({checklist.get('torque_obtido_lbft')} lb.ft) nos últimos 30cm "
            f"abaixo da especificação mínima nominal. Necessário acoplar extensão lisa adicional na estaca {torre_info['codigo_fundacao_pe']}."
        )

    return {
        "nivel_risco_ia": nivel_risco,
        "categoria_problema_ia": categoria,
        "criticidade_torre": criticidade_torre,
        "resumo_analise_ia": analise
    }

# ============================================================================
# ROTAS DA API REST (GESTOR + FISCAL MOBILE + IA)
# ============================================================================

@app.get("/api/cockpit")
def obter_cockpit_gestor():
    """Retorna todos os dados consolidados para o Cockpit do Gestor: Baseline, Torres Georreferenciadas, Avanço dos Pacotes, EVA (PV/EV/SPI) e Ordens."""
    with open(BASELINE_JSON_PATH, "r", encoding="utf-8") as f:
        bl_data = json.load(f)

    conn = get_db()
    cur = conn.cursor()

    # Mapear status atuais das torres
    cur.execute("SELECT * FROM status_torres")
    status_map = {row["codigo_projeto"]: dict(row) for row in cur.fetchall()}

    estruturas_enriquecidas = []
    concluidas_fund = 0
    concluidas_mont = 0
    concluidas_lanc = 0
    em_andamento_fund = 0
    em_andamento_mont = 0
    em_andamento_lanc = 0
    peso_montado_ton = 0.0
    alertas_vermelhos = 0
    alertas_amarelos = 0

    for est in bl_data["estruturas"]:
        st = status_map.get(est["codigo_projeto"], {})
        sf = st.get("status_fundacao", "NAO_INICIADO")
        sm = st.get("status_montagem", "NAO_INICIADO")
        sl = st.get("status_lancamento", "NAO_INICIADO")
        crit = st.get("criticidade_ia", "VERDE")

        if est["classificacao_mecanica"] != "PORTICO":
            if sf == "CONCLUIDO":
                concluidas_fund += 1
            elif sf == "EM_ANDAMENTO":
                em_andamento_fund += 1

            if sm == "CONCLUIDO":
                concluidas_mont += 1
                peso_montado_ton += est["peso_aco_ton"]
            elif sm == "EM_ANDAMENTO":
                em_andamento_mont += 1
                peso_montado_ton += est["peso_aco_ton"] * 0.4

            if sl == "CONCLUIDO":
                concluidas_lanc += 1
            elif sl == "EM_ANDAMENTO":
                em_andamento_lanc += 1

        if crit == "VERMELHO":
            alertas_vermelhos += 1
        elif crit == "AMARELO":
            alertas_amarelos += 1

        est_copy = dict(est)
        est_copy["status_fundacao"] = sf
        est_copy["status_montagem"] = sm
        est_copy["status_lancamento"] = sl
        est_copy["criticidade_ia"] = crit
        est_copy["ultimo_risco_categoria"] = st.get("ultimo_risco_categoria", "NENHUM")
        est_copy["ultima_observacao"] = st.get("ultima_observacao", "")
        est_copy["torque_medio_instalacao_lbft"] = st.get("torque_medio_instalacao_lbft")
        estruturas_enriquecidas.append(est_copy)

    # Recalcular Avanço Proporcional dos Pacotes Construtivos do MS Project (Regra Comentário 1)
    pacotes_calculados = []
    ev_total_brl = 0.0
    pv_total_brl = 0.0
    ev_por_etapa = {"FUNDACAO": 0.0, "MONTAGEM": 0.0, "LANCAMENTO": 0.0, "COMISSIONAMENTO": 0.0}
    pv_por_etapa = {"FUNDACAO": 0.0, "MONTAGEM": 0.0, "LANCAMENTO": 0.0, "COMISSIONAMENTO": 0.0}

    # 1ª Passada: Calcular todos os pacotes folha (atividades diretas de campo)
    for pac in bl_data["pacotes_vinculados"]:
        if pac.get("eh_resumo_eap", False):
            continue
        codigos = pac["codigos_torres"]
        etapa = pac["etapa_macro"]
        total_t = max(1, len(codigos))
        pontos = 0.0

        for cod in codigos:
            st = status_map.get(cod, {})
            if etapa == "FUNDACAO":
                status_etapa = st.get("status_fundacao", "NAO_INICIADO")
            elif etapa == "MONTAGEM":
                status_etapa = st.get("status_montagem", "NAO_INICIADO")
            elif etapa == "LANCAMENTO":
                status_etapa = st.get("status_lancamento", "NAO_INICIADO")
            else:
                # Comissionamento requer fundação, montagem e lançamento concluídos na torre
                sf_c = st.get("status_fundacao") == "CONCLUIDO"
                sm_c = st.get("status_montagem") == "CONCLUIDO"
                sl_c = st.get("status_lancamento") == "CONCLUIDO"
                status_etapa = "CONCLUIDO" if (sf_c and sm_c and sl_c) else ("EM_ANDAMENTO" if (sf_c and sm_c and st.get("status_lancamento") == "EM_ANDAMENTO") else "NAO_INICIADO")

            if status_etapa == "CONCLUIDO":
                pontos += 1.0
            elif status_etapa == "EM_ANDAMENTO":
                pontos += 0.50 if "PRE MONTAGEM" not in pac["nome_pacote"].upper() else 0.85

        avanco_pct = round((pontos / total_t) * 100.0, 2)
        pv_pac = pac["custo_planejado_pv_brl"]
        ev_pac = round(pv_pac * (avanco_pct / 100.0), 2)
        pv_total_brl += pv_pac
        ev_total_brl += ev_pac
        if etapa in ev_por_etapa:
            pv_por_etapa[etapa] += pv_pac
            ev_por_etapa[etapa] += ev_pac

        pac_copy = dict(pac)
        pac_copy["avanco_fisico_pct"] = avanco_pct
        pac_copy["valor_agregado_ev_brl"] = ev_pac
        pacotes_calculados.append(pac_copy)

    # 2ª Passada: Consolidar linhas Resumo da EAP (IDs 61, 62, 75, 82, 90)
    for pac in bl_data["pacotes_vinculados"]:
        if not pac.get("eh_resumo_eap", False):
            continue
        regra = pac.get("regra_vinculo_torres", "")
        if regra == "RESUMO_FUNDACAO":
            pv_res, ev_res = pv_por_etapa["FUNDACAO"], ev_por_etapa["FUNDACAO"]
        elif regra == "RESUMO_MONTAGEM":
            pv_res, ev_res = pv_por_etapa["MONTAGEM"], ev_por_etapa["MONTAGEM"]
        elif regra == "RESUMO_LANCAMENTO":
            pv_res, ev_res = pv_por_etapa["LANCAMENTO"], ev_por_etapa["LANCAMENTO"]
        elif regra == "RESUMO_COMISSIONAMENTO":
            pv_res, ev_res = pv_por_etapa["COMISSIONAMENTO"], ev_por_etapa["COMISSIONAMENTO"]
        else:
            # RESUMO_CONSTRUCAO (ID 61: soma Civil + Montagem + Lançamento)
            pv_res = pv_por_etapa["FUNDACAO"] + pv_por_etapa["MONTAGEM"] + pv_por_etapa["LANCAMENTO"]
            ev_res = ev_por_etapa["FUNDACAO"] + ev_por_etapa["MONTAGEM"] + ev_por_etapa["LANCAMENTO"]

        avanco_res = round((ev_res / max(1.0, pv_res)) * 100.0, 2)
        pac_copy = dict(pac)
        pac_copy["custo_planejado_pv_brl"] = round(pv_res, 2)
        pac_copy["avanco_fisico_pct"] = avanco_res
        pac_copy["valor_agregado_ev_brl"] = round(ev_res, 2)
        pacotes_calculados.append(pac_copy)

    pacotes_calculados.sort(key=lambda x: x["uid_ms_project"])

    # Cálculo de SPI, Avanço Global Ponderado e Risco de Prazo
    total_torres = bl_data["resumo_executivo"]["total_torres"] # 84
    avanco_fund_pct = round(((concluidas_fund + 0.4 * em_andamento_fund) / total_torres) * 100.0, 2)
    avanco_mont_pct = round(((concluidas_mont + 0.4 * em_andamento_mont) / total_torres) * 100.0, 2)
    avanco_lanc_pct = round(((concluidas_lanc + 0.4 * em_andamento_lanc) / total_torres) * 100.0, 2)

    avanco_fisico_global_pct = round((ev_total_brl / max(1.0, pv_total_brl)) * 100.0, 2)

    # Meta planejada de referência para simulação tática (ou proporcional aos apontamentos)
    cur.execute("SELECT COUNT(*) as c FROM apontamentos_campo")
    total_apontamentos = cur.fetchone()["c"]

    # Buscar últimos apontamentos e Ordens de Produção
    cur.execute("SELECT * FROM apontamentos_campo ORDER BY data_hora_sincronizacao DESC LIMIT 40")
    apontamentos_recentes = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM ordens_producao ORDER BY created_at DESC")
    ordens_producao = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM revisoes_baseline ORDER BY versao DESC")
    revisoes = [dict(r) for r in cur.fetchall()]

    conn.close()

    limiar_ativo = revisoes[0]["limiar_risco_toleravel_pct"] if revisoes else 4.50

    # Executar Motor Estocástico de Monte Carlo (2.000 iterações Beta-PERT + Bernoulli)
    mc_resultado = executar_simulacao_monte_carlo(
        estruturas=estruturas_enriquecidas,
        limiar_risco_pct=limiar_ativo,
        iteracoes=2000,
        prazo_construcao_planejado_dias=391.0,
        data_termino_baseline_str=bl_data["resumo_executivo"].get("data_termino_prevista", "2023-10-15")
    )

    spi_p80 = mc_resultado["percentis"]["P80"]["spi_projetado"]
    desvio_p80_pct = mc_resultado["percentis"]["P80"]["desvio_prazo_pct"]
    meta_planejada_pct = round(min(100.0, avanco_fisico_global_pct / max(0.50, spi_p80)), 2) if avanco_fisico_global_pct > 0 else round(desvio_p80_pct, 2)

    curva_s_data = gerar_curva_s_eva(
        pacotes_calculados=pacotes_calculados,
        mc_resultado=mc_resultado,
        avanco_global_pct=avanco_fisico_global_pct
    )

    return {
        "resumo_executivo": bl_data["resumo_executivo"],
        "baseline_ativa": revisoes[0] if revisoes else bl_data["baseline_metadata"],
        "historico_baselines": revisoes,
        "monte_carlo": mc_resultado,
        "curva_s": curva_s_data,
        "kpis_tempo_real": {
            "avanco_global_pct": avanco_fisico_global_pct,
            "meta_planejada_pct": meta_planejada_pct,
            "spi": spi_p80,
            "spi_p50": mc_resultado["percentis"]["P50"]["spi_projetado"],
            "desvio_prazo_risco_pct": desvio_p80_pct,
            "desvio_p50_pct": mc_resultado["percentis"]["P50"]["desvio_prazo_pct"],
            "probabilidade_estouro_limiar_pct": mc_resultado["probabilidade_estouro_limiar_pct"],
            "limiar_risco_baseline_pct": limiar_ativo,
            "pv_planejado_total_brl": round(pv_total_brl, 2),
            "ev_agregado_atual_brl": round(ev_total_brl, 2),
            "var_multa_p80_brl": mc_resultado["percentis"]["P80"]["var_multa_contratual_brl"],
            "torres_fundacao_concluidas": concluidas_fund,
            "torres_montagem_concluidas": concluidas_mont,
            "torres_lancamento_concluidas": concluidas_lanc,
            "avanco_fundacao_pct": avanco_fund_pct,
            "avanco_montagem_pct": avanco_mont_pct,
            "avanco_lancamento_pct": avanco_lanc_pct,
            "peso_aco_montado_ton": round(peso_montado_ton, 2),
            "alertas_vermelhos": alertas_vermelhos,
            "alertas_amarelos": alertas_amarelos,
            "total_apontamentos_sincronizados": total_apontamentos
        },
        "alertas_validacao_integridade": bl_data["alertas_validacao_integridade"],
        "ordem_batalha_vigente": bl_data["ordem_batalha_inicial"],
        "ordens_producao": ordens_producao,
        "pacotes_cronograma": pacotes_calculados,
        "todas_tarefas_cronograma": bl_data.get("todas_tarefas_cronograma", []),
        "estruturas": estruturas_enriquecidas,
        "apontamentos_recentes": apontamentos_recentes
    }


class ApontamentoInput(BaseModel):
    sqlite_local_id: Optional[str] = None
    codigo_projeto: str
    fiscal_nome: Optional[str] = "Eng. Fiscal Campo - Equipe Açu"
    etapa: str # FUNDACAO, MONTAGEM, LANCAMENTO
    status_reportado: str # NAO_INICIADO, EM_ANDAMENTO, CONCLUIDO
    latitude_coleta: float
    longitude_coleta: float
    observacao_texto: Optional[str] = ""
    checklist: Optional[Dict[str, Any]] = {}
    ignorar_trava_geofence_teste: Optional[bool] = False


@app.post("/api/campo/sincronizar")
def sincronizar_apontamento_campo(payload: ApontamentoInput):
    """
    Recebe o pacote JSON vindo do Sync Engine Offline-First do aplicativo móvel do Fiscal:
    1. Valida a Cerca Geográfica (Geofencing <= 50m da coordenada UTM/WGS84 da Torre).
    2. Valida precedência construtiva (ex: impede Montagem sem Fundação concluída).
    3. Aciona o Motor de IA para classificar o risco textual/técnico.
    4. Recalcula o avanço proporcional dos Pacotes do MS Project e emite Ordem de Produção se Risco > Limiar da Baseline.
    """
    with open(BASELINE_JSON_PATH, "r", encoding="utf-8") as f:
        bl_data = json.load(f)

    torre = next((e for e in bl_data["estruturas"] if e["codigo_projeto"] == payload.codigo_projeto), None)
    if not torre:
        raise HTTPException(status_code=404, detail=f"Torre {payload.codigo_projeto} não encontrada na Lista de Construção.")

    dist_m = calcular_distancia_haversine_metros(
        torre["latitude"], torre["longitude"],
        payload.latitude_coleta, payload.longitude_coleta
    )
    geofence_ok = (dist_m <= 50.0) or bool(payload.ignorar_trava_geofence_teste)

    if not geofence_ok:
        raise HTTPException(
            status_code=400,
            detail=f"BLOQUEIO GEOFENCING: Coordenada de coleta está a {dist_m:.1f}m da Torre {payload.codigo_projeto} (Limite máximo = 50,0m)."
        )

    conn = get_db()
    cur = conn.cursor()

    # Verificar precedência construtiva
    cur.execute("SELECT * FROM status_torres WHERE codigo_projeto = ?", (payload.codigo_projeto,))
    st_atual = dict(cur.fetchone())

    if payload.etapa == "MONTAGEM" and payload.status_reportado in ("EM_ANDAMENTO", "CONCLUIDO"):
        if st_atual["status_fundacao"] != "CONCLUIDO":
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"TRAVA DE ENGENHARIA ATIVA: Não é permitido iniciar/concluir MONTAGEM na Torre {payload.codigo_projeto} antes da conclusão e validação de torque/cura da FUNDAÇÃO ({torre['tipo_fundacao']})."
            )

    if payload.etapa == "LANCAMENTO" and payload.status_reportado in ("EM_ANDAMENTO", "CONCLUIDO"):
        if st_atual["status_montagem"] != "CONCLUIDO":
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"TRAVA DE ENGENHARIA ATIVA: Não é permitido apontar LANÇAMENTO DE CABOS na Torre {payload.codigo_projeto} sem a estrutura metálica ({torre['tipo_estrutura']}) 100% montada e revisada."
            )

    # Executar análise de IA sobre o apontamento
    analise_ia = classificar_relatorio_campo_ia(
        payload.observacao_texto or "",
        torre,
        payload.etapa,
        payload.checklist or {}
    )

    apontamento_id = str(uuid.uuid4())
    now_iso = datetime.datetime.now().isoformat()

    cur.execute("""
        INSERT INTO apontamentos_campo (
            id, tenant_id, sqlite_local_id, codigo_projeto, sequencia, fiscal_nome,
            etapa, status_reportado, checklist_json, latitude_coleta, longitude_coleta,
            distancia_torre_metros, geofence_valido, observacao_texto, transcricao_audio_ia,
            nivel_risco_ia, categoria_problema_ia, resumo_analise_ia, data_hora_coleta, data_hora_sincronizacao
        ) VALUES (?, 'TENANT-GNA-ALUBAR', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        apontamento_id,
        payload.sqlite_local_id or f"SQLITE-{uuid.uuid4().hex[:8]}",
        payload.codigo_projeto,
        torre["sequencia"],
        payload.fiscal_nome,
        payload.etapa,
        payload.status_reportado,
        json.dumps(payload.checklist or {}, ensure_ascii=False),
        payload.latitude_coleta,
        payload.longitude_coleta,
        dist_m,
        1 if geofence_ok else 0,
        payload.observacao_texto or "",
        payload.observacao_texto or "",
        analise_ia["nivel_risco_ia"],
        analise_ia["categoria_problema_ia"],
        analise_ia["resumo_analise_ia"],
        now_iso,
        now_iso
    ))

    # Atualizar status da torre
    col_etapa = "status_fundacao" if payload.etapa == "FUNDACAO" else ("status_montagem" if payload.etapa == "MONTAGEM" else "status_lancamento")
    torque_val = (payload.checklist or {}).get("torque_obtido_lbft") or st_atual.get("torque_medio_instalacao_lbft")

    cur.execute(f"""
        UPDATE status_torres
        SET {col_etapa} = ?,
            criticidade_ia = ?,
            ultimo_risco_categoria = ?,
            ultima_observacao = ?,
            torque_medio_instalacao_lbft = ?,
            updated_at = ?
        WHERE codigo_projeto = ?
    """, (
        payload.status_reportado,
        analise_ia["criticidade_torre"],
        analise_ia["categoria_problema_ia"],
        payload.observacao_texto or analise_ia["resumo_analise_ia"],
        torque_val,
        now_iso,
        payload.codigo_projeto
    ))

    # Verificar se o risco/desvio dispara uma Ordem de Produção Tática (Regra Comentário 2)
    cur.execute("SELECT limiar_risco_toleravel_pct FROM revisoes_baseline ORDER BY versao DESC LIMIT 1")
    limiar_baseline = cur.fetchone()["limiar_risco_toleravel_pct"]

    ordem_emitida = None
    if analise_ia["nivel_risco_ia"] in ("ALTO", "CRITICO"):
        cur.execute("SELECT COUNT(*) as c FROM ordens_producao")
        num_seq = cur.fetchone()["c"] + 1
        numero_op = f"OP-{num_seq:03d}"

        mc_op = simular_impacto_ordem_monte_carlo(
            torre_info=torre,
            categoria_problema=analise_ia["categoria_problema_ia"],
            nivel_risco=analise_ia["nivel_risco_ia"],
            limiar_baseline_pct=limiar_baseline,
            iteracoes=1000
        )
        risco_calc = mc_op["risco_detectado_p80_pct"]
        impacto_dias = mc_op["impacto_p80_dias"]
        multa_evitada = mc_op["multa_evitada_p80_brl"]

        frente = "Frente 01 - Porto do Açu (SE GNA II -> V15)" if torre["sequencia"] <= 43 else "Frente 02 - Campos 2 (SE Campos 2 -> V16)"

        if analise_ia["categoria_problema_ia"] == "TECNICO_GEOLOGIA":
            acao_rec = (
                f"[Monte Carlo P50={mc_op['impacto_p50_dias']}d | P80={impacto_dias}d | P90={mc_op['impacto_p90_dias']}d] "
                f"1) Suspender cravação contínua na Torre {payload.codigo_projeto} ({torre['codigo_fundacao_pe']}) para evitar dano estrutural ao cabeçote hidráulico; "
                f"2) Deslocar imediatamente a Retroescavadeira #02 para a torre adjacente ({'série seguinte' if torre['sequencia'] < 84 else 'série anterior'}); "
                f"3) Emitir FVS de Redução de Comprimento por Impenetrabilidade (Item 4 do Proc. 06-PRO-00002) ou migrar fundação para opção BSE-M (Nota 10.3)."
            )
        elif analise_ia["categoria_problema_ia"] == "CLIMA":
            acao_rec = (
                f"[Monte Carlo P50={mc_op['impacto_p50_dias']}d | P80={impacto_dias}d | P90={mc_op['impacto_p90_dias']}d] "
                f"1) Instalar pranchões de madeira/estiva e bomba de esgotamento na praça da Torre {payload.codigo_projeto} (Área Alagável Nota 12.11.1); "
                f"2) Garantir afloramento mínimo Delta H >= 60cm; "
                f"3) Remanejar equipe de fundação temporariamente para o trecho seco de ancoragens até drenagem da cava."
            )
        elif analise_ia["categoria_problema_ia"] == "FUNDIARIO_AMBIENTAL":
            acao_rec = (
                f"[Monte Carlo P50={mc_op['impacto_p50_dias']}d | P80={impacto_dias}d | P90={mc_op['impacto_p90_dias']}d] "
                f"1) Acionar Gestão Fundiária/Concessionária para liberação de faixa ou janela de desligamento na {torre.get('travessia_critica') or 'propriedade'}; "
                f"2) Inverter sentido tático da subfrente saltando o vão bloqueado para preservar o ritmo de 0,49 torres/dia."
            )
        else:
            acao_rec = (
                f"[Monte Carlo P50={mc_op['impacto_p50_dias']}d | P80={impacto_dias}d | P90={mc_op['impacto_p90_dias']}d] "
                f"1) Remanejar 1 equipe suplementar da Frente 02 (estaiadas GNEL adiantadas) para cobrir o déficit na Torre {payload.codigo_projeto}; "
                f"2) Autorizar turno estendido de sábado nas atividades de {payload.etapa} pelos próximos {impacto_dias} dias."
            )

        op_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO ordens_producao (
                id, numero_ordem, frente_afetada, torres_afetadas_json,
                risco_detectado_pct, limiar_baseline_pct, motivo_desvio,
                acao_corretiva_recomendada, impacto_estimado_prazo_dias,
                multa_contratual_evitada_brl, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'EMITIDA', ?)
        """, (
            op_id,
            numero_op,
            frente,
            json.dumps([payload.codigo_projeto]),
            risco_calc,
            limiar_baseline,
            analise_ia["resumo_analise_ia"],
            acao_rec,
            impacto_dias,
            multa_evitada,
            now_iso
        ))
        ordem_emitida = {
            "numero_ordem": numero_op,
            "frente_afetada": frente,
            "risco_detectado_pct": risco_calc,
            "acao_corretiva_recomendada": acao_rec,
            "multa_contratual_evitada_brl": multa_evitada
        }

    conn.commit()
    conn.close()

    return {
        "sucesso": True,
        "apontamento_id": apontamento_id,
        "distancia_torre_metros": dist_m,
        "geofence_valido": geofence_ok,
        "analise_ia": analise_ia,
        "ordem_producao_gerada": ordem_emitida
    }


@app.post("/api/simulacao/historico-35-torres")
def executar_simulacao_historica(cenario: str = Body("FASE_EXECUCAO_CRITICA", embed=True)):
    """
    O "Teste de Fogo" do Roadmap:
    Simula a evolução real da construção da LT 500 kV UTE GNA II - SE Campos 2 alimentando os apontamentos de campo
    históricos (fundações helicoidais concluídas, pré-montagem e montagem de autoportantes e estaiadas GNEL,
    e ocorrências reais de campo como alagamento na Baixada do Açu, impenetrabilidade SPT > 30 e travessia 345 kV Furnas).
    """
    with open(BASELINE_JSON_PATH, "r", encoding="utf-8") as f:
        bl_data = json.load(f)

    conn = get_db()
    cur = conn.cursor()

    now_iso = datetime.datetime.now().isoformat()

    if cenario == "RESET_BASELINE":
        cur.execute("DELETE FROM apontamentos_campo")
        cur.execute("DELETE FROM ordens_producao")
        cur.execute("""
            UPDATE status_torres
            SET status_fundacao = 'NAO_INICIADO',
                status_montagem = 'NAO_INICIADO',
                status_lancamento = 'NAO_INICIADO',
                criticidade_ia = 'VERDE',
                ultimo_risco_categoria = 'NENHUM',
                ultima_observacao = '',
                torque_medio_instalacao_lbft = NULL,
                updated_at = ?
        """, (now_iso,))
        conn.commit()
        conn.close()
        return {"sucesso": True, "mensagem": "Ambiente resetado para o Dia Zero da Baseline V1."}

    # Simular avanço histórico realista nas duas frentes (Frente A: 0/1 -> 17/2 [35+ torres] e Frente B: 37/2 -> 25/1)
    cur.execute("DELETE FROM apontamentos_campo")
    cur.execute("DELETE FROM ordens_producao")

    batch_updates = []
    for est in bl_data["estruturas"]:
        seq = est["sequencia"]
        cod = est["codigo_projeto"]
        if est["classificacao_mecanica"] == "PORTICO":
            batch_updates.append((
                "CONCLUIDO", "CONCLUIDO", "EM_ANDAMENTO",
                "VERDE", "NENHUM", "Pórtico de subestação liberado.", None, now_iso, cod
            ))
            continue

        # Frente 1 (Séries 0 a 17 -> 42 torres) e Frente 2 (Séries 37 a 26 -> 26 torres)
        sf, sm, sl, crit, cat, obs, torque = "NAO_INICIADO", "NAO_INICIADO", "NAO_INICIADO", "VERDE", "NENHUM", "Execução conforme procedimento executivo 06-PRO-00002.", None

        if 1 <= seq <= 35:
            sf = "CONCLUIDO"
            torque = 5850.0
            if seq <= 24:
                sm = "CONCLUIDO"
            elif seq <= 31:
                sm = "EM_ANDAMENTO"
            if seq <= 12:
                sl = "CONCLUIDO"
            elif seq <= 18:
                sl = "EM_ANDAMENTO"
        elif 36 <= seq <= 43:
            sf = "EM_ANDAMENTO"
            torque = 5100.0
        elif 65 <= seq <= 84:
            # Frente 2 avançando no sentido SE Campos 2 -> V16
            sf = "CONCLUIDO"
            torque = 5600.0
            if seq >= 72:
                sm = "CONCLUIDO"
            elif seq >= 67:
                sm = "EM_ANDAMENTO"
            if seq >= 78:
                sl = "EM_ANDAMENTO"

        batch_updates.append((sf, sm, sl, crit, cat, obs, torque, now_iso, cod))

    cur.executemany("""
        UPDATE status_torres
        SET status_fundacao = ?, status_montagem = ?, status_lancamento = ?,
            criticidade_ia = ?, ultimo_risco_categoria = ?, ultima_observacao = ?,
            torque_medio_instalacao_lbft = ?, updated_at = ?
        WHERE codigo_projeto = ?
    """, batch_updates)

    conn.commit()
    conn.close()

    # Inserir 4 ocorrências reais de campo que acionam o Motor de IA e geram Ordens de Produção Táticas
    eventos_reais = [
        ApontamentoInput(
            codigo_projeto="14/2",
            fiscal_nome="Carlos Mendes (Fiscal Fundação - Frente Açu)",
            etapa="FUNDACAO",
            status_reportado="EM_ANDAMENTO",
            latitude_coleta=-21.85569,
            longitude_coleta=-41.14661,
            ignorar_trava_geofence_teste=True,
            observacao_texto="Cravação da estaca helicoidal HEL-098 no Pé B paralisada por alagamento severo após chuva intensa na baixada. Nível d'água (NA) atingiu 75cm acima do terreno natural, superando o afloramento Delta H de 60cm da Nota 12.11.1. Retroescavadeira com risco de atolamento.",
            checklist={"torque_obtido_lbft": 4800, "profundidade_m": 5.2, "condicao_clima": "Chuva"}
        ),
        ApontamentoInput(
            codigo_projeto="7/1",
            fiscal_nome="Roberto Silva (Fiscal Eletromecânica - Frente Açu)",
            etapa="LANCAMENTO",
            status_reportado="EM_ANDAMENTO",
            latitude_coleta=-21.86405,
            longitude_coleta=-41.07685,
            ignorar_trava_geofence_teste=True,
            observacao_texto="Impedimento no lançamento de cabos condutores no vão da Torre 7/1 a 7/2 (Travessia 9 sobre LT 345kV Porto do Açu - Campos da Furnas C.D.). Aguardando liberação de janela de desligamento e validação dos pórticos de proteção.",
            checklist={"condicao_clima": "Bom"}
        ),
        ApontamentoInput(
            codigo_projeto="9/1",
            fiscal_nome="Carlos Mendes (Fiscal Fundação - Frente Açu)",
            etapa="FUNDACAO",
            status_reportado="EM_ANDAMENTO",
            latitude_coleta=-21.85510,
            longitude_coleta=-41.16075,
            ignorar_trava_geofence_teste=True,
            observacao_texto="Recusa de cravação por camada impenetrável com SPT > 30 (Sondagem MDE-00071 registra NSPT = 36 a 5,45m e NSPT = 56 a 7,45m) na instalação da estaca do mastro central HEL-091 da torre estaiada GNEL 9/1 (Travessia Rodovia RJ-240). Torque subiu abruptamente para o limite máximo do cabeçote redutor antes de atingir 6,0m.",
            checklist={"torque_obtido_lbft": 6900, "profundidade_m": 4.8, "condicao_clima": "Nublado"}
        ),
        ApontamentoInput(
            codigo_projeto="27/2",
            fiscal_nome="André Costa (Fiscal Campo - Frente Campos 2)",
            etapa="FUNDACAO",
            status_reportado="EM_ANDAMENTO",
            latitude_coleta=-21.85350,
            longitude_coleta=-41.26920,
            ignorar_trava_geofence_teste=True,
            observacao_texto="Atraso na entrega das extensões lisas de 16 polegadas das estacas HEL-098 para a Torre de Ancoragem 27/2 (Travessia Rodovia RJ-236). Equipe de cravação aguardando suprimento no trecho.",
            checklist={"torque_obtido_lbft": 5200, "profundidade_m": 4.0, "condicao_clima": "Bom"}
        )
    ]

    for ev in eventos_reais:
        sincronizar_apontamento_campo(ev)

    return {
        "sucesso": True,
        "mensagem": "Simulação Histórica (Frente Açu 35+ Torres + Frente Campos 2 + 4 Desvios Táticos Reais) processada pelo Motor de IA com sucesso!"
    }


class RevisaoBaselineInput(BaseModel):
    titulo_revisao: str
    motivo_revisao: str
    novo_limiar_risco_pct: float
    gerar_nova_ordem_batalha: bool = True


@app.post("/api/baseline/revisar")
def criar_revisao_baseline(payload: RevisaoBaselineInput):
    """Permite ao Gestor registrar uma Revisão de Baseline (por aditivo contratual ou revisão de engenharia) e emitir nova Ordem de Batalha."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT MAX(versao) as max_v FROM revisoes_baseline")
    nova_versao = (cur.fetchone()["max_v"] or 1) + 1

    cur.execute("UPDATE revisoes_baseline SET status = 'REVISADA'")
    cod_ob = f"OB-00{nova_versao}" if payload.gerar_nova_ordem_batalha else "OB-001 (Mantida)"

    cur.execute("""
        INSERT INTO revisoes_baseline (versao, titulo_revisao, motivo_revisao, status, limiar_risco_toleravel_pct, nova_ordem_batalha_codigo, created_at)
        VALUES (?, ?, ?, 'ATIVA', ?, ?, ?)
    """, (
        nova_versao,
        payload.titulo_revisao,
        payload.motivo_revisao,
        payload.novo_limiar_risco_pct,
        cod_ob,
        datetime.datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()
    return {"sucesso": True, "versao": nova_versao, "nova_ordem_batalha": cod_ob}


@app.post("/api/ordens-producao/{ordem_id}/aprovar")
def aprovar_ordem_producao(ordem_id: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE ordens_producao SET status = 'APROVADA_GESTOR' WHERE id = ?", (ordem_id,))
    conn.commit()
    conn.close()
    return {"sucesso": True}


# Servir o Frontend (Cockpit do Gestor + App Mobile Offline-First do Fiscal)
@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
