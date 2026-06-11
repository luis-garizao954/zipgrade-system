"""
Bot del Profe - ZipGrade System
Comandos:
  /start       - Registrarse
  /micursos    - Ver y crear cursos
  /subirquiz   - Subir PDF de ZipGrade
  /estudiantes - Gestionar estudiantes del curso
  /estado      - Ver estado de suscripción
"""
import logging
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "http://localhost:8000"

# Estados del ConversationHandler
ESPERANDO_NOMBRE_CURSO, ESPERANDO_GRADO, ESPERANDO_PDF, REVISANDO_NOMBRES, ESPERANDO_NOMBRE_QUIZ = range(5)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

async def api_get(endpoint: str, params: dict = None):
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{API_URL}{endpoint}", params=params, timeout=30)
        return r.json() if r.status_code == 200 else None

async def api_post(endpoint: str, data: dict = None, files=None):
    async with httpx.AsyncClient() as c:
        if files:
            r = await c.post(f"{API_URL}{endpoint}", data=data, files=files, timeout=120)
        else:
            r = await c.post(f"{API_URL}{endpoint}", json=data, timeout=30)
        return r.json() if r.status_code in [200, 201] else None

# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    nombre = update.effective_user.full_name
    profe = await api_post("/profes/registrar", {"telegram_id": tid, "nombre": nombre})
    if profe:
        await update.message.reply_text(
            f"👋 Hola, *{nombre}*\\!\n\n"
            f"Estás registrado como profe en el sistema ZipGrade\\.\n\n"
            f"📋 *Comandos disponibles:*\n"
            f"/micursos \\- Ver y crear cursos\n"
            f"/subirquiz \\- Subir PDF de ZipGrade\n"
            f"/estado \\- Ver tu suscripción\n\n"
            f"⚠️ Necesitas una suscripción activa para subir quizzes\\.",
            parse_mode="MarkdownV2"
        )
    else:
        await update.message.reply_text("❌ Error registrándote. Intenta de nuevo.")

# ─── /estado ──────────────────────────────────────────────────────────────────

