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
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

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

def generar_excel(resultados, titulo):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Notas"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E79")
    title_font = Font(bold=True, size=13, color="1F4E79")
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    # Título
    ws.merge_cells("A1:D1")
    ws["A1"] = titulo
    ws["A1"].font = title_font
    ws["A1"].alignment = center
    ws.row_dimensions[1].height = 25

    # Encabezados
    encabezados = ["#", "Estudiante", "Nota (sobre 5.0)", "Porcentaje"]
    anchos = [5, 30, 18, 15]
    for col, (h, ancho) in enumerate(zip(encabezados, anchos), 1):
        cell = ws.cell(row=2, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        ws.column_dimensions[cell.column_letter].width = ancho
    ws.row_dimensions[2].height = 20

    # Datos
    for i, r in enumerate(resultados, 1):
        nota = float(r.nota) if r.nota else 0
        porcentaje = float(r.porcentaje) if r.porcentaje else 0
        fila = i + 2

        ws.cell(row=fila, column=1, value=i).alignment = center
        ws.cell(row=fila, column=2, value=r.nombre_temp or "").alignment = left
        ws.cell(row=fila, column=3, value=f"{nota:.2f} / 5.0").alignment = center
        ws.cell(row=fila, column=4, value=f"{porcentaje:.1f}%").alignment = center

        nota_cell = ws.cell(row=fila, column=3)
        if nota >= 3.5:
            nota_cell.fill = PatternFill("solid", fgColor="C6EFCE")
            nota_cell.font = Font(color="276221", bold=True)
        elif nota >= 3.0:
            nota_cell.fill = PatternFill("solid", fgColor="FFEB9C")
            nota_cell.font = Font(color="9C5700", bold=True)
        else:
            nota_cell.fill = PatternFill("solid", fgColor="FFC7CE")
            nota_cell.font = Font(color="9C0006", bold=True)

        ws.row_dimensions[fila].height = 18

    # Promedio
    total = len(resultados)
    if total > 0:
        promedio = sum(float(r.nota) for r in resultados if r.nota) / total
        aprobados = sum(1 for r in resultados if r.nota and float(r.nota) >= 3.0)
        fila_prom = total + 4

        ws.merge_cells(f"A{fila_prom}:D{fila_prom}")
        ws[f"A{fila_prom}"] = f"Total: {total}  |  Aprobados: {aprobados}  |  Reprobados: {total - aprobados}"
        ws[f"A{fila_prom}"].font = Font(bold=True, color="1F4E79")

        ws[f"A{fila_prom+1}"] = "Promedio del grupo:"
        ws[f"A{fila_prom+1}"].font = Font(bold=True)
        ws[f"C{fila_prom+1}"] = f"{promedio:.2f} / 5.0"
        ws[f"C{fila_prom+1}"].font = Font(bold=True, color="1F4E79")
        ws[f"C{fila_prom+1}"].alignment = Alignment(horizontal="center")

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

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

async def send_excel(token, chat_id, excel_bytes, filename, caption=""):
    async with httpx.AsyncClient(timeout=60) as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption},
            files={"document": (filename, excel_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )

def get_estado(db, telegram_id, clave):
    r = db.query(Resultado).filter(
        Resultado.nombre_temp == f"__estado__{telegram_id}__{clave}"
    ).first()
    return r.quiz_nombre if r else None

def set_estado(db, telegram_id, clave, valor):
    r = db.query(Resultado).filter(
        Resultado.nombre_temp == f"__estado__{telegram_id}__{clave}"
    ).first()
    if r:
        r.quiz_nombre = valor
    else:
        db.add(Resultado(id=uuid.uuid4(),
            nombre_temp=f"__estado__{telegram_id}__{clave}",
            quiz_nombre=valor, confirmado=False))
    db.commit()

def del_estado(db, telegram_id, clave):
    db.query(Resultado).filter(
        Resultado.nombre_temp == f"__estado__{telegram_id}__{clave}"
    ).delete(synchronize_session=False)
    db.commit()

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
                set_estado(db, telegram_id, "curso_seleccionado", f"{curso_id}|{curso.nombre}")
                set_estado(db, telegram_id, "paso", "esperando_nombre_quiz")
                await send_message(BOT_PROFE_TOKEN, chat_id,
                    f"📚 Curso: <b>{curso.nombre} - {curso.grado}</b>\n\n✏️ Escribe el nombre del quiz:\nEjemplo: <b>Quiz 1 Primer Periodo</b>")

        elif cb_data.startswith("excel_quiz_"):
            partes = cb_data.replace("excel_quiz_", "").split("|", 1)
            curso_buscar = partes[0]
            quiz_buscar = partes[1] if len(partes) > 1 else ""
            resultados = db.query(Resultado).filter(
                Resultado.curso_nombre.ilike(f"%{curso_buscar}%"),
                Resultado.quiz_nombre.ilike(f"%{quiz_buscar}%"),
                Resultado.confirmado == True
            ).all()
            if not resultados:
                await send_message(BOT_PROFE_TOKEN, chat_id, f"❌ No hay resultados para {quiz_buscar}.")
            else:
                titulo = f"Notas - {curso_buscar} - {quiz_buscar}"
                excel_bytes = generar_excel(resultados, titulo)
                filename = f"notas_{curso_buscar}_{quiz_buscar}.xlsx".replace(" ", "_")
                await send_excel(BOT_PROFE_TOKEN, chat_id, excel_bytes, filename,
                    f"📊 {titulo} — {len(resultados)} estudiantes")

        elif cb_data.startswith("excel_todos_"):
            curso_buscar = cb_data.replace("excel_todos_", "")
            resultados = db.query(Resultado).filter(
                Resultado.curso_nombre.ilike(f"%{curso_buscar}%"),
                Resultado.confirmado == True
            ).all()
            if not resultados:
                await send_message(BOT_PROFE_TOKEN, chat_id, f"❌ No hay resultados para {curso_buscar}.")
            else:
                titulo = f"Todas las notas - {curso_buscar}"
                excel_bytes = generar_excel(resultados, titulo)
                filename = f"notas_{curso_buscar}_todos.xlsx".replace(" ", "_")
                await send_excel(BOT_PROFE_TOKEN, chat_id, excel_bytes, filename,
                    f"📊 {titulo} — {len(resultados)} registros")

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
                    f"✅ Hola <b>{profe.nombre}</b>!\n\n📋 Comandos:\n/micursos - Ver tus cursos\n/nuevocurso - Crear un curso\n/subirquiz - Subir quiz\n/excel - Generar Excel de notas\n/estado - Ver suscripcion")
            else:
                await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Tu suscripcion no esta activa.")

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
            await send_message(BOT_PROFE_TOKEN, chat_id, "No tienes cursos. Usa /nuevocurso para crear uno.")
        else:
            lista = "\n".join([f"📚 <b>{c.nombre}</b> - {c.grado}" for c in cursos])
            await send_message(BOT_PROFE_TOKEN, chat_id, f"Tus cursos:\n\n{lista}")

    elif text == "/nuevocurso":
        if not profe or not profe.activo:
            await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Necesitas suscripcion activa.")
            return {"ok": True}
        set_estado(db, telegram_id, "paso", "esperando_nombre_curso")
        await send_message(BOT_PROFE_TOKEN, chat_id,
            "✏️ Escribe el nombre y grado del curso:\nEjemplo: <b>Matematicas 9B</b>")

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

    elif text == "/excel" or text.lower().startswith("excel"):
        if not profe or not profe.activo:
            await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Necesitas suscripcion activa.")
            return {"ok": True}
        cursos_con_datos = db.query(Resultado.curso_nombre).filter(
            Resultado.confirmado == True,
            Resultado.curso_nombre != None
        ).distinct().all()
        if not cursos_con_datos:
            await send_message(BOT_PROFE_TOKEN, chat_id, "❌ No hay resultados guardados aún.")
        else:
            set_estado(db, telegram_id, "paso", "esperando_materia_excel")
            lista = "\n".join([f"• <b>{c[0]}</b>" for c in cursos_con_datos])
            await send_message(BOT_PROFE_TOKEN, chat_id,
                f"📊 ¿De qué materia quieres el Excel?\n\nMaterias disponibles:\n{lista}\n\nEscribe el nombre de la materia:")

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
            paso = get_estado(db, telegram_id, "paso")
            curso_info = get_estado(db, telegram_id, "curso_seleccionado")
            quiz_nombre = get_estado(db, telegram_id, "quiz_nombre")

            resultados_pendientes = db.query(Resultado).filter(
                Resultado.nombre_temp.like("PAG%"),
                Resultado.confirmado == False
            ).all()

            if resultados_pendientes and paso == "esperando_pdf_quiz":
                await send_message(BOT_PROFE_TOKEN, chat_id, "📄 PDF del quiz recibido. Subiendo...")
                nombre_archivo = f"quizzes/{uuid.uuid4()}.pdf"
                quiz_pdf_url = subir_pdf_r2(file_bytes, nombre_archivo)
                if quiz_pdf_url:
                    for r in resultados_pendientes:
                        r.quiz_pdf_url = quiz_pdf_url
                    db.commit()
                    set_estado(db, telegram_id, "paso", "esperando_nombres")
                    await send_message(BOT_PROFE_TOKEN, chat_id,
                        "✅ PDF del quiz guardado.\n\nAhora pega la lista de nombres:\nPAG1: Nombre Apellido\nPAG2: Nombre Apellido...")
                else:
                    await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Error subiendo el PDF.")
            else:
                if not curso_info:
                    await send_message(BOT_PROFE_TOKEN, chat_id, "❌ Primero selecciona un curso con /subirquiz")
                    return {"ok": True}

                curso_id, curso_nombre = curso_info.split("|", 1)
                qnombre = quiz_nombre or "Quiz"

                await send_message(BOT_PROFE_TOKEN, chat_id,
                    f"📎 PDF de ZipGrade recibido.\n📚 Curso: <b>{curso_nombre}</b>\n📝 Quiz: <b>{qnombre}</b>\n\n⏳ Procesando...")
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
                            curso_nombre=curso_nombre,
                            quiz_nombre=qnombre,
                            confirmado=False
                        )
                        db.add(nuevo_r)
                    db.commit()
                    set_estado(db, telegram_id, "paso", "esperando_pdf_quiz")

                    resumen = "\n".join([f"• <b>{r['nombre']}</b>: {r['nota']}/5.0 ({r['porcentaje']}%)" for r in resultados_lista])
                    await send_message(BOT_PROFE_TOKEN, chat_id,
                        f"✅ PDF procesado: <b>{total} estudiantes</b>\n\n{resumen}\n\n"
                        f"📄 Ahora envíame el PDF del quiz (las preguntas).")

                except Exception as e:
                    await send_message(BOT_PROFE_TOKEN, chat_id, f"❌ Error procesando PDF: {str(e)}")

    elif text and not text.startswith("/"):
        paso = get_estado(db, telegram_id, "paso")

        if paso == "esperando_nombre_curso" and profe and profe.activo:
            partes = text.rsplit(" ", 1)
            nom = partes[0]
            grado = partes[1] if len(partes) > 1 else ""
            nuevo_curso = Curso(id=uuid.uuid4(), profe_id=profe.id, nombre=nom, grado=grado)
            db.add(nuevo_curso)
            del_estado(db, telegram_id, "paso")
            db.commit()
            await send_message(BOT_PROFE_TOKEN, chat_id,
                f"✅ Curso <b>{nom} {grado}</b> creado!\n\nUsa /subirquiz para subir un quiz.")

        elif paso == "esperando_nombre_quiz":
            set_estado(db, telegram_id, "quiz_nombre", text.strip())
            set_estado(db, telegram_id, "paso", "esperando_pdf_zipgrade")
            await send_message(BOT_PROFE_TOKEN, chat_id,
                f"✅ Quiz: <b>{text.strip()}</b>\n\n📎 Ahora envíame el PDF de ZipGrade.")

        elif paso == "esperando_materia_excel":
            materia = text.strip()
            del_estado(db, telegram_id, "paso")
            quizzes = db.query(Resultado.quiz_nombre).filter(
                Resultado.curso_nombre.ilike(f"%{materia}%"),
                Resultado.confirmado == True,
                Resultado.quiz_nombre != None
            ).distinct().all()
            if not quizzes:
                await send_message(BOT_PROFE_TOKEN, chat_id,
                    f"❌ No encontré resultados para <b>{materia}</b>.")
            else:
                botones_lista = [[{"text": f"📝 {q[0]}", "callback_data": f"excel_quiz_{materia}|{q[0]}"}] for q in quizzes]
                botones_lista.append([{"text": "📊 Todos los quizzes", "callback_data": f"excel_todos_{materia}"}])
                botones = {"inline_keyboard": botones_lista}
                await send_message(BOT_PROFE_TOKEN, chat_id,
                    f"📚 <b>{materia}</b> — ¿De qué quiz quieres el Excel?",
                    reply_markup=botones)

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

            del_estado(db, telegram_id, "paso")
            del_estado(db, telegram_id, "curso_seleccionado")
            del_estado(db, telegram_id, "quiz_nombre")

            curso_n = resultados_db[0].curso_nombre if resultados_db else ""
            quiz_n = resultados_db[0].quiz_nombre if resultados_db else ""
            resumen = "\n".join([f"• <b>{r.nombre_temp}</b>: {r.nota}/5.0" for r in resultados_db])
            await send_message(BOT_PROFE_TOKEN, chat_id,
                f"✅ <b>{nombres_asignados} estudiantes guardados!</b>\n"
                f"📚 Curso: <b>{curso_n}</b>\n📝 Quiz: <b>{quiz_n}</b>\n\n{resumen}\n\n"
                f"💡 Escribe <b>/excel</b> para generar un Excel con las notas.")

        else:
            await send_message(BOT_PROFE_TOKEN, chat_id,
                "Comandos:\n/start\n/micursos\n/nuevocurso\n/subirquiz\n/excel\n/estado")

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
                f"👋 Hola <b>{nombre}</b>!\n\nBienvenido al sistema ZipGrade.\n\n"
                f"Puedes:\n• Escribir tu <b>nombre</b> para ver todas tus notas\n"
                f"• Escribir una <b>materia</b> (ej: matematicas) para ver notas de esa materia")
        else:
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                f"✅ Hola <b>{estudiante.nombre}</b>!\n\nEscribe tu nombre o una materia para ver tus notas.")

    elif text and not text.startswith("/"):
        busqueda = text.strip()

        resultados_materia = db.query(Resultado).filter(
            Resultado.curso_nombre.ilike(f"%{busqueda}%"),
            Resultado.confirmado == True
        ).all()

        resultados_nombre = db.query(Resultado).filter(
            Resultado.nombre_temp.ilike(f"%{busqueda}%"),
            Resultado.confirmado == True
        ).all()

        if resultados_materia and not resultados_nombre:
            est = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
            if est and est.nombre:
                resultados = db.query(Resultado).filter(
                    Resultado.curso_nombre.ilike(f"%{busqueda}%"),
                    Resultado.nombre_temp.ilike(f"%{est.nombre}%"),
                    Resultado.confirmado == True
                ).all()
                if not resultados:
                    await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                        f"❌ No encontré tus notas en <b>{busqueda}</b>.\n\nPrimero escribe tu nombre completo.")
                else:
                    msg = f"📚 <b>Tus notas en {busqueda.title()}:</b>\n\n"
                    for r in resultados:
                        msg += f"📝 <b>{r.quiz_nombre}</b>: {r.nota}/5.0 ({r.porcentaje}%)\n"
                    await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, msg)
                    for r in resultados:
                        if r.imagen_url:
                            await send_photo(BOT_ESTUDIANTE_TOKEN, chat_id, r.imagen_url,
                                f"📋 {r.quiz_nombre} - Tu hoja de respuestas")
                        if r.quiz_pdf_url:
                            await send_document_url(BOT_ESTUDIANTE_TOKEN, chat_id, r.quiz_pdf_url,
                                f"📄 {r.quiz_nombre} - PDF del quiz")
            else:
                await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                    f"❌ Primero escribe tu nombre completo para registrarte.")

        elif resultados_nombre:
            est = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
            if est and est.nombre != busqueda:
                est.nombre = busqueda
                db.commit()

            msg = f"📊 <b>Todas tus notas ({busqueda}):</b>\n\n"
            for r in resultados_nombre:
                curso = r.curso_nombre or "Sin curso"
                quiz = r.quiz_nombre or "Sin quiz"
                msg += f"📚 <b>{curso}</b> - {quiz}: <b>{r.nota}/5.0</b> ({r.porcentaje}%)\n"
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id, msg)
            for r in resultados_nombre:
                if r.imagen_url:
                    await send_photo(BOT_ESTUDIANTE_TOKEN, chat_id, r.imagen_url,
                        f"📋 {r.curso_nombre} - {r.quiz_nombre}")
                if r.quiz_pdf_url:
                    await send_document_url(BOT_ESTUDIANTE_TOKEN, chat_id, r.quiz_pdf_url,
                        f"📄 {r.curso_nombre} - {r.quiz_nombre}")
        else:
            await send_message(BOT_ESTUDIANTE_TOKEN, chat_id,
                f"❌ No encontré resultados para <b>{busqueda}</b>.\n\n"
                f"Intenta con tu nombre completo o el nombre de la materia.")

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