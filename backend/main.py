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
import boto3

app = FastAPI(title="ZipGrade System API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

engine = create_engine(settings.DATABASE_URL)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)

BOT_PROFE_TOKEN = os.getenv("BOT_PROFE_TOKEN", "")
BOT_ESTUDIANTE_TOKEN = os.getenv("BOT_ESTUDIANTE_TOKEN", "")
BASE_URL = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY", "")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "zipgrade-pdfs")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def subir_pdf_r2(pdf_bytes: bytes, nombre_archivo: str) -> str:
    try:
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            region_name="auto"
        )
        client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=nombre_archivo,
            Body=pdf_bytes,
            ContentType="application/pdf"
        )
        return f"{R2_PUBLIC_URL}/{nombre_archivo}"
    except Exception as e:
        print(f"Error subiendo PDF a R2: {e}")
        return ""

async def send_message(token, chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)

async def send_photo(token, chat_id, photo_url, caption=""):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            json={"chat_id": chat_id, "photo": photo_url, "caption": caption}
        )

async def send_document_url(token, chat_id, doc_url, caption=""):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            json={"chat_id": chat_id, "document": doc_url, "caption": caption}
        )

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
        cb_data = callback.get("data", "")
        if cb_data.startswith("curso_"):
            curso_id = cb_data.replace("curso_", "")
            curso = db.query(Curso).filter(Curso.id == curso_id).first()
            if curso:
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
            await send_message(BOT_PROFE_TOKEN, chat_id, "No tienes cursos aun. Usa /nuevocurso para crear uno.")
        else:
            lista = "\n".join([f"📚 {c.nombre} - {c.grado}" for c in cursos])
            await send_message(BOT_PROFE_TOKEN, chat_id, f"Tus cursos:\n\n{lista}")

    elif text == "/nuevocurso":
        if not profe or not profe.activo:
            await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Necesitas suscripcion activa.")
            return {"ok": True}
        marcador = db.query(Resultado).filter(
            Resultado.nombre_temp == f"__estado__{telegram_id}__esperando_curso"
        ).first()
        if not marcador:
            db.add(Resultado(id=uuid.uuid4(), nombre_temp=f"__estado__{telegram_id}__esperando_curso", confirmado=False))
            db.commit()
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

    elif document:
        file_name = document.get("file_name", "")
        file_id = document.get("file_id")

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"https://api.telegram.org/bot{BOT_PROFE_TOKEN}/getFile",
                params={"file_id": file_id})
            file_path = r.json()["result"]["file_path"]
            file_r = await client.get(f"https://api.telegram.org/file/bot{BOT_PROFE_TOKEN}/{file_path}")
            file_bytes = file_r.content

        if file_name.endswith(".pdf"):
            resultados_pendientes = db.query(Resultado).filter(
                Resultado.nombre_temp.like("PAG%"),
                Resultado.confirmado == False
            ).all()

            if resultados_pendientes:
                await send_message(BOT_PROFE_TOKEN, chat_id, "📄 PDF del quiz recibido. Subiendo...")
                nombre_archivo = f"quizzes/{uuid.uuid4()}.pdf"
                quiz_pdf_url = subir_pdf_r2(file_bytes, nombre_archivo)

                if quiz_pdf_url:
                    for r in resultados_pendientes:
                        r.quiz_pdf_url = quiz_pdf_url
                    db.commit()
                    await send_message(BOT_PROFE_TOKEN, chat_id,
                        "✅ PDF del quiz guardado.\n\nAhora pega la lista de nombres:\nPAG1: Nombre Apellido\nPAG2: Nombre Apellido...")
                else:
                    await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Error subiendo el PDF. Intenta de nuevo.")
            else:
                await send_message(BOT_PROFE_TOKEN, chat_id,
                    "📎 PDF de ZipGrade recibido. Procesando...\n\n⏳ Esto puede tardar unos segundos.")
                try:
                    resultados_lista = await procesar_pdf_zipgrade(file_bytes)
                    total = len(resultados_lista)

                    db.query(Resultado).filter(
                        Resultado.nombre_temp.like("PAG%"),
                        Resultado.confirmado == False
                    ).delete(synchronize_session=False)
                    db.commit()

                    for r in resultados_lista:
                        nuevo_r = Resultado(
                            id=uuid.uuid4(),
                            nombre_temp=r["nombre"],
                            nota=r["nota"],
                            puntos=r["puntos"],
                            posibles=r["posibles"],
                            porcentaje=r["porcentaje"],
                            pagina=r.get("pagina", 0),
                            imagen_url=r.get("imagen_url", ""),
                            confirmado=False
                        )
                        db.add(nuevo_r)
                    db.commit()

                    resumen = "\n".join([f"• <b>{r['nombre']}</b>: {r['nota']}/5.0 ({r['porcentaje']}%)" for r in resultados_lista])
                    await send_message(BOT_PROFE_TOKEN, chat_id,
                        f"✅ PDF procesado: <b>{total} estudiantes</b>\n\n{resumen}\n\n"
                        f"📄 Ahora envíame el PDF del quiz (las preguntas) para que los estudiantes lo reciban.")

                except Exception as e:
                    await send_message(BOT_PROFE_TOKEN, chat_id, f"❌ Error procesando PDF: {str(e)}")

    elif text and not text.startswith("/"):
        marcador = db.query(Resultado).filter(
            Resultado.nombre_temp == f"__estado__{telegram_id}__esperando_curso"
        ).first()

        if marcador and profe and profe.activo:
            partes = text.rsplit(" ", 1)
            nom = partes[0]
            grado = partes[1] if len(partes) > 1 else ""
            nuevo_curso = Curso(id=uuid.uuid4(), profe_id=profe.id, nombre=nom, grado=grado)
            db.add(nuevo_curso)
            db.delete(marcador)
            db.commit()
            await send_message(BOT_PROFE_TOKEN, chat_id,
                f"✅ Curso <b>{nom} {grado}</b> creado!\n\nUsa /subirquiz para subir un PDF.")

        elif "PAG" in text[:5]:
            resultados_db = db.query(Resultado).filter(
                Resultado.nombre_temp.like("PAG%"),
                Resultado.confirmado == False
            ).all()

            if not resultados_db:
                await send_message(BOT_PROFE_TOKEN, chat_id,
                    "❌ No encontré el PDF procesado. Por favor vuelve a enviar el PDF primero.")
                return {"ok": True}

            lineas = [l.strip() for l in text.split('\n') if l.strip() and l.strip()[:3] == "PAG"]
            nombres_asignados = 0
            for linea in lineas:
                try:
                    partes = linea.split(":")
                    num_pag = int(partes[0].replace("PAG", "").strip())
                    nombre_real = partes[1].split("-")[0].strip()
                    for r in resultados_db:
                        if r.pagina == num_pag:
                            r.nombre_temp = nombre_real
                            r.confirmado = True
                            nombres_asignados += 1
                            break
                except:
                    continue
            db.commit()

            resumen = "\n".join([f"• <b>{r.nombre_temp}</b>: {r.nota}/5.0" for r in resultados_db])
            await send_message(BOT_PROFE_TOKEN, chat_id,
                f"✅ <b>{nombres_asignados} nombres asignados y guardados!</b>\n\n{resumen}\n\n"
                f"✅ Los estudiantes ya pueden consultar sus notas.")

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
            nuevo = Estudiante(id=uuid.uuid4(), telegram_id=telegram_id, nombre=nombre, apellido="", activo=True)
            db.add(nuevo)
            db.commit()
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                f"👋 Hola <b>{nombre}</b>!\n\nBienvenido al sistema ZipGrade.\n\nEscribe tu nombre completo tal como aparece en tu examen para ver tu nota.")
        else:
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                f"✅ Hola <b>{estudiante.nombre}</b>!\n\nEscribe tu nombre completo para buscar tu nota.")

    elif text and not text.startswith("/"):
        nombre_buscar = text.strip()
        resultados = db.query(Resultado).filter(
            Resultado.nombre_temp.ilike(f"%{nombre_buscar}%"),
            Resultado.confirmado == True
        ).all()
        if not resultados:
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                f"❌ No encontré resultados para <b>{nombre_buscar}</b>.\n\nIntenta con tu apellido o como aparece en el examen.")
        else:
            for r in resultados:
                msg = f"📊 <b>{r.nombre_temp}</b>\n📝 Nota: <b>{r.nota}/5.0</b> ({r.porcentaje}%)"
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, msg)
                if r.imagen_url:
                    await send_photo(BOT_ESTUDIANTE_TOKEN, chat_id, r.imagen_url,
                        "📋 Tu hoja de respuestas")
                if r.quiz_pdf_url:
                    await send_document_url(BOT_ESTUDIANTE_TOKEN, chat_id, r.quiz_pdf_url,
                        "📄 PDF del quiz")

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

@app.post("/quizzes/procesar-pdf")
async def procesar_pdf_endpoint(archivo: UploadFile = File(...), curso_id: str = Form(...), db: Session = Depends(get_db)):
    contenido = await archivo.read()
    resultados = await procesar_pdf_zipgrade(contenido)
    return {"resultados": resultados, "total": len(resultados)}

@app.get("/resultados/historial/{estudiante_id}")
def historial_estudiante(estudiante_id: str, db: Session = Depends(get_db)):
    return db.query(Resultado).filter(
        Resultado.estudiante_id == estudiante_id,
        Resultado.confirmado == True).all()

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