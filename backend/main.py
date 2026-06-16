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
from backend.services.pdf_service import procesar_pdf_zipgrade
import uuid, os, httpx, io

app = FastAPI(title="ZipGrade System API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

engine = create_engine(settings.DATABASE_URL)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)

BOT_PROFE_TOKEN = os.getenv("BOT_PROFE_TOKEN", "")
BOT_ESTUDIANTE_TOKEN = os.getenv("BOT_ESTUDIANTE_TOKEN", "")
BASE_URL = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")

# Diccionarios en memoria para los flujos tradicionales de los profes
profe_estado = {}

# Control de estados inmersivos en grupos para Profes y Estudiantes
# Estructura: {telegram_id: {"curso_id": "...", "curso_nombre": "..."}}
estudiante_grupo_estado = {}
profe_grupo_estado = {}

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

async def transmitir_a_estudiantes_del_curso(db: Session, curso_id: str, remitente_nombre: str, data: dict, tipo_mensaje: str):
    """Envía el contenido multimedia enviado por el profesor a TODOS los estudiantes del curso"""
    inscripciones = db.query(CursoEstudiante).filter(CursoEstudiante.curso_id == curso_id).all()
    for ins in inscripciones:
        est = db.query(Estudiante).filter(Estudiante.id == ins.estudiante_id).first()
        if est and est.activo:
            await enviar_multimedia_generico(BOT_ESTUDIANTE_TOKEN, est.telegram_id, remitente_nombre, data, tipo_mensaje, es_profe=True)

async def transmitir_a_estudiantes_y_profe(db: Session, curso_id: str, remitente_telegram_id: int, remitente_nombre: str, data: dict, tipo_mensaje: str):
    """Transmite el contenido de un estudiante a sus compañeros y también al profesor dueño del curso"""
    curso = db.query(Curso).filter(Curso.id == curso_id).first()
    
    # 1. Enviar a los compañeros del curso
    inscripciones = db.query(CursoEstudiante).filter(CursoEstudiante.curso_id == curso_id).all()
    for ins in inscripciones:
        est = db.query(Estudiante).filter(Estudiante.id == ins.estudiante_id).first()
        if est and est.telegram_id != remitente_telegram_id and est.activo:
            await enviar_multimedia_generico(BOT_ESTUDIANTE_TOKEN, est.telegram_id, remitente_nombre, data, tipo_mensaje, es_profe=False)
            
    # 2. Enviar al profesor del curso
    if curso:
        profe = db.query(Profe).filter(Profe.id == curso.profe_id).first()
        if profe:
            await enviar_multimedia_generico(BOT_PROFE_TOKEN, profe.telegram_id, remitente_nombre, data, tipo_mensaje, es_profe=False)

async def enviar_multimedia_generico(token: str, chat_id: int, remitente_nombre: str, data: dict, tipo_mensaje: str, es_profe: bool):
    """Función auxiliar para procesar textos, links, audios, videos y archivos hacia Telegram"""
    prefix = f"👨‍🏫 <b>[PROFE] {remitente_nombre}:</b>" if es_profe else f"👥 <b>[GRUPO] {remitente_nombre}:</b>"
    
    async with httpx.AsyncClient() as client:
        if tipo_mensaje == "text":
            texto_final = f"{prefix}\n{data['text']}"
            await client.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                              json={"chat_id": chat_id, "text": texto_final, "parse_mode": "HTML", "disable_web_page_preview": False})
        
        elif tipo_mensaje == "document":
            caption = f"{prefix} compartió un archivo"
            if data.get("caption"): caption += f"\n{data['caption']}"
            await client.post(f"https://api.telegram.org/bot{token}/sendDocument", 
                              json={"chat_id": chat_id, "document": data["file_id"], "caption": caption, "parse_mode": "HTML"})
            
        elif tipo_mensaje == "photo":
            caption = f"{prefix} envió una imagen"
            if data.get("caption"): caption += f"\n{data['caption']}"
            await client.post(f"https://api.telegram.org/bot{token}/sendPhoto", 
                              json={"chat_id": chat_id, "photo": data["file_id"], "caption": caption, "parse_mode": "HTML"})
            
        elif tipo_mensaje == "voice":
            caption = f"{prefix} envió una nota de voz"
            await client.post(f"https://api.telegram.org/bot{token}/sendVoice", 
                              json={"chat_id": chat_id, "voice": data["file_id"], "caption": caption, "parse_mode": "HTML"})
            
        elif tipo_mensaje == "video":
            caption = f"{prefix} envió un video"
            if data.get("caption"): caption += f"\n{data['caption']}"
            await client.post(f"https://api.telegram.org/bot{token}/sendVideo", 
                              json={"chat_id": chat_id, "video": data["file_id"], "caption": caption, "parse_mode": "HTML"})

