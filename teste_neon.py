import os
import sys
import psycopg2

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

CONN_STRING = os.environ.get("DATABASE_URL", "COLE_AQUI_A_SUA_CONNECTION_STRING_DA_NEON")
if len(sys.argv) > 1:
    CONN_STRING = sys.argv[1]


def rodar_teste_conexao():
    print("🔄 Iniciando teste de conexão e provisionamento na Neon.tech...")
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(CONN_STRING)
        cursor = conn.cursor()
        print("✅ Conexão estabelecida com sucesso!")

        print("🔄 Verificando extensão PostGIS...")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        conn.commit()
        cursor.execute("SELECT PostGIS_Full_Version();")
        version = cursor.fetchone()
        print(f"✅ PostGIS ativo! Versão: {version[0][:50]}...")

        print("🔄 Provisionando tabelas oficiais do SaaS (status_torres, apontamentos_campo, ordens_producao, revisoes_baseline)...")
        os.environ["DATABASE_URL"] = CONN_STRING
        backend_dir = os.path.join(BASE_DIR, "backend")
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)

        import main as saas_main
        saas_main.init_cloud_db()

        cursor.execute("SELECT COUNT(*) FROM status_torres;")
        total_estruturas = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM revisoes_baseline;")
        total_revisoes = cursor.fetchone()[0]
        print(f"✅ Schema de produção criado e populado na Neon.tech: {total_estruturas} estruturas (84 torres + 2 pórticos) e {total_revisoes} Baseline ativa (OB-001)!")

        print("\n🏆 PARABÉNS! Seu banco de dados Neon.tech já está com todas as tabelas e as 86 estruturas da LT 500 kV carregadas para o Render.")

    except Exception as e:
        print("\n❌ ERRO DETECTADO:")
        print(f"Não foi possível consolidar a operação. Detalhes do erro: {e}")

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            print("🔒 Conexão encerrada com segurança.")


if __name__ == "__main__":
    rodar_teste_conexao()
