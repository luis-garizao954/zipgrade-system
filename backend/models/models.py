from sqlalchemy import Column, String, Boolean, DateTime, Integer, Numeric, Date, ForeignKey, BigInteger, Text
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
    email = Column(Text, unique=True)
    activo = Column(Boolean, default=False)
    suscripcion_hasta = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    cursos = relationship("Curso", back_populates="profe", cascade="all, delete")

class Estudiante(Base):
    __tablename__ = "estudiantes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    nombre = Column(Text, nullable=False)
    apellido = Column(Text, nullable=False)
    activo = Column(Boolean, default=False)
    suscripcion_hasta = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    resultados = relationship("Resultado", back_populates="estudiante")

class Curso(Base):
    __tablename__ = "cursos"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profe_id = Column(UUID(as_uuid=True), ForeignKey("profes.id", ondelete="CASCADE"))
    nombre = Column(Text, nullable=False)
    grado = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    profe = relationship("Profe", back_populates="cursos")
    quizzes = relationship("Quiz", back_populates="curso", cascade="all, delete")
    estudiantes = relationship("Estudiante", secondary="curso_estudiantes")

class CursoEstudiante(Base):
    __tablename__ = "curso_estudiantes"
    curso_id = Column(UUID(as_uuid=True), ForeignKey("cursos.id", ondelete="CASCADE"), primary_key=True)
    estudiante_id = Column(UUID(as_uuid=True), ForeignKey("estudiantes.id", ondelete="CASCADE"), primary_key=True)
    apellido_zipgrade = Column(Text)

class Quiz(Base):
    __tablename__ = "quizzes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    curso_id = Column(UUID(as_uuid=True), ForeignKey("cursos.id", ondelete="CASCADE"))
    nombre = Column(Text, nullable=False)
    fecha = Column(Date, server_default=func.current_date())
    total_preguntas = Column(Integer, default=20)
    created_at = Column(DateTime, server_default=func.now())
    curso = relationship("Curso", back_populates="quizzes")
    resultados = relationship("Resultado", back_populates="quiz", cascade="all, delete")

class Resultado(Base):
    __tablename__ = "resultados"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id = Column(UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE"))
    estudiante_id = Column(UUID(as_uuid=True), ForeignKey("estudiantes.id"))
    apellido_detectado = Column(Text)
    apellido_confirmado = Column(Text)
    correctas = Column(Integer)
    total = Column(Integer)
    nota = Column(Decimal(3, 2))
    pdf_url = Column(Text)
    confirmado = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    quiz = relationship("Quiz", back_populates="resultados")
    estudiante = relationship("Estudiante", back_populates="resultados")

class Pago(Base):
    __tablename__ = "pagos"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo = Column(Text, nullable=False)
    referencia_id = Column(UUID(as_uuid=True), nullable=False)
    monto = Column(Decimal(10, 2))
    meses = Column(Integer, default=1)
    fecha_pago = Column(DateTime, server_default=func.now())
    metodo = Column(Text)
