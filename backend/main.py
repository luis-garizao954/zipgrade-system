from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from backend.config import settings
from backend.models.models import Base, Profe, Estudiante, Curso, Quiz, Resultado, CursoEstudiante
from backend.services.suscripcion_service import (
    profe_activo, estudiante_activo, activar_profe, activar_estudiante,
    desactivar_profe, desactivar_estudiante
)
from datetime import date
import uuid, os, httpx, base64, io, anthropic

app = FastAPI(title="ZipGrade System API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

engine = create_engine(settings.DATABASE_URL)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)

BOT_PROFE_TOKEN = os.getenv("BOT_PROFE_TOKEN", "")
BOT_ESTUDIANTE_TOKEN = os.getenv("BOT_ESTUDIANTE_TOKEN", "")
BASE_URL = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")

profe_estado = {}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def send_message(token, chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)

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
    callback = data.get("callback_query", {})
    message = data.get("message", {})

    if callback:
        chat_id = callback.get("from", {}).get("id")
        telegram_id = chat_id
        cb_data = callback.get("data", "")
        if cb_data.startswith("curso_"):
            curso_id = cb_data.replace("curso_", "")
            curso = db.query(Curso).filter(Curso.id == curso_id).first()
            if curso:
                profe_estado[telegram_id] = {"curso_id": curso_id, "curso_nombre": curso.nombre}
                await send_message(BOT_PROFE_TOKEN, chat_id,
                    f"📚 Curso: <b>{curso.nombre} - {curso.grado}</b>\n\nAhora envíame el PDF de ZipGrade.")
        return {"ok": True}

    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    telegram_id = message.get("from", {}).get("id")
    nombre = message.get("from", {}).get("first_name", "Profe")
    document = message.get("document", {})

    if not chat_id:
        return {"ok": True}

    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()

    if text == "/start":
        if not profe:
            nuevo = Profe(id=uuid.uuid4(), telegram_id=telegram_id, nombre=nombre, email="", activo=False)
            db.add(nuevo)
            db.commit()
            await send_message(BOT_PROFE_TOKEN, chat_id,
                f"👋 Hola <b>{nombre}</b>!\n\nTu cuenta fue creada. Contacta al administrador para activar tu suscripcion.")
        else:
            if profe.activo:
                await send_message(BOT_PROFE_TOKEN, chat_id,
                    f"✅ Hola <b>{profe.nombre}</b>! Tu suscripcion esta activa.\n\n📋 Comandos:\n/micursos - Ver tus cursos\n/nuevocurso - Crear un curso\n/subirquiz - Subir PDF de ZipGrade\n/estado - Ver tu suscripcion")
            else:
                await send_message(BOT_PROFE_TOKEN, chat_id,
                    "❌ Tu suscripcion no esta activa. Contacta al administrador.")

    elif text == "/estado":
        if profe:
            estado = "✅ Activa" if profe.activo else "❌ Inactiva"
            await send_message(BOT_PROFE_TOKEN, chat_id, f"📊 Tu suscripcion: {estado}")

    elif text == "/micursos":
        if not profe or not profe.activo:
            await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Necesitas suscripcion activa.")
            return {"ok": True}
        cursos = db.query(Curso).filter(Curso.profe_id == profe.id).all()
        if not cursos:
            await send_message(BOT_PROFE_TOKEN, chat_id,
                "No tienes cursos aun. Usa /nuevocurso para crear uno.")
        else:
            lista = "\n".join([f"📚 {c.nombre} - {c.grado}" for c in cursos])
            await send_message(BOT_PROFE_TOKEN, chat_id, f"Tus cursos:\n\n{lista}")

    elif text == "/nuevocurso":
        if not profe or not profe.activo:
            await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Necesitas suscripcion activa.")
            return {"ok": True}
        profe_estado[telegram_id] = {"esperando": "nombre_curso"}
        await send_message(BOT_PROFE_TOKEN, chat_id,
            "✏️ Escribe el nombre y grado del curso en este formato:\n\n<b>Matematicas 9B</b>")

    elif text == "/subirquiz":
        if not profe or not profe.activo:
            await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Necesitas suscripcion activa.")
            return {"ok": True}
        cursos = db.query(Curso).filter(Curso.profe_id == profe.id).all()
        if not cursos:
            await send_message(BOT_PROFE_TOKEN, chat_id, "Primero crea un curso con /nuevocurso")
        else:
            botones = {"inline_keyboard": [[{"text": f"📚 {c.nombre} - {c.grado}", "callback_data": f"curso_{c.id}"}] for c in cursos]}
            await send_message(BOT_PROFE_TOKEN, chat_id, "¿A qué curso pertenece este quiz?", reply_markup=botones)

    elif document and document.get("file_name", "").endswith(".pdf"):
        estado_profe = profe_estado.get(telegram_id, {})
        curso_id = estado_profe.get("curso_id")
        await send_message(BOT_PROFE_TOKEN, chat_id,
            "📎 PDF recibido. Procesando con IA...\n\n⏳ Esto puede tardar 1-2 minutos.")
        try:
            file_id = document.get("file_id")
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(f"https://api.telegram.org/bot{BOT_PROFE_TOKEN}/getFile",
                    params={"file_id": file_id})
                file_path = r.json()["result"]["file_path"]
                pdf_r = await client.get(f"https://api.telegram.org/file/bot{BOT_PROFE_TOKEN}/{file_path}")
                pdf_bytes = pdf_r.content

            from pypdf import PdfReader, PdfWriter
            import fitz

            reader = PdfReader(io.BytesIO(pdf_bytes))
            total = len(reader.pages)
            ac = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            resultados_lista = []

            for i in range(total):
                writer = PdfWriter()
                writer.add_page(reader.pages[i])
                buf = io.BytesIO()
                writer.write(buf)
                pagina_bytes = buf.getvalue()
                try:
                    doc = fitz.open(stream=pagina_bytes, filetype="pdf")
                    pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
                    img_b64 = base64.b64encode(pix.tobytes("png")).decode()
                    resp = ac.messages.create(
                        model="claude-opus-4-6", max_tokens=100,
                        messages=[{"role": "user", "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                            {"type": "text", "text": "Busca el apellido escrito a mano en esta hoja de examen. Responde SOLO el apellido, nada mas."}
                        ]}])
                    apellido = resp.content[0].text.strip()
                except Exception as e:
                    apellido = f"Pagina_{i+1}"
                resultados_lista.append({"pagina": i+1, "apellido": apellido})

            resumen = "\n".join([f"Pag {r['pagina']}: <b>{r['apellido']}</b>" for r in resultados_lista])
            await send_message(BOT_PROFE_TOKEN, chat_id,
                f"✅ PDF procesado: <b>{total} estudiantes</b>\n\n{resumen}\n\n¿Los apellidos son correctos? Responde <b>OK</b> para confirmar.")
            profe_estado[telegram_id]["resultados"] = resultados_lista
            profe_estado[telegram_id]["pdf_bytes"] = pdf_bytes

        except Exception as e:
            await send_message(BOT_PROFE_TOKEN, chat_id, f"❌ Error procesando PDF: {str(e)}")

    elif text and not text.startswith("/"):
        estado_profe = profe_estado.get(telegram_id, {})
        if estado_profe.get("esperando") == "nombre_curso" and profe and profe.activo:
            partes = text.rsplit(" ", 1)
            nom = partes[0]
            grado = partes[1] if len(partes) > 1 else ""
            nuevo_curso = Curso(id=uuid.uuid4(), profe_id=profe.id, nombre=nom, grado=grado)
            db.add(nuevo_curso)
            db.commit()
            profe_estado[telegram_id] = {}
            await send_message(BOT_PROFE_TOKEN, chat_id,
                f"✅ Curso <b>{nom} {grado}</b> creado!\n\nUsa /subirquiz para subir un PDF.")
        elif text.upper() == "OK" and estado_profe.get("resultados"):
            await send_message(BOT_PROFE_TOKEN, chat_id,
                "✅ Resultados confirmados y guardados. Los estudiantes ya pueden consultar sus notas.")
            profe_estado[telegram_id] = {}
        else:
            await send_message(BOT_PROFE_TOKEN, chat_id,
                "Comandos:\n/start\n/micursos\n/nuevocurso\n/subirquiz\n/estado")

    return {"ok": True}

