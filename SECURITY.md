# Security

> YouTube ya **NO requiere API key** (usamos feeds RSS públicos). Solo necesitas la key de OpenAI.

El proyecto corre en la nube. En producción **los secretos viven solo en GitHub
Actions** (cifrados, no se pueden volver a leer). El `.env` local es solo para
desarrollo. Reglas:

| Secreto | Dónde vive | Notas |
| --- | --- | --- |
| `OPENAI_API_KEY` | GitHub Actions secret (+ `.env` local) | key de Project con budget mensual |
| `DATABASE_URL` / `SYNC_DATABASE_URL` | GitHub Actions secret | Neon; nunca en repo |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `LINKEDIN_DRAFT_CHAT_ID` | GitHub Actions secret | bot admin **solo "post messages"**; el chat id no es sensible |
| `PAGES_TOKEN` | GitHub Actions secret | PAT fine-grained, `Contents: read+write` solo en el repo del portfolio |
| `BREVO_API_KEY` / `BREVO_LIST_ID` | GitHub Actions secret | newsletter por API; el list id no es sensible |
| `EMAIL_FROM` (+ `EMAIL_HOST`/`USER`/`PASSWORD`/`TO` si SMTP) | GitHub Actions secret | remitente verificado / fallback SMTP |

- Las migraciones y escrituras contra la BBDD cloud corren **solo dentro de Actions**.
- El bot de Telegram es admin con **solo** permiso de publicar: borrar/banear/añadir-admins/editar-info **OFF**. Un token filtrado solo podría spamear, no destruir.
- **Brevo**: la restricción "IPs autorizadas → para claves API" está **desactivada** (los runners de Actions usan IPs dinámicas no whitelistables). La defensa es que la API key vive solo en Secrets y es rotable; el daño máximo de una fuga = enviar emails/leer contactos, capado por el límite del plan. El formulario de la web NO expone la key (POST a `sibforms.com/serve`, no a la API).
- Defensa contra prompt-injection en cada llamada LLM (sanitize + `INJECTION_GUARD` + validación de enums) — ver `ARCHITECTURE.md` §9.

---

## Defensa local en 3 pasos (desarrollo)

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
cd C:\Users\Msonero\GitHub\ai-news-engine
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
cd C:\Users\Msonero\GitHub\ai-news-engine
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
2. **Telegram** (si se filtra el token): @BotFather → `/revoke` → genera nuevo token
3. Genera la nueva key/token, actualiza el **GitHub Actions secret** (Settings → Secrets and variables → Actions) y el `.env` local. El próximo run la usa automáticamente.
4. Mira el dashboard de uso por actividad anómala las próximas 24h

Tiempo desde detección hasta cerrada: <2 minutos.
