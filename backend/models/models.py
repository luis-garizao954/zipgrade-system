import uuid
from sqlalchemy import Column, String, Boolean, Float, ForeignKey, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID  # <-- IMPORTANTE PARA POSTGRES
from sqlalchemy.ext.declarative import declarative_base
import datetime

Base = declarative_base()

class Profe(Base):
    __tablename__ = "profes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id = Column(Integer, unique=True, nullable=False)
    nombre = Column(String, nullable=False)
    email = Column(String, default="")
    activo = Column(Boolean, default=False)

class Estudiante(Base):
    __tablename__ = "estudiantes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id = Column(Integer, unique=True, nullable=False)
    nombre = Column(String, nullable=False)
    apellido = Column(String, default="")
    activo = Column(Boolean, default=False)

class Curso(Base):
    __tablename__ = "cursos"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profe_id = Column(UUID(as_uuid=True), ForeignKey("profes.id"))
    nombre = Column(String, nullable=False)
    grado = Column(String, default="")

class CursoEstudiante(Base):
    __tablename__ = "curso_estudiantes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    curso_id = Column(UUID(as_uuid=True), ForeignKey("cursos.id"))
    estudiante_id = Column(UUID(as_uuid=True), ForeignKey("estudiantes.id"))

class Quiz(Base):
    __tablename__ = "quizzes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    curso_id = Column(UUID(as_uuid=True), ForeignKey("cursos.id"))
    nombre = Column(String, nullable=False)

class Resultado(Base):
    __tablename__ = "resultados"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id = Column(UUID(as_uuid=True), ForeignKey("quizzes.id"))
    estudiante_id = Column(UUID(as_uuid=True), ForeignKey("estudiantes.id"))
    nota = Column(Float, nullable=False)
    porcentaje = Column(Float, default=0.0)
    confirmado = Column(Boolean, default=False)

class MensajeGrupo(Base):
    __tablename__ = "mensaje_grupos"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    curso_id = Column(UUID(as_uuid=True), ForeignKey("cursos.id"), nullable=False)  # <-- CORREGIDO A UUID
    remitente_nombre = Column(String, nullable=False)
    tipo_mensaje = Column(String, nullable=False)
    texto = Column(String, nullable=True)
    file_id = Column(String, nullable=True)
    caption = Column(String, nullable=True)
    fecha_envio = Column(DateTime, default=datetime.datetime.utcnow)