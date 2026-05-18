import os
import csv
import io
import httpx
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

import database as db
from auth import (
    hash_senha, verificar_senha, criar_token,
    get_usuario_atual, get_admin, dias_restantes_trial
)

load_dotenv()
db.init_db()

app = FastAPI(title="Captação Inteligente API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── WebSocket Manager ─────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: dict[int, list[WebSocket]] = {}

    async def connect(self, usuario_id: int, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(usuario_id, []).append(ws)

    def disconnect(self, usuario_id: int, ws: WebSocket):
        if usuario_id in self.active:
            self.active[usuario_id].remove(ws)

    async def send(self, usuario_id: int, message: str):
        for ws in self.active.get(usuario_id, []):
            try:
                await ws.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()


# ── Schemas ───────────────────────────────────────────────

class CadastroSchema(BaseModel):
    email: str
    senha: str
    nome: str

class LoginSchema(BaseModel):
    email: str
    senha: str

class BuscaSchema(BaseModel):
    localidade_id: str
    localidade_nome: str
    localidade_path: str
    tipo_imovel: List[str] = []
    quartos: Optional[int] = None
    vagas: Optional[int] = None
    preco_min: Optional[int] = None
    preco_max: Optional[int] = None
    quantidade: int = 5
    pesquisa: Optional[str] = None

class ContatoSchema(BaseModel):
    busca_id: int
    titulo: Optional[str] = None
    condominio: Optional[str] = None
    preco: Optional[str] = None
    telefone: Optional[str] = None
    url: Optional[str] = None
    list_id: Optional[str] = None
    fonte: Optional[str] = None
    mensagem_enviada: bool = False
    data_envio: Optional[datetime] = None
    descartado: bool = False
    motivo_descarte: Optional[str] = None
    tipo_mensagem: Optional[str] = None

class BuscaConcluidaSchema(BaseModel):
    total_captados: Optional[int] = None

class BuscaErroSchema(BaseModel):
    erro: str

class AlterarPlanoSchema(BaseModel):
    usuario_id: int
    plano: str
    suporte_dias: Optional[int] = None
    trial_dias: Optional[int] = None

class LogSchema(BaseModel):
    mensagem: str
    usuario_id: int


# ── Rotas públicas ────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "app": "Captação Inteligente v2"}


@app.post("/auth/cadastro")
def cadastro(dados: CadastroSchema):
    if db.buscar_usuario_por_email(dados.email):
        raise HTTPException(status_code=400, detail="Email já cadastrado")
    trial_ate = datetime.utcnow() + timedelta(days=7)
    usuario_id = db.criar_usuario(
        email=dados.email,
        senha_hash=hash_senha(dados.senha),
        nome=dados.nome,
        trial_ate=trial_ate,
    )
    token = criar_token(usuario_id, dados.email)
    return {
        "token": token,
        "usuario_id": usuario_id,
        "nome": dados.nome,
        "plano": "trial",
        "trial_dias_restantes": 7,
    }


@app.post("/auth/login")
def login(dados: LoginSchema):
    usuario = db.buscar_usuario_por_email(dados.email)
    if not usuario or not verificar_senha(dados.senha, usuario["senha_hash"]):
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")
    token = criar_token(usuario["id"], usuario["email"])
    trial = dias_restantes_trial(usuario)
    return {
        "token": token,
        "usuario_id": usuario["id"],
        "nome": usuario["nome"],
        "plano": usuario["plano"],
        "trial_dias_restantes": trial,
    }


# ── Localidades (proxy OLX autocomplete) ─────────────────

@app.get("/localidades")
async def localidades(q: str = Query(..., min_length=2)):
    url = f"https://location-autocomplete.olx.com.br/location?q={q}"
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get(url)
            return resp.json()
        except Exception:
            return []


# ── Buscas ────────────────────────────────────────────────

@app.post("/buscas")
def criar_busca(dados: BuscaSchema, usuario=Depends(get_usuario_atual)):
    busca_id = db.criar_busca(usuario["id"], dados.dict())
    db.registrar_atividade(usuario["id"], "busca_criada", f"localidade={dados.localidade_nome}")
    return {"busca_id": busca_id, "status": "pendente"}


@app.get("/buscas")
def listar_buscas(usuario=Depends(get_usuario_atual)):
    return db.listar_buscas(usuario["id"])


# ── Rotas do agente ───────────────────────────────────────

@app.get("/buscas/pendente")
def busca_pendente(usuario_id: int = Query(...)):
    busca = db.buscar_pendente(usuario_id)
    if not busca:
        return {"busca": None}
    db.atualizar_status_busca(busca["id"], "em_andamento")
    return {"busca": busca}


@app.post("/buscas/{busca_id}/concluida")
def busca_concluida(busca_id: int, dados: BuscaConcluidaSchema):
    db.atualizar_status_busca(busca_id, "concluida")
    return {"ok": True}


@app.post("/buscas/{busca_id}/erro")
def busca_erro(busca_id: int, dados: BuscaErroSchema):
    db.atualizar_status_busca(busca_id, "erro", erro=dados.erro)
    return {"ok": True}


@app.post("/agente/contato")
async def agente_contato(dados: ContatoSchema, usuario_id: int = Query(...)):
    contato_id = db.salvar_contato(usuario_id, dados.busca_id, dados.dict())
    if contato_id:
        await manager.send(usuario_id, f"CONTATO:{dados.titulo}|{dados.telefone or ''}|{dados.url or ''}")
    return {"contato_id": contato_id}


@app.post("/agente/log")
async def agente_log(dados: LogSchema):
    await manager.send(dados.usuario_id, f"LOG:{dados.mensagem}")
    return {"ok": True}


# ── Contatos ──────────────────────────────────────────────

@app.get("/contatos")
def listar_contatos(
    apenas_com_telefone: bool = False,
    apenas_nao_enviados: bool = False,
    usuario=Depends(get_usuario_atual)
):
    return db.listar_contatos(usuario["id"], apenas_com_telefone, apenas_nao_enviados)


@app.get("/contatos/stats")
def stats_contatos(usuario=Depends(get_usuario_atual)):
    return db.stats_contatos(usuario["id"])


@app.get("/contatos/exportar")
def exportar_contatos(usuario=Depends(get_usuario_atual)):
    contatos = db.listar_contatos(usuario["id"])

    output = io.StringIO()
    output.write('\ufeff')  # BOM UTF-8
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["Título", "Condomínio", "Preço", "Telefone", "WhatsApp", "URL", "Fonte", "Mensagem Enviada", "Data"])

    for c in contatos:
        tel = c.get("telefone") or ""
        wa = f"https://wa.me/55{tel.replace(' ','').replace('-','').replace('(','').replace(')','')}" if tel else ""
        writer.writerow([
            c.get("titulo", ""),
            c.get("condominio", ""),
            c.get("preco", ""),
            tel,
            wa,
            c.get("url", ""),
            c.get("fonte", ""),
            "Sim" if c.get("mensagem_enviada") else "Não",
            str(c.get("criado_em", ""))[:16],
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contatos_captacao.csv"}
    )


# ── Admin ─────────────────────────────────────────────────

@app.get("/admin/usuarios")
def admin_usuarios(admin=Depends(get_admin)):
    return db.listar_usuarios()


@app.post("/admin/plano")
def admin_plano(dados: AlterarPlanoSchema, admin=Depends(get_admin)):
    suporte_ate = None
    trial_ate = None
    if dados.suporte_dias:
        suporte_ate = datetime.utcnow() + timedelta(days=dados.suporte_dias)
    if dados.trial_dias:
        trial_ate = datetime.utcnow() + timedelta(days=dados.trial_dias)
    db.atualizar_plano(dados.usuario_id, dados.plano, suporte_ate, trial_ate)
    return {"ok": True}


@app.post("/admin/trial")
def admin_trial(dados: AlterarPlanoSchema, admin=Depends(get_admin)):
    trial_ate = datetime.utcnow() + timedelta(days=dados.trial_dias or 7)
    db.atualizar_plano(dados.usuario_id, "trial", trial_ate=trial_ate)
    return {"ok": True}


# ── WebSocket ─────────────────────────────────────────────

@app.websocket("/ws/{usuario_id}")
async def websocket_endpoint(websocket: WebSocket, usuario_id: int):
    await manager.connect(usuario_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(usuario_id, websocket)
