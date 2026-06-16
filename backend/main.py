
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from backend.config import settings
from backend.models.models import Base, Profe, Estudiante, Curso, Quiz, Resultado, CursoEstudiante, MensajeGrupo
from backend.services.suscripcion_service import (
    profe_activo, estudiante_activo, activar_profe, activar_estudiante,
    desactivar_profe, desactivar_estudiante
)
from backend.services.pdf_service import procesar_pdf_zipgrade
import uuid, os, httpx

app = FastAPI(title="ZipGrade System API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

engine = create_engine(settings.DATABASE_URL)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)

BOT_PROFE_TOKEN = os.getenv("BOT_PROFE_TOKEN", "")
BOT_ESTUDIANTE_TOKEN = os.getenv("BOT_ESTUDIANTE_TOKEN", "")
BASE_URL = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")

profe_estado = {}
estudiante_grupo_estado = {}
profe_grupo_estado = {}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def send_message(token, chat_id, text, reply_markup=None):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup: payload["reply_markup"] = reply_markup
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=10)
    except Exception:
        pass

async def cargar_historial_grupo(db: Session, token: str, chat_id: int, curso_id: str):
    try:
        # Conversión segura a UUID para la consulta
        c_uuid = uuid.UUID(curso_id)
        mensajes = db.query(MensajeGrupo).filter(MensajeGrupo.curso_id == c_uuid).order_by(MensajeGrupo.fecha_envio.asc()).all()
        if not mensajes:
            await send_message(token, chat_id, "📭 <i>Este grupo no tiene mensajes compartidos todavía.</i>")
            return
            
        await send_message(token, chat_id, f"📜 <b>Cargando historial ({len(mensajes)} mensajes)...</b>")
        for msg in mensajes:
            data_multimedia = {"text": msg.texto, "file_id": msg.file_id, "caption": msg.caption}
            es_docente = "[PROFE]" in msg.remitente_nombre
            nombre_limpio = msg.remitente_nombre.replace("👨‍🏫 [PROFE] ", "").replace("👥 [GRUPO] ", "")
            await enviar_multimedia_generico(token, chat_id, nombre_limpio, data_multimedia, msg.tipo_mensaje, es_profe=es_docente)
    except Exception:
        pass

async def alertar_conexion_profe(db: Session, curso_id: str, nombre_prof: str, curso_nombre: str, curso_grado: str):
    try:
        c_uuid = uuid.UUID(curso_id)
        inscripciones = db.query(CursoEstudiante).filter(CursoEstudiante.curso_id == c_uuid).all()
        texto_alerta = (
            f"👨‍🏫 <b>Notificación Escolar:</b>\n\n"
            f"El profesor <b>{nombre_prof}</b> se conectó al grupo de <b>{curso_nombre} {curso_grado}</b>.\n\n"
            f"💡 Usa /grupos para ingresar a la asignatura."
        )
        for ins in inscripciones:
            est = db.query(Estudiante).filter(Estudiante.id == ins.estudiante_id).first()
            if est and est.activo:
                await send_message(BOT_ESTUDIANTE_TOKEN, est.telegram_id, texto_alerta)
    except Exception:
        pass

async def registrar_y_transmitir_en_grupo(db: Session, curso_id: str, remitente_telegram_id: int, remitente_nombre: str, data: dict, tipo_mensaje: str, es_profe: bool):
    try:
        c_uuid = uuid.UUID(curso_id)
        etiqueta = f"👨‍🏫 [PROFE] {remitente_nombre}" if es_profe else f"👥 [GRUPO] {remitente_nombre}"
        nuevo_msg = MensajeGrupo(
            id=uuid.uuid4(),
            curso_id=c_uuid,
            remitente_nombre=etiqueta,
            tipo_mensaje=tipo_mensaje,
            texto=data.get("text"),
            file_id=data.get("file_id"),
            caption=data.get("caption")
        )
        db.add(nuevo_msg)
        db.commit()

        for est_tg_id, estado in estudiante_grupo_estado.items():
            if estado.get("curso_id") == str(curso_id) and est_tg_id != remitente_telegram_id:
                await enviar_multimedia_generico(BOT_ESTUDIANTE_TOKEN, est_tg_id, remitente_nombre, data, tipo_mensaje, es_profe)
                
        for prof_tg_id, estado in profe_grupo_estado.items():
            if estado.get("curso_id") == str(curso_id) and prof_tg_id != remitente_telegram_id:
                await enviar_multimedia_generico(BOT_PROFE_TOKEN, prof_tg_id, remitente_nombre, data, tipo_mensaje, es_profe)
    except Exception:
        pass

