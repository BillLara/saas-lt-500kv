-- ============================================================================
-- PLATAFORMA SAAS AUTÔNOMA DE ACOMPANHAMENTO TÁTICO DE LINHAS DE TRANSMISSÃO (LT)
-- Modelagem PostgreSQL Multi-Tenant (Fase 1 - MVP 35 Torres)
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. TENANTS (Isolamento Multi-inquilino: Concessionárias / Consórcios / Gestoras)
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nome VARCHAR(255) NOT NULL,
    cnpj VARCHAR(20) UNIQUE,
    plano_assinatura VARCHAR(50) DEFAULT 'ENTERPRISE_KM',
    ativo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. USUÁRIOS (RBAC: GESTOR vs FISCAL)
CREATE TABLE usuarios (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nome VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    senha_hash VARCHAR(255) NOT NULL,
    perfil VARCHAR(30) NOT NULL CHECK (perfil IN ('GESTOR', 'FISCAL', 'ADMIN')),
    ativo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. PROJETOS (Empreendimentos de Linhas de Transmissão)
CREATE TABLE projetos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nome VARCHAR(255) NOT NULL,
    codigo_lt VARCHAR(100) NOT NULL,
    tensao_kv NUMERIC(6,2),
    extensao_km NUMERIC(10,2) NOT NULL,
    total_torres INTEGER NOT NULL DEFAULT 35,
    data_inicio_prevista DATE,
    data_termino_prevista DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. BASELINES (Controle de Versão, Limiar de Risco e Travamento de Meta)
CREATE TABLE baselines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    projeto_id UUID NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    versao INTEGER NOT NULL DEFAULT 1,
    titulo_revisao VARCHAR(255) NOT NULL, -- Ex: 'Baseline V1 - Original', 'Baseline V2 - Aditivo Contratual'
    motivo_revisao TEXT,
    status VARCHAR(30) NOT NULL CHECK (status IN ('EM_VALIDACAO', 'ATIVA', 'REVISADA', 'ARQUIVADA')),
    limiar_risco_toleravel_pct NUMERIC(5,2) NOT NULL DEFAULT 5.00, -- Calculado/definido na validação para disparar Ordens de Produção
    arquivo_ms_project_nome VARCHAR(255),
    arquivo_lista_construcao_nome VARCHAR(255),
    validado_pela_ia BOOLEAN DEFAULT FALSE,
    relatorio_validacao_ia JSONB, -- Inconsistências ou alertas gerados no cruzamento XML x Excel
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(projeto_id, versao)
);

-- 5. TORRES (Originadas da Lista de Construção - Excel)
CREATE TABLE torres (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    projeto_id UUID NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    baseline_id UUID NOT NULL REFERENCES baselines(id) ON DELETE CASCADE,
    codigo_torre VARCHAR(50) NOT NULL, -- Chave comum com MS Project / Campo (Ex: 'T-01', '1', '01')
    sequencia INTEGER NOT NULL,        -- 1 a 35
    lote VARCHAR(50) DEFAULT 'Lote Único',
    trecho VARCHAR(100),
    tipo_estrutura VARCHAR(100),       -- Ex: Suspensão, Ancoragem, Estaiada, Autoportante
    tipo_fundacao VARCHAR(100),        -- Ex: Sapata, Tubulão, Estaca Escavada, Rocha
    tipo_solo VARCHAR(100),            -- Ex: Normal, Mole, Rocha
    peso_aco_ton NUMERIC(10,3),        -- Peso da estrutura metálica em toneladas
    volume_concreto_m3 NUMERIC(10,2),  -- Volume previsto de fundação
    vao_jusante_m NUMERIC(10,2),       -- Vão de lançamento de cabos (metros)
    latitude NUMERIC(10,7),            -- Coordenada para Geofencing (50m) e Mapa Linear
    longitude NUMERIC(10,7),
    cota_terreno NUMERIC(8,2),
    status_atual_fundacao VARCHAR(30) DEFAULT 'NAO_INICIADO' CHECK (status_atual_fundacao IN ('NAO_INICIADO', 'EM_ANDAMENTO', 'CONCLUIDO')),
    status_atual_montagem VARCHAR(30) DEFAULT 'NAO_INICIADO' CHECK (status_atual_montagem IN ('NAO_INICIADO', 'EM_ANDAMENTO', 'CONCLUIDO')),
    status_atual_lancamento VARCHAR(30) DEFAULT 'NAO_INICIADO' CHECK (status_atual_lancamento IN ('NAO_INICIADO', 'EM_ANDAMENTO', 'CONCLUIDO')),
    criticidade_ia VARCHAR(20) DEFAULT 'VERDE' CHECK (criticidade_ia IN ('VERDE', 'AMARELO', 'VERMELHO')),
    metadados_engenharia JSONB,        -- Colunas dinâmicas extras da Lista de Construção
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(baseline_id, codigo_torre)
);