@app.on_event("startup")
async def set_webhooks():
    if BOT_PROFE_TOKEN and BASE_URL:
        async with httpx.AsyncClient() as client:
            await client.get(f"https://api.telegram.org/bot{BOT_PROFE_TOKEN}/setWebhook", params={"url": f"https://{BASE_URL}/webhook/profe"})
            await client.get(f"https://api.telegram.org/bot{BOT_ESTUDIANTE_TOKEN}/setWebhook", params={"url": f"https://{BASE_URL}/webhook/estudiante"})

@app.post("/webhook/profe")
async def webhook_profe(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    
    # --- CALLBACKS DEL PROFE (Botones de Cursos/Grupos) ---
    callback = data.get("callback_query", {})
    if callback:
        chat_id = callback.get("from", {}).get("id")
        telegram_id = chat_id
        nombre_prof = callback.get("from", {}).get("first_name", "Profe")
        cb_data = callback.get("data", "")
        
        if cb_data.startswith("profe_grupo_"):
            curso_id = cb_data.replace("profe_grupo_", "")
            curso = db.query(Curso).filter(Curso.id == curso_id).first()
            if curso:
                # El profesor se sumerge en el grupo de manera activa
                profe_grupo_estado[telegram_id] = {"curso_id": curso_id, "curso_nombre": curso.nombre, "curso_grado": curso.grado}
                
                await send_message(BOT_PROFE_TOKEN, chat_id,
                    f"📥 <b>Inmerso en el grupo: {curso.nombre} {curso.grado}</b>\n\n"
                    f"📢 Todo lo que escribas, pegues o envíes aquí (links, notas de voz, imágenes, PDFs, Word, Excel o videos) "
                    f"les llegará de inmediato a todos los estudiantes de este salón.\n\n"
                    f"🚪 Para salir de esta asignatura y volver a tu panel de control, usa: /salir")
                
                # Avisar a los alumnos que el docente entró al chat
                await transmitir_a_estudiantes_del_curso(db, curso_id, nombre_prof, 
                    {"text": f"👨‍🏫 El profesor <b>{nombre_prof}</b> se ha conectado al canal del grupo."}, "text")
            return {"ok": True}
            
        elif cb_data.startswith("curso_"):
            # Flujo viejo de ZipGrade para procesar un PDF
            curso_id = cb_data.replace("curso_", "")
            curso = db.query(Curso).filter(Curso.id == curso_id).first()
            if curso:
                profe_estado[telegram_id] = {"curso_id": curso_id, "curso_nombre": curso.nombre}
                await send_message(BOT_PROFE_TOKEN, chat_id, f"📚 Curso: <b>{curso.nombre} - {curso.grado}</b>\n\nAhora envíame el PDF de ZipGrade.")
            return {"ok": True}

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    telegram_id = message.get("from", {}).get("id")
    nombre = message.get("from", {}).get("first_name", "Profe")
    
    if not chat_id:
        return {"ok": True}

    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()

    # --- COMANDOS PRIORITARIOS DEL DOCENTE ---
    if text == "/start":
        if not profe:
            nuevo = Profe(id=uuid.uuid4(), telegram_id=telegram_id, nombre=nombre, email="", activo=False)
            db.add(nuevo)
            db.commit()
            await send_message(BOT_PROFE_TOKEN, chat_id, f"👋 Hola <b>{nombre}</b>!\n\nTu cuenta fue creada. Contacta al administrador para activar tu suscripcion.")
        else:
            if profe.activo:
                await send_message(BOT_PROFE_TOKEN, chat_id, 
                    f"✅ Hola <b>{profe.nombre}</b>!\n\n📋 Comandos:\n/micursos - Ver tus cursos\n/nuevocurso - Crear un curso\n/subirquiz - Subir PDF de ZipGrade\n/grupos - Entrar a un Chat de Grupo\n/salir - Salir del grupo actual\n/estado - Ver tu suscripcion")
            else:
                await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Tu suscripcion no esta activa. Contacta al administrador.")
        return {"ok": True}

    elif text == "/salir":
        if telegram_id in profe_grupo_estado:
            info = profe_grupo_estado[telegram_id]
            # Notificar que el profe salió de la inmersión
            await transmitir_a_estudiantes_del_curso(db, info["curso_id"], nombre, 
                {"text": f"🚪 El profesor <b>{nombre}</b> se ha desconectado del grupo."}, "text")
            
            del profe_grupo_estado[telegram_id]
            await send_message(BOT_PROFE_TOKEN, chat_id, "🚪 Has salido del grupo. Volviste a tu chat administrativo normal.")
        else:
            await send_message(BOT_PROFE_TOKEN, chat_id, "No estás inmerso en ningún grupo en este momento.")
        return {"ok": True}

    elif text == "/grupos":
        if not profe or not profe.activo:
            await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Necesitas suscripcion activa.")
            return {"ok": True}
        cursos = db.query(Curso).filter(Curso.profe_id == profe.id).all()
        if not cursos:
            await send_message(BOT_PROFE_TOKEN, chat_id, "Aún no tienes asignaturas creadas. Usa /nuevocurso primero.")
        else:
            botones = [[{"text": f"👥 Ver {c.nombre} {c.grado}", "callback_data": f"profe_grupo_{c.id}"}] for c in cursos]
            await send_message(BOT_PROFE_TOKEN, chat_id, "🗂️ Selecciona en qué grupo deseas entrar de manera inmersiva:", reply_markup={"inline_keyboard": botones})
        return {"ok": True}

    # --- TRANSMISIÓN MULTIMEDIA DEL PROFE INMERSO EN UN GRUPO ---
    if telegram_id in profe_grupo_estado:
        c_id = profe_grupo_estado[telegram_id]["curso_id"]
        
        if text:
            await transmitir_a_estudiantes_del_curso(db, c_id, nombre, {"text": text}, "text")
        elif message.get("document"):
            await transmitir_a_estudiantes_del_curso(db, c_id, nombre, {"file_id": message["document"]["file_id"], "caption": message.get("caption", "")}, "document")
        elif message.get("photo"):
            await transmitir_a_estudiantes_del_curso(db, c_id, nombre, {"file_id": message["photo"][-1]["file_id"], "caption": message.get("caption", "")}, "photo")
        elif message.get("voice"):
            await transmitir_a_estudiantes_del_curso(db, c_id, nombre, {"file_id": message["voice"]["file_id"]}, "voice")
        elif message.get("video"):
            await transmitir_a_estudiantes_del_curso(db, c_id, nombre, {"file_id": message["video"]["file_id"], "caption": message.get("caption", "")}, "video")
        return {"ok": True}

    # --- FLUJO TRADICIONAL DE PROFESORES (ZIPGRADE / NUEVO CURSO) ---
    if text == "/estado":
        if profe: await send_message(BOT_PROFE_TOKEN, chat_id, f"📊 Tu suscripcion: {'✅ Activa' if profe.activo else '❌ Inactiva'}")
    elif text == "/micursos":
        if profe and profe.activo:
            cursos = db.query(Curso).filter(Curso.profe_id == profe.id).all()
            msg = "\n".join([f"📚 {c.nombre} - {c.grado}" for c in cursos]) if cursos else "No tienes cursos creados."
            await send_message(BOT_PROFE_TOKEN, chat_id, f"Tus cursos:\n\n{msg}")
    elif text == "/nuevocurso":
        if profe and profe.activo:
            profe_estado[telegram_id] = {"esperando": "nombre_curso"}
            await send_message(BOT_PROFE_TOKEN, chat_id, "✏️ Escribe el nombre y grado en este formato:\n\n<b>Matematicas 9B</b>")
    elif text == "/subirquiz":
        if profe and profe.activo:
            cursos = db.query(Curso).filter(Curso.profe_id == profe.id).all()
            if not cursos: await send_message(BOT_PROFE_TOKEN, chat_id, "Primero crea un curso.")
            else:
                botones = [[{"text": f"📚 {c.nombre} - {c.grado}", "callback_data": f"curso_{c.id}"}] for c in cursos]
                await send_message(BOT_PROFE_TOKEN, chat_id, "¿A qué curso pertenece este quiz?", reply_markup={"inline_keyboard": botones})
    elif message.get("document") and message["document"].get("file_name", "").endswith(".pdf"):
        await send_message(BOT_PROFE_TOKEN, chat_id, "📎 PDF recibido. Procesando...\n\n⏳ Esto puede tardar unos segundos.")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(f"https://api.telegram.org/bot{BOT_PROFE_TOKEN}/getFile", params={"file_id": message["document"]["file_id"]})
                pdf_r = await client.get(f"https://api.telegram.org/file/bot{BOT_PROFE_TOKEN}/{r.json()['result']['file_path']}")
            res = await procesar_pdf_zipgrade(pdf_r.content)
            resumen = "\n".join([f"• <b>{r['nombre']}</b>: {r['nota']}/5.0 ({r['porcentaje']}%)" for r in res])
            await send_message(BOT_PROFE_TOKEN, chat_id, f"✅ PDF procesado: <b>{len(res)} estudiantes</b>\n\n{resumen}\n\nResponde <b>OK</b> para guardar.")
            profe_estado[telegram_id] = {"resultados": res}
        except Exception as e:
            await send_message(BOT_PROFE_TOKEN, chat_id, f"❌ Error: {str(e)}")
    elif text and not text.startswith("/"):
        est_p = profe_estado.get(telegram_id, {})
        if est_p.get("esperando") == "nombre_curso":
            partes = text.rsplit(" ", 1)
            nuevo_curso = Curso(id=uuid.uuid4(), profe_id=profe.id, nombre=partes[0], grado=partes[1] if len(partes) > 1 else "")
            db.add(nuevo_curso)
            db.commit()
            profe_estado[telegram_id] = {}
            await send_message(BOT_PROFE_TOKEN, chat_id, "✅ Curso creado de manera exitosa!")
        elif text.upper() == "OK" and est_p.get("resultados"):
            await send_message(BOT_PROFE_TOKEN, chat_id, "✅ Resultados guardados y listos para los estudiantes.")
            profe_estado[telegram_id] = {}
        else:
            await send_message(BOT_PROFE_TOKEN, chat_id, "Comando no reconocido fuera del grupo.")
            
    return {"ok": True}

@app.post("/webhook/estudiante")
async def webhook_estudiante(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    
    callback = data.get("callback_query", {})
    if callback:
        chat_id = callback.get("from", {}).get("id")
        telegram_id = chat_id
        nombre_est = callback.get("from", {}).get("first_name", "Estudiante")
        cb_data = callback.get("data", "")
        
        if cb_data.startswith("entrar_grupo_"):
            curso_id = cb_data.replace("entrar_grupo_", "")
            curso = db.query(Curso).filter(Curso.id == curso_id).first()
            if curso:
                estudiante_grupo_estado[telegram_id] = {"curso_id": curso_id, "curso_nombre": curso.nombre}
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, 
                    f"🚪 Conectado al grupo de <b>{curso.nombre} - {curso.grado}</b>.\n\n"
                    f"👥 Tus compañeros y el profesor leerán tus mensajes y archivos.\n\n"
                    f"🚪 Para salir, escribe: /salir")
                await transmitir_a_estudiantes_y_profe(db, curso_id, telegram_id, nombre_est, 
                    {"text": f"📥 El alumno <b>{nombre_est}</b> se unió al chat."}, "text")
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
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, f"✅ Hola <b>{estudiante.nombre}</b>!\n\n📋 Comandos:\n/misnotas - Ver tus resultados\n/grupos - Entrar a una asignatura\n/salir - Salir del grupo")
        else:
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "Cuenta inactiva o nueva. Contacta a tu docente.")
        return {"ok": True}

    elif text == "/salir":
        if telegram_id in estudiante_grupo_estado:
            c_id = estudiante_grupo_estado[telegram_id]["curso_id"]
            await transmitir_a_estudiantes_y_profe(db, c_id, telegram_id, nombre, {"text": f"📤 El alumno <b>{nombre}</b> salió del grupo."}, "text")
            del estudiante_grupo_estado[telegram_id]
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "🚪 Volviste a tu chat privado.")
        else:
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "No estás en un grupo.")
        return {"ok": True}

    elif text == "/grupos":
        if estudiante and estudiante.activo:
            inscripciones = db.query(CursoEstudiante).filter(CursoEstudiante.estudiante_id == estudiante.id).all()
            if not inscripciones:
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "No estás inscrito en ningún curso.")
            else:
                botones = []
                for ins in inscripciones:
                    c = db.query(Curso).filter(Curso.id == ins.curso_id).first()
                    if c: botones.append([{"text": f"📖 {c.nombre} - {c.grado}", "callback_data": f"entrar_grupo_{c.id}"}])
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "🔍 Selecciona el grupo de asignatura:", reply_markup={"inline_keyboard": botones})
        return {"ok": True}

    elif text == "/misnotas":
        if estudiante and estudiante.activo:
            resultados = db.query(Resultado).filter(Resultado.estudiante_id == estudiante.id, Resultado.confirmado == True).all()
            if not resultados: await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "📭 No hay notas.")
            else:
                msg = "\n".join([f"📝 {db.query(Quiz).filter(Quiz.id==r.quiz_id).first().nombre if db.query(Quiz).filter(Quiz.id==r.quiz_id).first() else 'Quiz'}: <b>{r.nota}/5.0</b>" for r in resultados])
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, f"📊 <b>Tus notas:</b>\n\n{msg}")
        return {"ok": True}

    # --- TRANSMISIÓN MULTIMEDIA DEL ALUMNO INMERSO EN UN GRUPO ---
    if telegram_id in estudiante_grupo_estado:
        c_id = estudiante_grupo_estado[telegram_id]["curso_id"]
        if text:
            await transmitir_a_estudiantes_y_profe(db, c_id, telegram_id, nombre, {"text": text}, "text")
        elif message.get("document"):
            await transmitir_a_estudiantes_y_profe(db, c_id, telegram_id, nombre, {"file_id": message["document"]["file_id"], "caption": message.get("caption", "")}, "document")
        elif message.get("photo"):
            await transmitir_a_estudiantes_y_profe(db, c_id, telegram_id, nombre, {"file_id": message["photo"][-1]["file_id"], "caption": message.get("caption", "")}, "photo")
        elif message.get("voice"):
            await transmitir_a_estudiantes_y_profe(db, c_id, telegram_id, nombre, {"file_id": message["voice"]["file_id"]}, "voice")
        elif message.get("video"):
            await transmitir_a_estudiantes_y_profe(db, c_id, telegram_id, nombre, {"file_id": message["video"]["file_id"], "caption": message.get("caption", "")}, "video")
        return {"ok": True}

    if text and not text.startswith("/"):
        await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, "Comandos válidos: /start, /misnotas, /grupos")
    return {"ok": True}

# --- RESTO DE ENDPOINTS INTACTOS DE ADMINISTRACIÓN Y CONSULTAS ---
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
    nuevo = Curso(id=uuid.uuid4(), profe_id=data["profe_id"], nombre=data["nombre"], grado=data.get("grado", ""))
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
    return db.query(Resultado).filter(Resultado.estudiante_id == estudiante_id, Resultado.confirmado == True).all()

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