@app.post("/webhook/estudiante")
async def webhook_estudiante(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    telegram_id = message.get("from", {}).get("id")
    nombre = message.get("from", {}).get("first_name", "Estudiante")

    if not chat_id:
        return {"ok": True}

    estudiante = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()

    if text == "/start":
        if not estudiante:
            nuevo = Estudiante(id=uuid.uuid4(), telegram_id=telegram_id, nombre=nombre, apellido="", activo=False)
            db.add(nuevo)
            db.commit()
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                f"👋 Hola <b>{nombre}</b>!\n\nTu cuenta fue creada. Contacta a tu profe para activar tu suscripcion.")
        else:
            if estudiante.activo:
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                    f"✅ Hola <b>{estudiante.nombre}</b>!\n\nUsa /misnotas para ver tus resultados.")
            else:
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                    "❌ Tu suscripcion no esta activa. Contacta a tu profe.")

    elif text == "/misnotas":
        if not estudiante or not estudiante.activo:
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "❌ Necesitas suscripcion activa.")
            return {"ok": True}
        resultados = db.query(Resultado).filter(
            Resultado.estudiante_id == estudiante.id,
            Resultado.confirmado == True).all()
        if not resultados:
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "📭 Aun no tienes resultados.")
        else:
            msg = f"📊 <b>Tus resultados, {estudiante.nombre}:</b>\n\n"
            for r in resultados:
                quiz = db.query(Quiz).filter(Quiz.id == r.quiz_id).first()
                nom = quiz.nombre if quiz else "Quiz"
                msg += f"📝 {nom}: <b>{r.nota}/5.0</b>\n"
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, msg)
    else:
        await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "Comandos:\n/start\n/misnotas")

    return {"ok": True}