-- 6. PACOTES_CRONOGRAMA (EAP / Tarefas Macro do MS Project XML)
CREATE TABLE pacotes_cronograma (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    baseline_id UUID NOT NULL REFERENCES baselines(id) ON DELETE CASCADE,
    uid_ms_project VARCHAR(100) NOT NULL, -- UID original da tarefa no XML do MS Project
    wbs_codigo VARCHAR(100),              -- Código da EAP (Ex: '1.2.1')
    nome_pacote VARCHAR(255) NOT NULL,    -- Ex: 'Pré-montagem de Torres Estaiadas'
    etapa_macro VARCHAR(50) CHECK (etapa_macro IN ('FUNDACAO', 'MONTAGEM', 'LANCAMENTO', 'PRELIMINARES', 'COMISSIONAMENTO', 'OUTROS')),
    duracao_planejada_dias NUMERIC(8,2),
    data_inicio_planejada DATE,
    data_fim_planejada DATE,
    custo_planejado_pv NUMERIC(14,2) DEFAULT 0.00, -- Planned Value (PV)
    produtividade_requerida_dia NUMERIC(10,3),
    unidade_produtividade VARCHAR(50),             -- Ex: 'torres/dia', 'ton/dia', 'm3/dia'
    recursos_alocados JSONB,                       -- Equipes e maquinários extraídos do MS Project
    avanco_fisico_calculado_ia NUMERIC(5,2) DEFAULT 0.00, -- % proporcional calculado pela IA a partir das torres
    valor_agregado_ev NUMERIC(14,2) DEFAULT 0.00,  -- Earned Value (EV)
    spi_atual NUMERIC(6,3) DEFAULT 1.000,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. VINCULO_TORRE_PACOTE (Matriz Relacional: Pacotes Macro Project <-> Torres Individuais Excel)
CREATE TABLE vinculo_torre_pacote (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    baseline_id UUID NOT NULL REFERENCES baselines(id) ON DELETE CASCADE,
    pacote_id UUID NOT NULL REFERENCES pacotes_cronograma(id) ON DELETE CASCADE,
    torre_id UUID NOT NULL REFERENCES torres(id) ON DELETE CASCADE,
    peso_proporcional NUMERIC(8,5) NOT NULL DEFAULT 1.00000, -- Representatividade da torre no pacote (por qtd, peso ou volume)
    concluido BOOLEAN DEFAULT FALSE,
    data_conclusao TIMESTAMP WITH TIME ZONE,
    UNIQUE(pacote_id, torre_id)
);

-- 8. APONTAMENTOS_CAMPO (Coleta Mobile Offline-First Sincronizada + Análise NLP Gemini)
CREATE TABLE apontamentos_campo (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    projeto_id UUID NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    torre_id UUID NOT NULL REFERENCES torres(id) ON DELETE CASCADE,
    fiscal_id UUID REFERENCES usuarios(id),
    sqlite_local_id VARCHAR(100), -- ID gerado no SQLite do celular para idempotência do Sync Engine
    etapa VARCHAR(50) NOT NULL CHECK (etapa IN ('FUNDACAO', 'MONTAGEM', 'LANCAMENTO')),
    status_reportado VARCHAR(30) NOT NULL CHECK (status_reportado IN ('NAO_INICIADO', 'EM_ANDAMENTO', 'CONCLUIDO')),
    checklist_dinamico JSONB,     -- Respostas específicas adaptadas ao tipo de fundação/estrutura
    latitude_coleta NUMERIC(10,7),
    longitude_coleta NUMERIC(10,7),
    distancia_torre_metros NUMERIC(8,2),
    geofence_valido BOOLEAN DEFAULT TRUE, -- True se coletado <= 50m da coordenada da torre
    observacao_texto TEXT,
    audio_url VARCHAR(500),
    transcricao_audio_ia TEXT,
    fotos_urls JSONB,             -- Lista de URLs de fotos comprimidas
    -- Classificação gerada pelo Motor de IA (Gemini)
    processado_pela_ia BOOLEAN DEFAULT FALSE,
    nivel_risco_ia VARCHAR(20) CHECK (nivel_risco_ia IN ('BAIXO', 'MEDIO', 'ALTO', 'CRITICO')),
    categoria_problema_ia VARCHAR(50) CHECK (categoria_problema_ia IN ('NENHUM', 'CLIMA', 'LOGISTICA_SUPRIMENTOS', 'FUNDIARIO_AMBIENTAL', 'TECNICO_GEOLOGIA', 'PRODUTIVIDADE_EQUIPE')),
    resumo_analise_ia TEXT,
    data_hora_coleta TIMESTAMP WITH TIME ZONE NOT NULL,
    data_hora_sincronizacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 9. ORDENS_BATALHA (Plano de Ataque Estratégico Gerado pós-validação da Baseline)
CREATE TABLE ordens_batalha (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    projeto_id UUID NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    baseline_id UUID NOT NULL REFERENCES baselines(id) ON DELETE CASCADE,
    codigo_ordem VARCHAR(50) NOT NULL, -- Ex: 'OB-001'
    status VARCHAR(30) DEFAULT 'VIGENTE' CHECK (status IN ('VIGENTE', 'SUBSTITUIDA')),
    frentes_trabalho JSONB NOT NULL,   -- Frentes (Ex: Frente A T01->T18 Norte-Sul, Frente B T35->T19 Sul-Norte)
    dimensionamento_recursos JSONB NOT NULL, -- Alocação de equipes e equipamentos por trecho
    analise_estrategica_ia TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 10. ORDENS_PRODUCAO (Ações Corretivas Táticas Geradas pela IA quando Risco > Limiar da Baseline)
CREATE TABLE ordens_producao (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    projeto_id UUID NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    baseline_id UUID NOT NULL REFERENCES baselines(id) ON DELETE CASCADE,
    ordem_batalha_id UUID REFERENCES ordens_batalha(id),
    numero_ordem VARCHAR(50) NOT NULL, -- Ex: 'OP-042'
    frente_afetada VARCHAR(100) NOT NULL,
    torres_afetadas JSONB,             -- Lista de códigos de torres impactadas (Ex: ["T-14", "T-15"])
    risco_detectado_pct NUMERIC(5,2) NOT NULL, -- Valor do desvio/risco que ultrapassou o limiar da baseline
    motivo_desvio TEXT NOT NULL,
    acao_corretiva_recomendada TEXT NOT NULL, -- Sugestão tática da IA (remanejamento de equipe, turno extra, etc.)
    impacto_estimado_prazo_dias INTEGER,
    status VARCHAR(30) DEFAULT 'EMITIDA' CHECK (status IN ('EMITIDA', 'APROVADA_GESTOR', 'EM_EXECUCAO', 'CONCLUIDA', 'DESCARTADA')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Índices para performance analítica e multi-tenancy
CREATE INDEX idx_torres_tenant_projeto ON torres(tenant_id, projeto_id, sequencia);
CREATE INDEX idx_pacotes_baseline ON pacotes_cronograma(tenant_id, baseline_id);
CREATE INDEX idx_apontamentos_torre ON apontamentos_campo(tenant_id, torre_id, data_hora_coleta DESC);
CREATE INDEX idx_ordens_producao_status ON ordens_producao(tenant_id, projeto_id, status);
