from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from backend.config import settings
from backend.models.models import Base, Profe, Estudiante, Curso, Quiz, Resultado, CursoEstudiante
from backend.services.pdf_service import procesar_pdf_zipgrade
from backend.services.storage_service import subir_pdf, generar_url_temporal
from backend.services.suscripcion_service import (
    profe_activo, estudiante_activo, activar_profe, activar_estudiante,
    desactivar_profe, desactivar_estudiante, registrar_pago
)
from datetime import date
import uuid
import os
import httpx

app = FastAPI(title="ZipGrade System API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

engine = create_engine(settings.DATABASE_URL)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)

BOT_PROFE_TOKEN = os.getenv("BOT_PROFE_TOKEN", "")
BOT_ESTUDIANTE_TOKEN = os.getenv("BOT_ESTUDIANTE_TOKEN", "")
BASE_URL = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def send_message(token, chat_id, text):
    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text})

@app.on_event("startup")
async def set_webhooks():
    if BOT_PROFE_TOKEN and BASE_URL:
        async with httpx.AsyncClient() as client:
            await client.get(f"https://api.telegram.org/bot{BOT_PROFE_TOKEN}/setWebhook",
                params={"url": f"https://{BASE_URL}/webhook/profe"})
            await client.get(f"https://api.telegram.org/bot{BOT_ESTUDIANTE_TOKEN}/setWebhook",
                params={"url": f"https://{BASE_URL}/webhook/estudiante"})

@app.post("/webhook/profe")
async def webhook_profe(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    telegram_id = message.get("from", {}).get("id")
    if not chat_id:
        return {"ok": True}
    if text == "/start":
        profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
        if not profe:
            nuevo = Profe(id=uuid.uuid4(), telegram_id=telegram_id,
                nombre=message.get("from", {}).get("first_name", "Profe"),
                email="", activo=False)
            db.add(nuevo)
            db.commit()
            await send_message(BOT_PROFE_TOKEN, chat_id,
                "👋 Bienvenido al sistema ZipGrade.\n\nTu cuenta fue creada. Contacta al administrador para activar tu suscripcion.")
        else:
            if profe.activo:
                await send_message(BOT_PROFE_TOKEN, chat_id,
                    f"✅ Hola {profe.nombre}! Tu suscripcion esta activa.")
            else:
                await send_message(BOT_PROFE_TOKEN, chat_id,
                    "❌ Tu suscripcion no esta activa. Contacta al administrador.")
    else:
        await send_message(BOT_PROFE_TOKEN, chat_id, "Usa /start para comenzar.")
    return {"ok": True}

@app.post("/webhook/estudiante")
async def webhook_estudiante(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    telegram_id = message.get("from", {}).get("id")
    if not chat_id:
        return {"ok": True}
    if text == "/start":
        estudiante = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
        if not estudiante:
            nuevo = Estudiante(id=uuid.uuid4(), telegram_id=telegram_id,
                nombre=message.get("from", {}).get("first_name", "Estudiante"),
                apellido="", activo=False)
            db.add(nuevo)
            db.commit()
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                "👋 Bienvenido al sistema ZipGrade.\n\nTu cuenta fue creada. Contacta al administrador para activar tu suscripcion.")
        else:
            if estudiante.activo:
                resultados = db.query(Resultado).filter(Resultado.estudiante_id == estudiante.id).all()
                if resultados:
                    msg = f"📊 Hola {estudiante.nombre}! Tus resultados:\n\n"
                    for r in resultados:
                        msg += f"• Nota: {r.nota}/5.0\n"
                    await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, msg)
                else:
                    await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                        f"Hola {estudiante.nombre}! Aun no tienes resultados.")
            else:
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                    "❌ Tu suscripcion no esta activa. Contacta al administrador.")
    else:
        await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "Usa /start para comenzar.")
    return {"ok": True}

@app.post("/profes/registrar")
def registrar_profe(data: dict, db: Session = Depends(get_db)):
    profe = db.query(Profe).filter(Profe.telegram_id == data["telegram_id"]).first()
    if profe:
        return profe
    nuevo = Profe(id=uuid.uuid4(), **data)
    db.add(nuevo)
    db.commit()
    return nuevo