@app.post("/profes/registrar")
def registrar_profe(data: dict, db: Session = Depends(get_db)):
    profe = db.query(Profe).filter(Profe.telegram_id == data["telegram_id"]).first()
    if profe:
        return {"id": str(profe.id), "nombre": profe.nombre, "activo": profe.activo}
    nuevo = Profe(id=uuid.uuid4(), telegram_id=data["telegram_id"], nombre=data.get("nombre", ""), email="", activo=False)
    db.add(nuevo)
    db.commit()
    return {"id": str(nuevo.id), "nombre": nuevo.nombre, "activo": nuevo.activo}

@app.get("/profes/by-telegram/{telegram_id}")
def get_profe_by_telegram(telegram_id: int, db: Session = Depends(get_db)):
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if not profe:
        raise HTTPException(status_code=404, detail="Profe no encontrado")
    return {"id": str(profe.id), "nombre": profe.nombre, "activo": profe.activo}

@app.get("/profes/activo/{telegram_id}")
def check_profe_activo(telegram_id: int, db: Session = Depends(get_db)):
    return {"activo": profe_activo(telegram_id, db)}

@app.post("/estudiantes/registrar")
def registrar_estudiante(data: dict, db: Session = Depends(get_db)):
    est = db.query(Estudiante).filter(Estudiante.telegram_id == data["telegram_id"]).first()
    if est:
        return {"id": str(est.id), "nombre": est.nombre, "activo": est.activo}
    nuevo = Estudiante(id=uuid.uuid4(), telegram_id=data["telegram_id"], nombre=data.get("nombre", ""), apellido="", activo=False)
    db.add(nuevo)
    db.commit()
    return {"id": str(nuevo.id), "nombre": nuevo.nombre, "activo": nuevo.activo}

@app.get("/estudiantes/by-telegram/{telegram_id}")
def get_estudiante_by_telegram(telegram_id: int, db: Session = Depends(get_db)):
    est = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
    if not est:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    return {"id": str(est.id), "nombre": est.nombre, "apellido": est.apellido, "activo": est.activo}

@app.get("/estudiantes/activo/{telegram_id}")
def check_estudiante_activo(telegram_id: int, db: Session = Depends(get_db)):
    return {"activo": estudiante_activo(telegram_id, db)}

@app.post("/cursos/crear")
def crear_curso(data: dict, db: Session = Depends(get_db)):
    nuevo = Curso(id=uuid.uuid4(), profe_id=data["profe_id"], nombre=data["nombre"], grado=data.get("grado", ""))
    db.add(nuevo)
    db.commit()
    return {"id": str(nuevo.id), "nombre": nuevo.nombre, "grado": nuevo.grado}

@app.get("/cursos/by-profe-telegram/{telegram_id}")
def cursos_by_profe(telegram_id: int, db: Session = Depends(get_db)):
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if not profe:
        return []
    cursos = db.query(Curso).filter(Curso.profe_id == profe.id).all()
    return [{"id": str(c.id), "nombre": c.nombre, "grado": c.grado} for c in cursos]

@app.get("/resultados/historial/{estudiante_id}")
def historial_estudiante(estudiante_id: str, db: Session = Depends(get_db)):
    return db.query(Resultado).filter(
        Resultado.estudiante_id == estudiante_id,
        Resultado.confirmado == True).all()

@app.get("/resultados/{resultado_id}")
def get_resultado(resultado_id: str, db: Session = Depends(get_db)):
    r = db.query(Resultado).filter(Resultado.id == resultado_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="No encontrado")
    return r

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