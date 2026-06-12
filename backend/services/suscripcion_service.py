from datetime import datetime
from sqlalchemy.orm import Session
from backend.models.models import Profe, Estudiante

def profe_activo(telegram_id: int, db: Session) -> bool:
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if not profe or not profe.activo:
        return False
    return True

def estudiante_activo(telegram_id: int, db: Session) -> bool:
    est = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
    if not est or not est.activo:
        return False
    return True

def activar_profe(telegram_id: int, db: Session):
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if profe:
        profe.activo = True
        db.commit()

def desactivar_profe(telegram_id: int, db: Session):
    profe = db.query(Profe).filter(Profe.telegram_id == telegram_id).first()
    if profe:
        profe.activo = False
        db.commit()

def activar_estudiante(telegram_id: int, db: Session):
    est = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
    if est:
        est.activo = True
        db.commit()

def desactivar_estudiante(telegram_id: int, db: Session):
    est = db.query(Estudiante).filter(Estudiante.telegram_id == telegram_id).first()
    if est:
        est.activo = False
        db.commit()

def registrar_pago(telegram_id: int, db: Session):
    pass