async def enviar_multimedia_generico(token: str, chat_id: int, remitente_nombre: str, data: dict, tipo_mensaje: str, es_profe: bool):
    try:
        prefix = f"👨‍🏫 <b>[PROFE] {remitente_nombre}:</b>" if es_profe else f"👥 <b>[GRUPO] {remitente_nombre}:</b>"
        async with httpx.AsyncClient() as client:
            if tipo_mensaje == "text":
                texto_final = f"{prefix}\n{data['text']}"
                await client.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                                  json={"chat_id": chat_id, "text": texto_final, "parse_mode": "HTML"}, timeout=10)
            elif tipo_mensaje == "document":
                caption = f"{prefix} compartió un archivo"
                if data.get("caption"): caption += f"\n{data['caption']}"
                await client.post(f"https://api.telegram.org/bot{token}/sendDocument", 
                                  json={"chat_id": chat_id, "document": data["file_id"], "caption": caption, "parse_mode": "HTML"}, timeout=10)
            elif tipo_mensaje == "photo":
                caption = f"{prefix} envió una imagen"
                if data.get("caption"): caption += f"\n{data['caption']}"
                await client.post(f"https://api.telegram.org/bot{token}/sendPhoto", 
                                  json={"chat_id": chat_id, "photo": data["file_id"], "caption": caption, "parse_mode": "HTML"}, timeout=10)
            elif tipo_mensaje == "voice":
                await client.post(f"https://api.telegram.org/bot{token}/sendVoice", 
                                  json={"chat_id": chat_id, "voice": data["file_id"], "caption": prefix, "parse_mode": "HTML"}, timeout=10)
            elif tipo_mensaje == "video":
                caption = f"{prefix} envió un video"
                if data.get("caption"): caption += f"\n{data['caption']}"
                await client.post(f"https://api.telegram.org/bot{token}/sendVideo", 
                                  json={"chat_id": chat_id, "video": data["file_id"], "caption": caption, "parse_mode": "HTML"}, timeout=10)
    except Exception:
        pass

@app.on_event("startup")
async def set_webhooks():
    if BOT_PROFE_TOKEN and BASE_URL:
        async with httpx.AsyncClient() as client:
            await client.get(f"https://api.telegram.org/bot{BOT_PROFE_TOKEN}/setWebhook", params={"url": f"https://{BASE_URL}/webhook/profe"})
            await client.get(f"https://api.telegram.org/bot{BOT_ESTUDIANTE_TOKEN}/setWebhook", params={"url": f"https://{BASE_URL}/webhook/estudiante"})

@app.post("/webhook/profe")
async def webhook_profe(request: Request, db: Session = Depends(get_db)):
    try: data = await request.json()
    except Exception: return {"ok": True}

    callback = data.get("callback_query", {})
    if callback:
        chat_id = callback.get("from", {}).get("id")
        telegram_id = chat_id
        nombre_prof = callback.get("from", {}).get("first_name", "Profe")
        cb_data = callback.get("data", "")
        
        if cb_data.startswith("profe_grupo_"):
            curso_id = cb_data.replace("profe_grupo_", "")
            c_uuid = uuid.UUID(curso_id)
            curso = db.query(Curso).filter(Curso.id == c_uuid).first()
            if curso:
                profe_grupo_estado[telegram_id] = {"curso_id": str(curso_id), "curso_nombre": curso.nombre, "curso_grado": curso.grado}
                await send_message(BOT_PROFE_TOKEN, chat_id, f"📥 <b>Inmerso en: {curso.nombre} {curso.grado}</b>\n\n🚪 Para salir usa: /salir")
                await cargar_historial_grupo(db, BOT_PROFE_TOKEN, chat_id, str(curso_id))
                await alertar_conexion_profe(db, str(curso_id), nombre_prof, curso.nombre, curso.grado)
            return {"ok": True}
            
        elif cb_data.startswith("curso_"):
            curso_id = cb_data.replace("curso_", "")
            c_uuid = uuid.UUID(curso_id)
            curso = db.query(Curso).filter(Curso.id == c_uuid).first()
            if curso:
                profe_estado[telegram_id] = {"curso_id": str(curso_id), "curso_nombre": curso.nombre}
                await send_message(BOT_PROFE_TOKEN, chat_id, f"📚 Curso seleccionado. Envía el PDF.")
            return {"ok": True}

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    telegram_id = message.get("from", {}).get("id")
    nombre = message.get("from", {}).get("first_name", "Profe")
    
    if not chat_id: return {"ok": True}
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()

    if text == "/start":
        if profe and profe.activo:
            await send_message(BOT_PROFE_TOKEN, chat_id, "✅ Panel del Profesor Activo.\n\n/micursos - Ver cursos\n/nuevocurso - Crear curso\n/subirquiz - Evaluar con ZipGrade\n/grupos - Entrar a un Aula Virtual\n/salir - Salir del aula")
        return {"ok": True}

    if text == "/salir":
        if telegram_id in profe_grupo_estado:
            del profe_grupo_estado[telegram_id]
            await send_message(BOT_PROFE_TOKEN, chat_id, "🚪 Saliste del grupo. Volviste al menú principal.")
        return {"ok": True}

    if text == "/grupos":
        if not profe or not profe.activo: return {"ok": True}
        cursos = db.query(Curso).filter(Curso.profe_id == profe.id).all()
        if cursos:
            botones = [[{"text": f"👥 Aula de {c.nombre} {c.grado}", "callback_data": f"profe_grupo_{c.id}"}] for c in cursos]
            await send_message(BOT_PROFE_TOKEN, chat_id, "🗂️ Selecciona el Aula Virtual:", reply_markup={"inline_keyboard": botones})
        return {"ok": True}

    if telegram_id in profe_grupo_estado:
        c_id = profe_grupo_estado[telegram_id]["curso_id"]
        if text: await registrar_y_transmitir_en_grupo(db, c_id, telegram_id, nombre, {"text": text}, "text", es_profe=True)
        elif message.get("document"): await registrar_y_transmitir_en_grupo(db, c_id, telegram_id, nombre, {"file_id": message["document"]["file_id"], "caption": message.get("caption", "")}, "document", es_profe=True)
        elif message.get("photo"): await registrar_y_transmitir_en_grupo(db, c_id, telegram_id, nombre, {"file_id": message["photo"][-1]["file_id"], "caption": message.get("caption", "")}, "photo", es_profe=True)
        elif message.get("voice"): await registrar_y_transmitir_en_grupo(db, c_id, telegram_id, nombre, {"file_id": message["voice"]["file_id"]}, "voice", es_profe=True)
        elif message.get("video"): await registrar_y_transmitir_en_grupo(db, c_id, telegram_id, nombre, {"file_id": message["video"]["file_id"], "caption": message.get("caption", "")}, "video", es_profe=True)
        return {"ok": True}

    return {"ok": True}

