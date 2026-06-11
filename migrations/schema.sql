-- =============================================
-- SCHEMA PRINCIPAL - ZipGrade System
-- =============================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Profes
CREATE TABLE profes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    email TEXT UNIQUE,
    activo BOOLEAN DEFAULT FALSE,
    suscripcion_hasta TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Estudiantes
CREATE TABLE estudiantes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    apellido TEXT NOT NULL,
    activo BOOLEAN DEFAULT FALSE,
    suscripcion_hasta TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Cursos (un profe puede tener varios cursos)
CREATE TABLE cursos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    profe_id UUID REFERENCES profes(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    grado TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Relacion estudiante <-> curso
CREATE TABLE curso_estudiantes (
    curso_id UUID REFERENCES cursos(id) ON DELETE CASCADE,
    estudiante_id UUID REFERENCES estudiantes(id) ON DELETE CASCADE,
    apellido_zipgrade TEXT,
    PRIMARY KEY (curso_id, estudiante_id)
);

-- Quizzes subidos por el profe
CREATE TABLE quizzes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    curso_id UUID REFERENCES cursos(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    fecha DATE DEFAULT CURRENT_DATE,
    total_preguntas INTEGER DEFAULT 20,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Resultados individuales por estudiante
CREATE TABLE resultados (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    quiz_id UUID REFERENCES quizzes(id) ON DELETE CASCADE,
    estudiante_id UUID REFERENCES estudiantes(id),
    apellido_detectado TEXT,
    apellido_confirmado TEXT,
    correctas INTEGER,
    total INTEGER,
    nota DECIMAL(3,2),
    pdf_url TEXT,
    confirmado BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Pagos / suscripciones
CREATE TABLE pagos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tipo TEXT NOT NULL CHECK (tipo IN ('profe', 'estudiante')),
    referencia_id UUID NOT NULL,
    monto DECIMAL(10,2),
    meses INTEGER DEFAULT 1,
    fecha_pago TIMESTAMP DEFAULT NOW(),
    metodo TEXT
);

-- Indices
CREATE INDEX idx_resultados_estudiante ON resultados(estudiante_id);
CREATE INDEX idx_resultados_quiz ON resultados(quiz_id);
CREATE INDEX idx_curso_estudiantes_apellido ON curso_estudiantes(apellido_zipgrade);
CREATE INDEX idx_profes_telegram ON profes(telegram_id);
CREATE INDEX idx_estudiantes_telegram ON estudiantes(telegram_id);