@app.get("/profes/by-telegram/{telegram_id}")
def get_profe_by_telegram(telegram_id: int, db: Session = Depends(get_db)):
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if not profe:
        raise HTTPException(status_code=404, detail="Profe no encontrado")
    return profe

@app.get("/profes/activo/{telegram_id}")
def check_profe_activo(telegram_id: int, db: Session = Depends(get_db)):
    return {"activo": profe_activo(telegram_id, db)}

@app.post("/estudiantes/registrar")
def registrar_estudiante(data: dict, db: Session = Depends(get_db)):
    est = db.query(Estudiante).filter(Estudiante.telegram_id == data["telegram_id"]).first()
    if est:
        return est
    nuevo = Estudiante(id=uuid.uuid4(), **data)
    db.add(nuevo)
    db.commit()
    return nuevo

@app.get("/estudiantes/by-telegram/{telegram_id}")
def get_estudiante_by_telegram(telegram_id: int, db: Session = Depends(get_db)):
    est = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
    if not est:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    return est

@app.get("/estudiantes/activo/{telegram_id}")
def check_estudiante_activo(telegram_id: int, db: Session = Depends(get_db)):
    return {"activo": estudiante_activo(telegram_id, db)}

@app.post("/cursos/crear")
def crear_curso(data: dict, db: Session = Depends(get_db)):
    nuevo = Curso(id=uuid.uuid4(), **data)
    db.add(nuevo)
    db.commit()
    return nuevo

@app.get("/cursos/by-profe-telegram/{telegram_id}")
def cursos_by_profe(telegram_id: int, db: Session = Depends(get_db)):
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if not profe:
        raise HTTPException(status_code=404, detail="Profe no encontrado")
    return db.query(Curso).filter(Curso.profe_id == profe.id).all()

@app.post("/quizzes/procesar-pdf")
async def procesar_pdf(archivo: UploadFile = File(...), curso_id: str = Form(...), db: Session = Depends(get_db)):
    contenido = await archivo.read()
    resultados = await procesar_pdf_zipgrade(contenido)
    return {"resultados": resultados, "total": len(resultados)}

@app.post("/quizzes/confirmar-resultado")
def confirmar_resultado(data: dict, db: Session = Depends(get_db)):
    nuevo = Resultado(id=uuid.uuid4(), **data)
    db.add(nuevo)
    db.commit()
    return nuevo

@app.get("/resultados/historial/{estudiante_id}")
def historial_estudiante(estudiante_id: str, db: Session = Depends(get_db)):
    return db.query(Resultado).filter(Resultado.estudiante_id == estudiante_id).all()

@app.get("/resultados/{resultado_id}")
def get_resultado(resultado_id: str, db: Session = Depends(get_db)):
    r = db.query(Resultado).filter(Resultado.id == resultado_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Resultado no encontrado")
    return r

@app.get("/resultados/{resultado_id}/url-pdf")
def get_url_pdf(resultado_id: str, db: Session = Depends(get_db)):
    r = db.query(Resultado).filter(Resultado.id == resultado_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Resultado no encontrado")
    return {"url": generar_url_temporal(r.pdf_key) if r.pdf_key else None}

@app.post("/admin/activar-profe/{telegram_id}")
def admin_activar_profe(telegram_id: int, db: Session = Depends(get_db)):
    activar_profe(telegram_id, db)
    return {"ok": True}

@app.post("/admin/desactivar-profe/{telegram_id}")
def admin_desactivar_profe(telegram_id: int, db: Session = Depends(get_db)):
    desactivar_profe(telegram_id, db)
    return {"ok": True}

@app.post("/admin/activar-estudiante/{telegram_id}")
def admin_activar_estudiante(telegram_id: int, db: Session = Depends(get_db)):
    activar_estudiante(telegram_id, db)
    return {"ok": True}

@app.post("/admin/desactivar-estudiante/{telegram_id}")
def admin_desactivar_estudiante(telegram_id: int, db: Session = Depends(get_db)):
    desactivar_estudiante(telegram_id, db)
    return {"ok": True}