@app.post("/webhook/estudiante")
async def webhook_estudiante(request: Request, db: Session = Depends(get_db)):
    try: data = await request.json()
    except Exception: return {"ok": True}

    callback = data.get("callback_query", {})
    if callback:
        chat_id = callback.get("from", {}).get("id")
        telegram_id = chat_id
        cb_data = callback.get("data", "")
        
        if cb_data.startswith("entrar_grupo_"):
            curso_id = cb_data.replace("entrar_grupo_", "")
            c_uuid = uuid.UUID(curso_id)
            curso = db.query(Curso).filter(Curso.id == c_uuid).first()
            if curso:
                estudiante_grupo_estado[telegram_id] = {"curso_id": str(curso_id), "curso_nombre": curso.nombre, "curso_grado": curso.grado}
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, f"📥 Conectado al aula: {curso.nombre}. Escribe /salir para terminar.")
                await cargar_historial_grupo(db, BOT_ESTUDIANTE_TOKEN, chat_id, str(curso_id))
        return {"ok": True}

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    telegram_id = message.get("from", {}).get("id")
    nombre = message.get("from", {}).get("first_name", "Estudiante")
    
    if not chat_id: return {"ok": True}
    estudiante = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()

    if text == "/start":
        if estudiante and estudiante.activo:
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "👋 Hola de nuevo. Comandos:\n/misnotas - Ver notas\n/grupos - Entrar a una clase\n/salir - Salir del grupo")
        return {"ok": True}

    if text == "/salir":
        if telegram_id in estudiante_grupo_estado:
            del estudiante_grupo_estado[telegram_id]
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "🚪 Saliste del grupo de manera segura.")
        return {"ok": True}

    if text == "/grupos":
        if estudiante and estudiante.activo:
            # CORRECCIÓN AQUÍ: Conversión explícita a UUID del ID del estudiante
            e_uuid = uuid.UUID(str(estudiante.id))
            inscripciones = db.query(CursoEstudiante).filter(CursoEstudiante.estudiante_id == e_uuid).all()
            if inscripciones:
                botones = []
                for ins in inscripciones:
                    c = db.query(Curso).filter(Curso.id == ins.curso_id).first()
                    if c: botones.append([{"text": f"📖 Entrar a {c.nombre}", "callback_data": f"entrar_grupo_{c.id}"}])
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "🔍 Selecciona la asignatura:", reply_markup={"inline_keyboard": botones})
            else:
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "No estás inscrito en ningún curso.")
        return {"ok": True}

    if telegram_id in estudiante_grupo_estado:
        c_id = estudiante_grupo_estado[telegram_id]["curso_id"]
        if text: await registrar_y_transmitir_en_grupo(db, c_id, telegram_id, nombre, {"text": text}, "text", es_profe=False)
        elif message.get("document"): await registrar_y_transmitir_en_grupo(db, c_id, telegram_id, nombre, {"file_id": message["document"]["file_id"], "caption": message.get("caption", "")}, "document", es_profe=False)
        elif message.get("photo"): await registrar_y_transmitir_en_grupo(db, c_id, telegram_id, nombre, {"file_id": message["photo"][-1]["file_id"], "caption": message.get("caption", "")}, "photo", es_profe=False)
        elif message.get("voice"): await registrar_y_transmitir_en_grupo(db, c_id, telegram_id, nombre, {"file_id": message["voice"]["file_id"]}, "voice", es_profe=False)
        elif message.get("video"): await registrar_y_transmitir_en_grupo(db, c_id, telegram_id, nombre, {"file_id": message["video"]["file_id"], "caption": message.get("caption", "")}, "video", es_profe=False)
        return {"ok": True}

    return {"ok": True}

