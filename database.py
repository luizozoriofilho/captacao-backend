import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

DATABASE_URL = os.getenv("postgresql://postgres:czAvHCu3nSwPY3Pt@db.lwtxxytecyffsynrqkbh.supabase.co:5432/postgres")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            nome TEXT,
            plano TEXT DEFAULT 'trial',
            trial_ate TIMESTAMP,
            suporte_ate TIMESTAMP,
            criado_em TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessoes (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            token TEXT UNIQUE NOT NULL,
            criado_em TIMESTAMP DEFAULT NOW(),
            expira_em TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS buscas (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            localidade_id TEXT,
            localidade_nome TEXT,
            localidade_path TEXT,
            tipo_imovel TEXT[],
            quartos INTEGER,
            vagas INTEGER,
            preco_min INTEGER,
            preco_max INTEGER,
            quantidade INTEGER DEFAULT 50,
            status TEXT DEFAULT 'pendente',
            criado_em TIMESTAMP DEFAULT NOW(),
            concluida_em TIMESTAMP,
            erro TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS contatos (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            busca_id INTEGER REFERENCES buscas(id),
            titulo TEXT,
            condominio TEXT,
            preco TEXT,
            telefone TEXT,
            url TEXT,
            list_id TEXT,
            fonte TEXT,
            mensagem_enviada BOOLEAN DEFAULT FALSE,
            data_envio TIMESTAMP,
            criado_em TIMESTAMP DEFAULT NOW(),
            descartado BOOLEAN DEFAULT FALSE,
            motivo_descarte TEXT,
            tipo_mensagem TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS atividade (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            acao TEXT,
            detalhe TEXT,
            criado_em TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


# ── Usuários ──────────────────────────────────────────────

def criar_usuario(email: str, senha_hash: str, nome: str, trial_ate):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO usuarios (email, senha_hash, nome, plano, trial_ate) VALUES (%s, %s, %s, 'trial', %s) RETURNING id",
        (email, senha_hash, nome, trial_ate)
    )
    usuario_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return usuario_id


def buscar_usuario_por_email(email: str):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None


def buscar_usuario_por_id(usuario_id: int):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM usuarios WHERE id = %s", (usuario_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None


def listar_usuarios():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, email, nome, plano, trial_ate, suporte_ate, criado_em FROM usuarios ORDER BY criado_em DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def atualizar_plano(usuario_id: int, plano: str, suporte_ate=None, trial_ate=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE usuarios SET plano=%s, suporte_ate=%s, trial_ate=%s WHERE id=%s",
        (plano, suporte_ate, trial_ate, usuario_id)
    )
    conn.commit()
    cur.close()
    conn.close()


# ── Buscas ────────────────────────────────────────────────

def criar_busca(usuario_id: int, dados: dict) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO buscas (usuario_id, localidade_id, localidade_nome, localidade_path,
            tipo_imovel, quartos, vagas, preco_min, preco_max, quantidade)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        usuario_id,
        dados.get("localidade_id"),
        dados.get("localidade_nome"),
        dados.get("localidade_path"),
        dados.get("tipo_imovel", []),
        dados.get("quartos"),
        dados.get("vagas"),
        dados.get("preco_min"),
        dados.get("preco_max"),
        dados.get("quantidade", 50),
    ))
    busca_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return busca_id


def buscar_pendente(usuario_id: int):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM buscas WHERE usuario_id=%s AND status='pendente' ORDER BY criado_em ASC LIMIT 1",
        (usuario_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None


def atualizar_status_busca(busca_id: int, status: str, erro: str = None):
    conn = get_conn()
    cur = conn.cursor()
    concluida_em = datetime.now() if status in ("concluida", "erro") else None
    cur.execute(
        "UPDATE buscas SET status=%s, erro=%s, concluida_em=%s WHERE id=%s",
        (status, erro, concluida_em, busca_id)
    )
    conn.commit()
    cur.close()
    conn.close()


def listar_buscas(usuario_id: int):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM buscas WHERE usuario_id=%s ORDER BY criado_em DESC", (usuario_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


# ── Contatos ──────────────────────────────────────────────

def salvar_contato(usuario_id: int, busca_id: int, dados: dict):
    conn = get_conn()
    cur = conn.cursor()
    # Evita duplicata por list_id + usuario
    cur.execute(
        "SELECT id FROM contatos WHERE usuario_id=%s AND list_id=%s",
        (usuario_id, dados.get("list_id"))
    )
    if cur.fetchone():
        cur.close()
        conn.close()
        return None

    cur.execute("""
        INSERT INTO contatos (usuario_id, busca_id, titulo, condominio, preco, telefone,
            url, list_id, fonte, mensagem_enviada, data_envio, descartado, motivo_descarte, tipo_mensagem)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        usuario_id, busca_id,
        dados.get("titulo"), dados.get("condominio"), dados.get("preco"),
        dados.get("telefone"), dados.get("url"), dados.get("list_id"),
        dados.get("fonte"), dados.get("mensagem_enviada", False),
        dados.get("data_envio"), dados.get("descartado", False),
        dados.get("motivo_descarte"), dados.get("tipo_mensagem"),
    ))
    contato_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return contato_id


def listar_contatos(usuario_id: int, apenas_com_telefone: bool = False, apenas_nao_enviados: bool = False):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    query = "SELECT * FROM contatos WHERE usuario_id=%s AND descartado=FALSE"
    params = [usuario_id]
    if apenas_com_telefone:
        query += " AND telefone IS NOT NULL AND telefone != ''"
    if apenas_nao_enviados:
        query += " AND mensagem_enviada=FALSE"
    query += " ORDER BY criado_em DESC"
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def stats_contatos(usuario_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM contatos WHERE usuario_id=%s AND descartado=FALSE", (usuario_id,))
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM contatos WHERE usuario_id=%s AND telefone IS NOT NULL AND telefone != '' AND descartado=FALSE", (usuario_id,))
    com_telefone = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM contatos WHERE usuario_id=%s AND mensagem_enviada=TRUE AND descartado=FALSE", (usuario_id,))
    mensagem_enviada = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {"total": total, "com_telefone": com_telefone, "mensagem_enviada": mensagem_enviada}


def registrar_atividade(usuario_id: int, acao: str, detalhe: str = ""):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO atividade (usuario_id, acao, detalhe) VALUES (%s, %s, %s)",
        (usuario_id, acao, detalhe)
    )
    conn.commit()
    cur.close()
    conn.close()
