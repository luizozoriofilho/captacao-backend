import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv

from database import buscar_usuario_por_id, buscar_usuario_por_email

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "chave-secreta-padrao-troque-em-producao")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha: str, hash: str) -> bool:
    return pwd_context.verify(senha, hash)


def criar_token(usuario_id: int, email: str) -> str:
    expira = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(usuario_id), "email": email, "exp": expira}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decodificar_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_usuario_atual(token: str = Depends(oauth2_scheme)):
    payload = decodificar_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    usuario_id = int(payload["sub"])
    usuario = buscar_usuario_por_id(usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Verificar acesso
    plano = usuario.get("plano")
    if plano == "bloqueado":
        raise HTTPException(status_code=403, detail="Acesso bloqueado. Entre em contato com o suporte.")

    if plano == "trial":
        trial_ate = usuario.get("trial_ate")
        if trial_ate and datetime.utcnow() > trial_ate:
            raise HTTPException(status_code=403, detail="Trial expirado. Adquira uma licença para continuar.")

    return usuario


async def get_admin(usuario=Depends(get_usuario_atual)):
    if usuario.get("email") != ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return usuario


def dias_restantes_trial(usuario: dict) -> Optional[int]:
    if usuario.get("plano") != "trial":
        return None
    trial_ate = usuario.get("trial_ate")
    if not trial_ate:
        return None
    delta = trial_ate - datetime.utcnow()
    return max(0, delta.days)
