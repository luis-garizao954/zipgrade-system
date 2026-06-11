from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
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
from decimal import Decimal
import uuid

app = FastAPI(title="ZipGrade System API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

engine = create_engine(settings.DATABASE_URL)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ─── PROFES ───────────────────────────────────────────────────────────────────

@app.post("/profes/registrar")
def registrar_profe(data: dict, db: Session = Depends(get_db)):
    profe = db.query(Profe).filter(Profe.telegram_id == data["telegram_id"]).first()
    if not profe:
        profe = Profe(telegram_id=data["telegram_id"], nombre=data["nombre"])
        db.add(profe)
        db.commit()
        db.refresh(profe)
    return {"id": str(profe.id), "nombre": profe.nombre, "activo": profe.activo}

@app.get("/profes/by-telegram/{telegram_id}")
def get_profe_by_telegram(telegram_id: int, db: Session = Depends(get_db)):
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if not profe:
        raise HTTPException(404, "Profe no encontrado")
    return {
        "id": str(profe.id), "nombre": profe.nombre,
        "activo": profe.activo,
        "suscripcion_hasta": str(profe.suscripcion_hasta) if profe.suscripcion_hasta else None
    }

@app.get("/profes/activo/{telegram_id}")
def check_profe_activo(telegram_id: int, db: Session = Depends(get_db)):
    return {"activo": profe_activo(db, telegram_id)}

# ─── ESTUDIANTES ──────────────────────────────────────────────────────────────

@app.post("/estudiantes/registrar")
def registrar_estudiante(data: dict, db: Session = Depends(get_db)):
    est = db.query(Estudiante).filter(Estudiante.telegram_id == data["telegram_id"]).first()
    if not est:
        est = Estudiante(
            telegram_id=data["telegram_id"],
            nombre=data["nombre"],
            apellido=data["apellido"]
        )
        db.add(est)
        db.commit()
        db.refresh(est)
    return {"id": str(est.id), "nombre": est.nombre, "apellido": est.apellido, "activo": est.activo}

@app.get("/estudiantes/by-telegram/{telegram_id}")
def get_estudiante_by_telegram(telegram_id: int, db: Session = Depends(get_db)):
    est = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
    if not est:
        raise HTTPException(404, "Estudiante no encontrado")
    return {
        "id": str(est.id), "nombre": est.nombre, "apellido": est.apellido,
        "activo": est.activo,
        "suscripcion_hasta": str(est.suscripcion_hasta) if est.suscripcion_hasta else None
    }

@app.get("/estudiantes/activo/{telegram_id}")
def check_estudiante_activo(telegram_id: int, db: Session = Depends(get_db)):
    return {"activo": estudiante_activo(db, telegram_id)}

# ─── CURSOS ───────────────────────────────────────────────────────────────────

@app.post("/cursos/crear")
def crear_curso(data: dict, db: Session = Depends(get_db)):
    curso = Curso(profe_id=data["profe_id"], nombre=data["nombre"], grado=data.get("grado", ""))
    db.add(curso)
    db.commit()
    db.refresh(curso)
    return {"id": str(curso.id), "nombre": curso.nombre, "grado": curso.grado}

@app.get("/cursos/by-profe-telegram/{telegram_id}")
def cursos_by_profe(telegram_id: int, db: Session = Depends(get_db)):
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if not profe:
        return []
    return [{"id": str(c.id), "nombre": c.nombre, "grado": c.grado} for c in profe.cursos]

# ─── QUIZZES Y PROCESAMIENTO PDF ──────────────────────────────────────────────

@app.post("/quizzes/procesar-pdf")
async def procesar_pdf(
    profe_id: str = Form(...),
    curso_id: str = Form(...),
    nombre_quiz: str = Form(...),
    pdf: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Verificar suscripción del profe
    profe = db.query(Profe).filter(Profe.id == profe_id).first()
    if not profe or not profe.activo:
        raise HTTPException(403, "Suscripción del profe no activa")

    pdf_bytes = await pdf.read()

    # Crear quiz
    quiz = Quiz(curso_id=curso_id, nombre=nombre_quiz, total_preguntas=20)
    db.add(quiz)
    db.commit()
    db.refresh(quiz)

    # Procesar PDF con IA
    paginas = procesar_pdf_zipgrade(pdf_bytes)

    # Guardar resultados preliminares (sin confirmar)
    resultados_guardados = []
    for p in paginas:
        resultado = Resultado(
            quiz_id=str(quiz.id),
            apellido_detectado=p["apellido_detectado"],
            confirmado=False
        )
        db.add(resultado)
        db.commit()
        db.refresh(resultado)

        # Guardar PDF individual en R2
        pdf_url = subir_pdf(p["pdf_bytes"], profe_id, str(quiz.id), p["apellido_detectado"] or f"pagina_{p['pagina']}")
        resultado.pdf_url = pdf_url
        db.commit()

        resultados_guardados.append({
            "resultado_id": str(resultado.id),
            "pagina": p["pagina"],
            "apellido_detectado": p["apellido_detectado"],
            "confianza": p["confianza"],
            "necesita_revision": p["necesita_revision"],
            "imagen_preview": p.get("imagen_preview", "")
        })

    return {
        "procesamiento_id": str(quiz.id),
        "quiz_nombre": nombre_quiz,
        "paginas": resultados_guardados
    }

@app.post("/quizzes/confirmar-resultado")
def confirmar_resultado(data: dict, db: Session = Depends(get_db)):
    """El profe confirma o corrige el apellido de un resultado."""
    resultado = db.query(Resultado).filter(Resultado.id == data["resultado_id"]).first()
    if not resultado:
        raise HTTPException(404)
    apellido = data["apellido_confirmado"]
    resultado.apellido_confirmado = apellido
    resultado.confirmado = True

    # Buscar estudiante por apellido en el curso
    quiz = db.query(Quiz).filter(Quiz.id == resultado.quiz_id).first()
    if quiz:
        ce = db.query(CursoEstudiante).filter(
            CursoEstudiante.curso_id == quiz.curso_id,
            CursoEstudiante.apellido_zipgrade.ilike(f"%{apellido}%")
        ).first()
        if ce:
            resultado.estudiante_id = ce.estudiante_id
            # Calcular nota si hay datos
            if data.get("correctas") and data.get("total"):
                resultado.correctas = data["correctas"]
                resultado.total = data["total"]
                resultado.nota = Decimal(str(round((data["correctas"] / data["total"]) * 5, 2)))

    db.commit()
    return {"ok": True, "apellido": apellido}

# ─── RESULTADOS ───────────────────────────────────────────────────────────────

@app.get("/resultados/historial/{estudiante_id}")
def historial_estudiante(estudiante_id: str, db: Session = Depends(get_db)):
    """
    Historial del estudiante.
    REGLA: Solo requiere que el ESTUDIANTE esté activo.
    El profe puede estar inactivo y el historial sigue disponible.
    """
    resultados = (
        db.query(Resultado)
        .filter(
            Resultado.estudiante_id == estudiante_id,
            Resultado.confirmado == True
        )
        .order_by(Resultado.created_at.desc())
        .all()
    )
    salida = []
    for r in resultados:
        quiz = r.quiz
        curso = quiz.curso if quiz else None
        salida.append({
            "id": str(r.id),
            "quiz_nombre": quiz.nombre if quiz else "—",
            "curso_nombre": curso.nombre if curso else "—",
            "fecha": str(quiz.fecha) if quiz else "—",
            "correctas": r.correctas,
            "total": r.total,
            "nota": str(r.nota) if r.nota else "0.0",
            "tiene_pdf": bool(r.pdf_url)
        })
    return salida

@app.get("/resultados/{resultado_id}")
def get_resultado(resultado_id: str, db: Session = Depends(get_db)):
    r = db.query(Resultado).filter(Resultado.id == resultado_id).first()
    if not r:
        raise HTTPException(404)
    quiz = r.quiz
    curso = quiz.curso if quiz else None
    return {
        "id": str(r.id),
        "quiz_nombre": quiz.nombre if quiz else "—",
        "curso_nombre": curso.nombre if curso else "—",
        "fecha": str(quiz.fecha) if quiz else "—",
        "correctas": r.correctas,
        "total": r.total,
        "nota": str(r.nota) if r.nota else "0.0"
    }

@app.get("/resultados/{resultado_id}/url-pdf")
def get_url_pdf(resultado_id: str, db: Session = Depends(get_db)):
    r = db.query(Resultado).filter(Resultado.id == resultado_id).first()
    if not r or not r.pdf_url:
        raise HTTPException(404)
    url = generar_url_temporal(r.pdf_url, segundos=3600)
    return {"url": url}

# ─── ADMIN - SUSCRIPCIONES ────────────────────────────────────────────────────

@app.post("/admin/activar-profe")
def admin_activar_profe(data: dict, db: Session = Depends(get_db)):
    profe = activar_profe(db, data["telegram_id"], data.get("meses", 1))
    if not profe:
        raise HTTPException(404, "Profe no encontrado")
    registrar_pago(db, "profe", str(profe.id), data.get("monto", 0), data.get("meses", 1), data.get("metodo", "manual"))
    return {"ok": True, "activo_hasta": str(profe.suscripcion_hasta)}

@app.post("/admin/activar-estudiante")
def admin_activar_estudiante(data: dict, db: Session = Depends(get_db)):
    est = activar_estudiante(db, data["telegram_id"], data.get("meses", 1))
    if not est:
        raise HTTPException(404, "Estudiante no encontrado")
    registrar_pago(db, "estudiante", str(est.id), data.get("monto", 0), data.get("meses", 1), data.get("metodo", "manual"))
    return {"ok": True, "activo_hasta": str(est.suscripcion_hasta)}

@app.post("/admin/desactivar-profe")
def admin_desactivar_profe(data: dict, db: Session = Depends(get_db)):
    desactivar_profe(db, data["telegram_id"])
    return {"ok": True}

@app.post("/admin/desactivar-estudiante")
def admin_desactivar_estudiante(data: dict, db: Session = Depends(get_db)):
    desactivar_estudiante(db, data["telegram_id"])
    return {"ok": True}

@app.get("/admin/usuarios")
def listar_usuarios(db: Session = Depends(get_db)):
    profes = db.query(Profe).all()
    estudiantes = db.query(Estudiante).all()
    return {
        "profes": [{"id": str(p.id), "nombre": p.nombre, "telegram_id": p.telegram_id, "activo": p.activo, "suscripcion_hasta": str(p.suscripcion_hasta)} for p in profes],
        "estudiantes": [{"id": str(e.id), "nombre": e.nombre, "apellido": e.apellido, "telegram_id": e.telegram_id, "activo": e.activo, "suscripcion_hasta": str(e.suscripcion_hasta)} for e in estudiantes]
    }