# --- ENPOINTS DE CONTROL COMPATIBLES CON UUID ---
@app.post("/profes/registrar")
def registrar_profe(data: dict, db: Session = Depends(get_db)):
    p = db.query(Profe).filter(Profe.telegram_id == data["telegram_id"]).first()
    if p: return {"id": str(p.id), "nombre": p.nombre, "activo": p.activo}
    nuevo = Profe(id=uuid.uuid4(), telegram_id=data["telegram_id"], nombre=data.get("nombre", ""), email="", activo=False)
    db.add(nuevo)
    db.commit()
    return {"id": str(nuevo.id), "nombre": nuevo.nombre, "activo": nuevo.activo}

@app.get("/profes/by-telegram/{telegram_id}")
def get_profe_by_telegram(telegram_id: int, db: Session = Depends(get_db)):
    p = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if not p: raise HTTPException(status_code=404, detail="No encontrado")
    return {"id": str(p.id), "nombre": p.nombre, "activo": p.activo}

@app.get("/profes/activo/{telegram_id}")
def check_profe_activo(telegram_id: int, db: Session = Depends(get_db)):
    return {"activo": profe_activo(telegram_id, db)}

@app.post("/estudiantes/registrar")
def registrar_estudiante(data: dict, db: Session = Depends(get_db)):
    e = db.query(Estudiante).filter(Estudiante.telegram_id == data["telegram_id"]).first()
    if e: return {"id": str(e.id), "nombre": e.nombre, "activo": e.activo}
    nuevo = Estudiante(id=uuid.uuid4(), telegram_id=data["telegram_id"], nombre=data.get("nombre", ""), apellido="", activo=False)
    db.add(nuevo)
    db.commit()
    return {"id": str(nuevo.id), "nombre": nuevo.nombre, "activo": nuevo.activo}

@app.get("/estudiantes/by-telegram/{telegram_id}")
def get_estudiante_by_telegram(telegram_id: int, db: Session = Depends(get_db)):
    e = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
    if not e: raise HTTPException(status_code=404, detail="No encontrado")
    return {"id": str(e.id), "nombre": e.nombre, "apellido": e.apellido, "activo": e.activo}

@app.get("/estudiantes/activo/{telegram_id}")
def check_estudiante_activo(telegram_id: int, db: Session = Depends(get_db)):
    return {"activo": estudiante_activo(telegram_id, db)}

@app.post("/cursos/crear")
def crear_curso(data: dict, db: Session = Depends(get_db)):
    p_uuid = uuid.UUID(data["profe_id"])
    nuevo = Curso(id=uuid.uuid4(), profe_id=p_uuid, nombre=data["nombre"], grado=data.get("grado", ""))
    db.add(nuevo)
    db.commit()
    return {"id": str(nuevo.id), "nombre": nuevo.nombre, "grado": nuevo.grado}

@app.get("/cursos/by-profe-telegram/{telegram_id}")
def courses_by_profe(telegram_id: int, db: Session = Depends(get_db)):
    p = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if not p: return []
    return [{"id": str(c.id), "nombre": c.nombre, "grado": c.grado} for c in db.query(Curso).filter(Curso.profe_id == p.id).all()]

@app.get("/resultados/historial/{estudiante_id}")
def historial_estudiante(estudiante_id: str, db: Session = Depends(get_db)):
    e_uuid = uuid.UUID(estudiante_id)
    return db.query(Resultado).filter(Resultado.estudiante_id == e_uuid, Resultado.confirmado == True).all()

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