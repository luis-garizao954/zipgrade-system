from sqlalchemy import Column, Boolean, DateTime, Integer, Numeric, Date, ForeignKey, BigInteger, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()

class Profe(Base):
    __tablename__ = "profes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    nombre = Column(Text, nullable=False)
    email = Column(Text)
    activo = Column(Boolean, default=False)
    suscripcion_hasta = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    cursos = relationship("Curso", back_populates="profe", cascade="all, delete")

class Estudiante(Base):
    __tablename__ = "estudiantes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    nombre = Column(Text, nullable=False)
    apellido = Column(Text, default="")
    activo = Column(Boolean, default=False)
    suscripcion_hasta = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

class Curso(Base):
    __tablename__ = "cursos"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profe_id = Column(UUID(as_uuid=True), ForeignKey("profes.id", ondelete="CASCADE"))
    nombre = Column(Text, nullable=False)
    grado = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    profe = relationship("Profe", back_populates="cursos")

class CursoEstudiante(Base):
    __tablename__ = "curso_estudiantes"
    curso_id = Column(UUID(as_uuid=True), ForeignKey("cursos.id", ondelete="CASCADE"), primary_key=True)
    estudiante_id = Column(UUID(as_uuid=True), ForeignKey("estudiantes.id", ondelete="CASCADE"), primary_key=True)

class Quiz(Base):
    __tablename__ = "quizzes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    curso_id = Column(UUID(as_uuid=True), ForeignKey("cursos.id", ondelete="CASCADE"))
    nombre = Column(Text, nullable=False)
    fecha = Column(Date, server_default=func.current_date())
    total_preguntas = Column(Integer, default=20)
    created_at = Column(DateTime, server_default=func.now())

class Resultado(Base):
    __tablename__ = "resultados"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id = Column(UUID(as_uuid=True), nullable=True)
    estudiante_id = Column(UUID(as_uuid=True), nullable=True)
    nombre_temp = Column(Text)
    nota = Column(Numeric(4, 2))
    puntos = Column(Numeric(6, 2))
    posibles = Column(Numeric(6, 2))
    porcentaje = Column(Numeric(5, 2))
    pagina = Column(Integer)
    confirmado = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())