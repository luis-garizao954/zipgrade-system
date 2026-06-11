"""
Bot del Estudiante - ZipGrade System
Comandos:
  /start      - Registrarse e ingresar apellido
  /misnotas   - Ver historial de resultados
  /descargar  - Descargar PDF de un quiz específico
  /estado     - Ver estado de suscripción
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "http://localhost:8000"

ESPERANDO_NOMBRE, ESPERANDO_APELLIDO = range(2)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

async def api_get(endpoint: str, params: dict = None):
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{API_URL}{endpoint}", params=params, timeout=30)
        return r.json() if r.status_code == 200 else None

async def api_post(endpoint: str, data: dict):
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{API_URL}{endpoint}", json=data, timeout=30)
        return r.json() if r.status_code in [200, 201] else None

# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    est = await api_get(f"/estudiantes/by-telegram/{tid}")
    if est:
        await update.message.reply_text(
            f"👋 Hola de nuevo, *{est['nombre']} {est['apellido']}*\\!\n\n"
            f"Usa /misnotas para ver tus resultados\\.",
            parse_mode="MarkdownV2"
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "👋 *Bienvenido al sistema de resultados ZipGrade*\n\n"
        "Para registrarte necesito tu *nombre*\\. ¿Cómo te llamas?",
        parse_mode="MarkdownV2"
    )
    return ESPERANDO_NOMBRE

async def recibir_nombre(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["nombre"] = update.message.text
    await update.message.reply_text("¿Y tu apellido?")
    return ESPERANDO_APELLIDO

async def recibir_apellido(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    nombre = ctx.user_data.get("nombre", "")
    apellido = update.message.text
    est = await api_post("/estudiantes/registrar", {
        "telegram_id": tid,
        "nombre": nombre,
        "apellido": apellido
    })
    if est:
        await update.message.reply_text(
            f"✅ *Registrado como {nombre} {apellido}*\n\n"
            f"Ahora necesitas una suscripción activa para consultar tus resultados\\.\n"
            f"Contacta a tu profe o al administrador para activarla\\.\n\n"
            f"Usa /misnotas para ver tu historial\\.",
            parse_mode="MarkdownV2"
        )
    else:
        await update.message.reply_text("❌ Error en el registro. Intenta de nuevo con /start")
    return ConversationHandler.END

# ─── /misnotas ────────────────────────────────────────────────────────────────

async def mis_notas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id

    # Verificar registro
    est = await api_get(f"/estudiantes/by-telegram/{tid}")
    if not est:
        await update.message.reply_text("No estás registrado. Usa /start")
        return

    # Verificar suscripción del estudiante
    activo = await api_get(f"/estudiantes/activo/{tid}")
    if not activo or not activo.get("activo"):
        await update.message.reply_text(
            "⚠️ *Tu suscripción no está activa*\n\n"
            "Contacta al administrador para activarla y acceder a tu historial\\.",
            parse_mode="MarkdownV2"
        )
        return

    # Obtener historial (solo del estudiante, independiente del profe)
    historial = await api_get(f"/resultados/historial/{est['id']}")
    if not historial or len(historial) == 0:
        await update.message.reply_text(
            "📭 *No tienes resultados aún*\n\n"
            "Cuando tu profe suba un quiz y confirme tu apellido, "
            "aparecerá aquí\\.",
            parse_mode="MarkdownV2"
        )
        return

    # Agrupar por curso
    cursos = {}
    for r in historial:
        curso_nombre = r.get("curso_nombre", "Sin curso")
        if curso_nombre not in cursos:
            cursos[curso_nombre] = []
        cursos[curso_nombre].append(r)

    texto = f"📊 *Historial de {est['nombre']} {est['apellido']}*\n\n"
    keyboard = []

    for curso_nombre, resultados in cursos.items():
        texto += f"📚 *{curso_nombre}*\n"
        promedio = sum(float(r["nota"]) for r in resultados) / len(resultados)
        texto += f"Promedio: {promedio:.1f}\n\n"
        for r in resultados:
            nota = float(r["nota"])
            emoji = "✅" if nota >= 3.0 else "❌"
            texto += f"{emoji} {r['quiz_nombre']} \\- {r['fecha']}: *{nota:.1f}*\n"
            keyboard.append([
                InlineKeyboardButton(
                    f"📄 Ver {r['quiz_nombre']}",
                    callback_data=f"verresult_{r['id']}"
                )
            ])
        texto += "\n"

    await update.message.reply_text(
        texto,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )

# ─── VER RESULTADO INDIVIDUAL ─────────────────────────────────────────────────

async def ver_resultado(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    resultado_id = query.data.replace("verresult_", "")
    tid = update.effective_user.id

    # Verificar que el estudiante sigue activo antes de dar acceso
    activo = await api_get(f"/estudiantes/activo/{tid}")
    if not activo or not activo.get("activo"):
        await query.message.reply_text("⚠️ Tu suscripción venció. Renuévala para ver tus resultados.")
        return

    resultado = await api_get(f"/resultados/{resultado_id}")
    if not resultado:
        await query.message.reply_text("❌ Resultado no encontrado.")
        return

    nota = float(resultado["nota"])
    estado = "✅ Aprobado" if nota >= 3.0 else "❌ Reprobado"
    porcentaje = int((resultado["correctas"] / resultado["total"]) * 100)

    # Generar URL temporal segura para el PDF (1 hora)
    url_pdf = await api_get(f"/resultados/{resultado_id}/url-pdf")

    texto = (
        f"📄 *{resultado['quiz_nombre']}*\n"
        f"Curso: {resultado['curso_nombre']}\n"
        f"Fecha: {resultado['fecha']}\n\n"
        f"Correctas: {resultado['correctas']}/{resultado['total']} \\({porcentaje}%\\)\n"
        f"Nota: *{nota:.1f} / 5\\.0*\n"
        f"Estado: {estado}\n"
    )

    keyboard = []
    if url_pdf and url_pdf.get("url"):
        keyboard.append([InlineKeyboardButton("📥 Descargar PDF", url=url_pdf["url"])])

    await query.message.reply_text(
        texto,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode="MarkdownV2"
    )

# ─── /estado ──────────────────────────────────────────────────────────────────

async def estado(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    est = await api_get(f"/estudiantes/by-telegram/{tid}")
    if not est:
        await update.message.reply_text("No estás registrado. Usa /start")
        return
    estado_txt = "✅ Activa" if est["activo"] else "❌ Inactiva"
    vence = est.get("suscripcion_hasta", "—")
    await update.message.reply_text(
        f"📊 *Tu suscripción*\n\n"
        f"Estado: {estado_txt}\n"
        f"Vence: {vence[:10] if vence else '—'}\n\n"
        f"Recuerda: aunque tu profe no pague, tú puedes seguir viendo "
        f"tu historial mientras tu suscripción esté activa\\.",
        parse_mode="MarkdownV2"
    )

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    from backend.config import settings
    app = ApplicationBuilder().token(settings.BOT_ESTUDIANTE_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ESPERANDO_NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre)],
            ESPERANDO_APELLIDO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_apellido)],
        },
        fallbacks=[]
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("misnotas", mis_notas))
    app.add_handler(CommandHandler("estado", estado))
    app.add_handler(CallbackQueryHandler(ver_resultado, pattern="^verresult_"))

    logger.info("Bot del estudiante iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()