async def estado(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    profe = await api_get(f"/profes/by-telegram/{tid}")
    if not profe:
        await update.message.reply_text("No estás registrado. Usa /start")
        return
    estado_txt = "✅ Activa" if profe["activo"] else "❌ Inactiva"
    vence = profe.get("suscripcion_hasta", "—")
    await update.message.reply_text(
        f"📊 *Tu suscripción*\n\n"
        f"Estado: {estado_txt}\n"
        f"Vence: {vence[:10] if vence else '—'}\n\n"
        f"Para renovar contacta al administrador\\.",
        parse_mode="MarkdownV2"
    )

# ─── /micursos ────────────────────────────────────────────────────────────────

async def mis_cursos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    cursos = await api_get(f"/cursos/by-profe-telegram/{tid}")
    if not cursos:
        keyboard = [[InlineKeyboardButton("➕ Crear primer curso", callback_data="crear_curso")]]
        await update.message.reply_text(
            "No tienes cursos aún.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    keyboard = [[InlineKeyboardButton(f"📚 {c['nombre']} - {c['grado']}", callback_data=f"curso_{c['id']}")] for c in cursos]
    keyboard.append([InlineKeyboardButton("➕ Nuevo curso", callback_data="crear_curso")])
    await update.message.reply_text(
        "📚 *Tus cursos:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )

async def callback_curso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "crear_curso":
        await query.message.reply_text("✏️ ¿Cómo se llama el nuevo curso? (ej: Matemáticas)")
        return ESPERANDO_NOMBRE_CURSO

async def recibir_nombre_curso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["nombre_curso"] = update.message.text
    await update.message.reply_text("¿Cuál es el grado? (ej: 9°B)")
    return ESPERANDO_GRADO

async def recibir_grado(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    nombre = ctx.user_data.get("nombre_curso")
    grado = update.message.text
    profe = await api_get(f"/profes/by-telegram/{tid}")
    if not profe:
        await update.message.reply_text("Error. Usa /start primero.")
        return ConversationHandler.END
    curso = await api_post("/cursos/crear", {
        "profe_id": profe["id"],
        "nombre": nombre,
        "grado": grado
    })
    if curso:
        await update.message.reply_text(f"✅ Curso *{nombre}* \\- {grado} creado\\!", parse_mode="MarkdownV2")
    else:
        await update.message.reply_text("❌ Error creando el curso.")
    return ConversationHandler.END

# ─── /subirquiz ───────────────────────────────────────────────────────────────

async def subir_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    activo = await api_get(f"/profes/activo/{tid}")
    if not activo or not activo.get("activo"):
        await update.message.reply_text(
            "⚠️ Tu suscripción no está activa.\n"
            "Contacta al administrador para renovarla."
        )
        return ConversationHandler.END
    cursos = await api_get(f"/cursos/by-profe-telegram/{tid}")
    if not cursos:
        await update.message.reply_text("Primero crea un curso con /micursos")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"📚 {c['nombre']} - {c['grado']}", callback_data=f"selcurso_{c['id']}")] for c in cursos]
    await update.message.reply_text(
        "¿A qué curso pertenece este quiz?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ESPERANDO_NOMBRE_QUIZ

async def seleccionar_curso_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    curso_id = query.data.replace("selcurso_", "")
    ctx.user_data["curso_id"] = curso_id
    await query.message.reply_text("¿Cómo se llama este quiz? (ej: Quiz 1 - Fracciones)")
    return ESPERANDO_PDF

async def recibir_nombre_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["nombre_quiz"] = update.message.text
    await update.message.reply_text(
        "📎 Ahora envía el *PDF de ZipGrade* con todos los resultados\\.",
        parse_mode="MarkdownV2"
    )
    return REVISANDO_NOMBRES

async def recibir_pdf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.document or not update.message.document.file_name.endswith(".pdf"):
        await update.message.reply_text("Por favor envía un archivo PDF.")
        return REVISANDO_NOMBRES

    await update.message.reply_text("⏳ Procesando PDF y leyendo apellidos con IA...")

    file = await update.message.document.get_file()
    pdf_bytes = await file.download_as_bytearray()
    tid = update.effective_user.id
    profe = await api_get(f"/profes/by-telegram/{tid}")

    # Enviar al backend para procesar
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(
            f"{API_URL}/quizzes/procesar-pdf",
            data={
                "profe_id": profe["id"],
                "curso_id": ctx.user_data["curso_id"],
                "nombre_quiz": ctx.user_data["nombre_quiz"]
            },
            files={"pdf": ("quiz.pdf", bytes(pdf_bytes), "application/pdf")}
        )
        if r.status_code != 200:
            await update.message.reply_text("❌ Error procesando el PDF.")
            return ConversationHandler.END
        resultado = r.json()

    ctx.user_data["procesamiento_id"] = resultado["procesamiento_id"]
    paginas = resultado["paginas"]
    ctx.user_data["paginas"] = paginas
    ctx.user_data["pagina_actual"] = 0

    await update.message.reply_text(
        f"✅ PDF procesado: *{len(paginas)} páginas* encontradas\\.\n\n"
        f"Ahora revisarás cada resultado para confirmar o corregir el apellido\\.",
        parse_mode="MarkdownV2"
    )
    await mostrar_pagina_revision(update, ctx)
    return ConversationHandler.END

async def mostrar_pagina_revision(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    paginas = ctx.user_data.get("paginas", [])
    i = ctx.user_data.get("pagina_actual", 0)
    if i >= len(paginas):
        await update.message.reply_text(
            "🎉 *¡Revisión completa\\!* Todos los resultados fueron guardados\\.\n"
            "Los estudiantes ya pueden consultar sus notas\\.",
            parse_mode="MarkdownV2"
        )
        return
    p = paginas[i]
    confianza_emoji = "✅" if p["confianza"] == "alta" else "⚠️" if p["confianza"] == "media" else "❌"
    keyboard = [
        [InlineKeyboardButton("✅ Confirmar", callback_data=f"confirmar_{i}"),
         InlineKeyboardButton("✏️ Corregir", callback_data=f"corregir_{i}")],
        [InlineKeyboardButton("⏭️ Omitir", callback_data=f"omitir_{i}")]
    ]
    await update.message.reply_text(
        f"📄 Página {i+1}/{len(paginas)}\n\n"
        f"Apellido detectado: *{p['apellido_detectado'] or 'No detectado'}*\n"
        f"Confianza IA: {confianza_emoji} {p['confianza']}\n\n"
        f"¿Es correcto?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    from backend.config import settings
    app = ApplicationBuilder().token(settings.BOT_PROFE_TOKEN).build()

    conv_curso = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_curso, pattern="^crear_curso$")],
        states={
            ESPERANDO_NOMBRE_CURSO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre_curso)],
            ESPERANDO_GRADO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_grado)],
        },
        fallbacks=[]
    )

    conv_quiz = ConversationHandler(
        entry_points=[CommandHandler("subirquiz", subir_quiz)],
        states={
            ESPERANDO_NOMBRE_QUIZ: [
                CallbackQueryHandler(seleccionar_curso_quiz, pattern="^selcurso_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre_quiz)
            ],
            ESPERANDO_PDF: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre_quiz)],
            REVISANDO_NOMBRES: [MessageHandler(filters.Document.PDF, recibir_pdf)],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("estado", estado))
    app.add_handler(CommandHandler("micursos", mis_cursos))
    app.add_handler(conv_curso)
    app.add_handler(conv_quiz)

    logger.info("Bot del profe iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()
