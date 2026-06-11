from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from backend.models.models import Profe, Estudiante, Pago
import uuid

# ─── VERIFICACIÓN DE ACCESO ───────────────────────────────────────────────────

def profe_activo(db: Session, telegram_id: int) -> bool:
    """Verifica si el profe tiene suscripción vigente."""
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if not profe or not profe.activo:
        return False
    if profe.suscripcion_hasta and profe.suscripcion_hasta < datetime.now():
        # Suscripción vencida: desactivar
        profe.activo = False
        db.commit()
        return False
    return True

def estudiante_activo(db: Session, telegram_id: int) -> bool:
    """Verifica si el estudiante tiene suscripción vigente."""
    est = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
    if not est or not est.activo:
        return False
    if est.suscripcion_hasta and est.suscripcion_hasta < datetime.now():
        est.activo = False
        db.commit()
        return False
    return True

def profe_del_curso_activo(db: Session, curso_id: str) -> bool:
    """
    Regla clave: el estudiante puede ver su historial aunque el profe
    no esté activo. Solo verifica si el ESTUDIANTE está activo.
    Esta función se usa para saber si se pueden subir nuevos quizzes.
    """
    from backend.models.models import Curso
    curso = db.query(Curso).filter(Curso.id == curso_id).first()
    if not curso:
        return False
    profe = db.query(Profe).filter(Profe.id == curso.profe_id).first()
    return profe and profe.activo

# ─── ACTIVACIÓN / DESACTIVACIÓN ───────────────────────────────────────────────

def activar_profe(db: Session, telegram_id: int, meses: int = 1):
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if not profe:
        return None
    ahora = datetime.now()
    base = profe.suscripcion_hasta if (profe.suscripcion_hasta and profe.suscripcion_hasta > ahora) else ahora
    profe.suscripcion_hasta = base + timedelta(days=30 * meses)
    profe.activo = True
    db.commit()
    return profe

def activar_estudiante(db: Session, telegram_id: int, meses: int = 1):
    est = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
    if not est:
        return None
    ahora = datetime.now()
    base = est.suscripcion_hasta if (est.suscripcion_hasta and est.suscripcion_hasta > ahora) else ahora
    est.suscripcion_hasta = base + timedelta(days=30 * meses)
    est.activo = True
    db.commit()
    return est

def desactivar_profe(db: Session, telegram_id: int):
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if profe:
        profe.activo = False
        profe.suscripcion_hasta = datetime.now()
        db.commit()
    return profe

def desactivar_estudiante(db: Session, telegram_id: int):
    est = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
    if est:
        est.activo = False
        est.suscripcion_hasta = datetime.now()
        db.commit()
    return est

def registrar_pago(db: Session, tipo: str, referencia_id: str, monto: float, meses: int, metodo: str):
    pago = Pago(
        tipo=tipo,
        referencia_id=referencia_id,
        monto=monto,
        meses=meses,
        metodo=metodo
    )
    db.add(pago)
    db.commit()
    return pago
