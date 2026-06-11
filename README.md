# ZipGrade System

Sistema de automatización de resultados con chatbots de Telegram para profes y estudiantes.

## Arquitectura

- **Backend:** FastAPI + PostgreSQL
- **Almacenamiento PDFs:** Cloudflare R2
- **OCR:** Claude Vision API
- **Chatbots:** Telegram (uno para profes, uno para estudiantes)
- **Servidor:** Railway (recomendado)

## Reglas de acceso

| Situación | Profe puede subir | Estudiante ve historial |
|---|---|---|
| Profe activo + Estudiante activo | ✅ | ✅ |
| Profe inactivo + Estudiante activo | ❌ | ✅ (historial ya guardado) |
| Profe activo + Estudiante inactivo | ✅ | ❌ |
| Ambos inactivos | ❌ | ❌ |

## Instalación local

```bash
# 1. Clonar y entrar al proyecto
cd zipgrade_system

# 2. Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales

# 5. Crear base de datos
psql -U postgres -c "CREATE DATABASE zipgrade_db;"
psql -U postgres -d zipgrade_db -f migrations/schema.sql

# 6. Iniciar el backend
uvicorn backend.main:app --reload --port 8000

# 7. Iniciar bot del profe (en otra terminal)
python -m bot_profe.bot_profe

# 8. Iniciar bot del estudiante (en otra terminal)
python -m bot_estudiante.bot_estudiante
```

## Despliegue en Railway

1. Crear cuenta en railway.app
2. Crear nuevo proyecto → Deploy from GitHub
3. Agregar servicio PostgreSQL
4. Configurar variables de entorno en el panel
5. El sistema queda en línea 24/7

## Crear bots de Telegram

1. Abrir Telegram y buscar @BotFather
2. Escribir `/newbot`
3. Darle un nombre al bot del profe (ej: ZipGrade Profe)
4. Darle un username (ej: zipgrade_profe_bot)
5. Copiar el token al .env como BOT_PROFE_TOKEN
6. Repetir para el bot del estudiante

## Gestión de suscripciones (endpoints admin)

### Activar profe
```bash
curl -X POST http://tu-servidor/admin/activar-profe \
  -H "Content-Type: application/json" \
  -d '{"telegram_id": 123456789, "meses": 1, "monto": 25000, "metodo": "nequi"}'
```

### Activar estudiante
```bash
curl -X POST http://tu-servidor/admin/activar-estudiante \
  -H "Content-Type: application/json" \
  -d '{"telegram_id": 987654321, "meses": 1, "monto": 10000, "metodo": "nequi"}'
```

### Desactivar profe (no pago)
```bash
curl -X POST http://tu-servidor/admin/desactivar-profe \
  -H "Content-Type: application/json" \
  -d '{"telegram_id": 123456789}'
```

### Ver todos los usuarios
```bash
curl http://tu-servidor/admin/usuarios
```

## Flujo del profe

1. `/start` → se registra
2. `/micursos` → crea sus cursos
3. `/subirquiz` → selecciona curso, da nombre al quiz, sube el PDF
4. El sistema separa el PDF página por página
5. Claude Vision lee el apellido de cada hoja
6. El profe revisa y confirma/corrige uno por uno
7. Los PDFs individuales quedan disponibles para los estudiantes

## Flujo del estudiante

1. `/start` → se registra con nombre y apellido
2. `/misnotas` → ve su historial completo por curso
3. Toca el botón de cada quiz para ver detalles y descargar su PDF
4. El historial siempre está disponible mientras su suscripción esté activa

## Estructura del proyecto

```
zipgrade_system/
├── backend/
│   ├── main.py              # API FastAPI
│   ├── config.py            # Configuración
│   ├── models/
│   │   └── models.py        # Modelos SQLAlchemy
│   └── services/
│       ├── pdf_service.py   # Separar PDF + OCR con Claude
│       ├── storage_service.py # Cloudflare R2
│       └── suscripcion_service.py # Control de acceso
├── bot_profe/
│   └── bot_profe.py         # Bot de Telegram para profes
├── bot_estudiante/
│   └── bot_estudiante.py    # Bot de Telegram para estudiantes
├── migrations/
│   └── schema.sql           # Esquema PostgreSQL
├── requirements.txt
└── .env.example
```
