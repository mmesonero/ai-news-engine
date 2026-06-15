# Security — setup en 3 pasos

> YouTube ya **NO requiere API key** (usamos feeds RSS públicos). Solo necesitas la key de OpenAI.

Estas 3 capas cubren el 95% del riesgo real de filtración. Total: ~10 min.

---

## 1. Crear OpenAI key con presupuesto (5 min)

1. Entra a https://platform.openai.com/api-keys
2. Arriba a la izquierda, **crea un Project nuevo** llamado `ai-news-engine`
3. Dentro del project: **Settings → Limits → set monthly budget** (recomendado: $20/mes)
4. Vuelve a **API keys → Create new secret key**
   - **Owned by**: `Project` (no User)
   - **Project**: el que acabas de crear
   - **Permissions**: solo `Model capabilities` (Chat + Embeddings)
5. Copia la key, la pegas en `.env`

**Qué te cubre:** Si se filtra, el daño máximo está capado al budget del project. Tu cuenta personal y otros projects no se tocan.

---

## 2. Bloquear el archivo `.env` (1 min)

Copia el template y bloquéalo:

```powershell
cd C:\Users\Msonero\ai-news-engine
copy .env.example .env
# edita .env con notepad y pega tus keys
notepad .env
# bloquea permisos
powershell -ExecutionPolicy Bypass -File scripts\lock_env.ps1
```

**Qué te cubre:** Solo tu usuario Windows puede leer el archivo. Otros procesos / usuarios del PC no.

---

## 3. Pre-commit hook (5 min, una sola vez)

Esto hace que **git rechace** cualquier commit que contenga algo con pinta de API key, aunque te despistes.

```powershell
pip install pre-commit
cd C:\Users\Msonero\ai-news-engine
pre-commit install
```

Verifica que funciona:
```powershell
pre-commit run --all-files
```

A partir de ahora cada `git commit` corre gitleaks automático. Si detecta `sk-...`, `AIza...`, AWS key, JWT, etc → commit abortado con mensaje claro.

**Qué te cubre:** Filtración por error humano — pegas una key en código de prueba y se te olvida quitarla. Es el caso más frecuente de leaks reales.

---

## Verificación rápida — que todo esté bien

```powershell
# 1. .env existe y NO va a git
git check-ignore .env
# debe imprimir: .env

# 2. .env tiene tus keys reales
type .env | findstr OPENAI_API_KEY
# debe mostrar tu key, NO "sk-replace-me"

# 3. pre-commit instalado
pre-commit --version

# 4. hook activo en este repo
type .git\hooks\pre-commit | findstr pre-commit
# debe mostrar texto
```

---

## Reglas día a día

- ❌ Nunca pegues `.env` en Slack/email/Notion
- ❌ Nunca pongas keys directamente en código aunque sea "5 min de prueba"
- ❌ Nunca uses la misma key en dev y prod
- ✅ Rota las keys cada 90 días (regenera + actualiza `.env`)
- ✅ Si sospechas filtración: revoca inmediatamente desde el dashboard de OpenAI/Google

---

## Si una key se filtra

**Pasos en orden:**

1. **OpenAI**: https://platform.openai.com/api-keys → click la key → `Revoke`
2. **YouTube**: Google Cloud Console → Credentials → key → `Delete`
3. Genera nueva, actualiza `.env`, reinicia: `docker compose restart api`
4. Mira el dashboard de uso por actividad anómala las próximas 24h

Tiempo desde detección hasta cerrada: <2 minutos.
