# Sophos V17 Enxuto – main.py

import os
import re
import json
import sys
import tempfile
import traceback
import unicodedata
import requests
from datetime import datetime, timedelta

import pandas as pd

from openai import OpenAI
import firebase_admin
from firebase_admin import credentials, db

from pinecone import Pinecone, ServerlessSpec

from telegram import (
    InputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Document,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

try:
    from PyPDF2 import PdfReader
except Exception:
    PdfReader = None

try:
    import docx
except Exception:
    docx = None

try:
    import pytesseract
    from PIL import Image
except Exception:
    pytesseract = None
    Image = None


# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

HISTORY_LIMIT = 6
SUMMARY_TRIGGER = 20
SUMMARY_KEY = "resumo_anterior"

MODEL_MAIN = os.environ.get("OPENAI_MODEL_MAIN", "gpt-5")
MODEL_FAST = os.environ.get("OPENAI_MODEL_FAST", "gpt-5-mini")
MODEL_EMBED = "text-embedding-3-small"

MAX_DOC_CHARS = 9000
MAX_TELEGRAM_CHARS = 3800

GATILHOS_MEMORIA = [
    "lembre", "guarde", "salve", "registre",
    "meu filho", "minha rotina", "meu objetivo",
    "eu costumo", "eu tomo", "eu treino",
    "trabalho com", "moro em", "prefiro",
    "a partir de agora", "daqui pra frente",
    "sempre que", "nunca"
]

ESTILO_SOPHOS = """
Você é o Sophos, assistente pessoal do usuário.

Estilo:
- direto, crítico, técnico, prático, coloquial e estoico;
- sem enrolação;
- tom firme, útil e encorajador;
- humor sagaz e emojis apenas quando fizer sentido.

Regras:
- Responda primeiro à dúvida principal.
- Use contexto antigo somente se houver relação clara.
- Evite conselhos genéricos.
- Em temas técnicos, traga números, riscos, trade-offs e veredito.
- Em listas, avalie item por item e conclua com manter, ajustar ou cortar.
- Seja franco, mas útil.
- Não puxe assuntos antigos sem necessidade.
- Priorize ação prática, clareza e decisão.
"""


# =============================================================================
# INICIALIZAÇÃO
# =============================================================================

TOKEN = os.environ.get("TOKEN_TELEGRAM")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
BOT_URL = os.environ.get("BOT_URL")

INTERVALS_API_KEY = os.environ.get("INTERVALS_API_KEY")
INTERVALS_ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")

FIREBASE_URL = os.environ.get(
    "FIREBASE_URL",
    "https://sophos-ddbed-default-rtdb.firebaseio.com"
)

if not TOKEN:
    raise RuntimeError("TOKEN_TELEGRAM não configurado.")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY não configurado.")
if not BOT_URL:
    raise RuntimeError("BOT_URL não configurado.")
if "FIREBASE_CRED_JSON" not in os.environ:
    raise RuntimeError("FIREBASE_CRED_JSON não configurado.")

client = OpenAI(api_key=OPENAI_API_KEY)

cred_dict = json.loads(os.environ["FIREBASE_CRED_JSON"])
cred = credentials.Certificate(cred_dict)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_URL})

ref = db.reference("/usuarios")

WEBHOOK_PATH = f"/{TOKEN}"
WEBHOOK_URL = f"{BOT_URL}{WEBHOOK_PATH}"

PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_ENVIRONMENT = os.environ.get("PINECONE_ENVIRONMENT")

vec_index = None

if PINECONE_API_KEY and PINECONE_ENVIRONMENT:
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index_name = "sophos-memoria"

    if index_name not in pc.list_indexes().names():
        pc.create_index(
            name=index_name,
            dimension=1536,
            metric="cosine",
            spec=ServerlessSpec(cloud="gcp", region=PINECONE_ENVIRONMENT)
        )

    vec_index = pc.Index(index_name)


# =============================================================================
# UTILITÁRIOS
# =============================================================================

def agora_iso():
    return datetime.now().isoformat()


def remover_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def dividir_texto(texto: str, limite: int = MAX_TELEGRAM_CHARS):
    partes = []

    texto = texto or ""

    while len(texto) > limite:
        corte = texto.rfind("\n", 0, limite)
        if corte == -1:
            corte = limite

        partes.append(texto[:corte].strip())
        texto = texto[corte:].strip()

    if texto:
        partes.append(texto)

    return partes


async def enviar_texto_longo(context, chat_id, texto, reply_markup=None):
    partes = dividir_texto(texto)

    for i, parte in enumerate(partes):
        markup = reply_markup if i == len(partes) - 1 else None
        await context.bot.send_message(
            chat_id=chat_id,
            text=parte,
            reply_markup=markup
        )


def chamar_gpt_sync(messages, model=MODEL_MAIN, max_tokens=None):
    kwargs = {
        "model": model,
        "messages": messages,
    }

    if max_tokens:
        kwargs["max_completion_tokens"] = max_tokens

    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def gerar_embedding(texto: str):
    resp = client.embeddings.create(
        model=MODEL_EMBED,
        input=texto[:8000]
    )
    return resp.data[0].embedding


def deve_extrair_memoria(texto: str) -> bool:
    t = texto.lower().strip()

    if len(t) < 40:
        return False

    return any(g in t for g in GATILHOS_MEMORIA)


def marcadores_feedback(tipo):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👍", callback_data=f"{tipo}:like"),
            InlineKeyboardButton("👎", callback_data=f"{tipo}:dislike"),
        ]
    ])


# =============================================================================
# FIREBASE / MEMÓRIA
# =============================================================================

def inicializar_usuario(user_id):
    user_ref = ref.child(str(user_id))

    if not user_ref.get():
        user_ref.set({"init": {"timestamp": agora_iso()}})

    for sub in ["contexto", "memoria", "feedback_respostas"]:
        if not user_ref.child(sub).get():
            user_ref.child(sub).set({})


def salvar_contexto(user_id, texto):
    contexto = ref.child(str(user_id)).child("contexto").get() or {}
    ultimos = [v.get("texto", "") for v in contexto.values() if isinstance(v, dict)]

    if ultimos and texto.strip() == ultimos[-1].strip():
        return

    ref.child(str(user_id)).child("contexto").push({
        "texto": texto,
        "data": agora_iso()
    })


def recuperar_contexto(user_id, limite=HISTORY_LIMIT):
    partes = []

    resumo_node = ref.child(str(user_id)).child(SUMMARY_KEY).get() or {}
    if resumo_node.get("texto"):
        partes.append(f"Resumo anterior: {resumo_node['texto']}")

    d = ref.child(str(user_id)).child("contexto").get() or {}
    ultimos = list(d.values())[-limite:]

    for item in ultimos:
        if isinstance(item, dict) and item.get("texto"):
            partes.append(f"Usuário: {item['texto']}")

    return "\n".join(partes)


def salvar_memoria_relativa(user_id, chave, valor):
    ref.child(str(user_id)).child("memoria").child(chave).set(valor)


def registrar_feedback(user_id, tipo_resposta, feedback, texto_resposta):
    ref.child(str(user_id)).child("feedback_respostas").push({
        "tipo": tipo_resposta,
        "feedback": feedback,
        "resposta": texto_resposta[:500],
        "data": agora_iso()
    })


def recuperar_feedback_counts(user_id):
    fb = ref.child(str(user_id)).child("feedback_respostas").get() or {}

    likes = 0
    dislikes = 0

    for e in fb.values():
        if not isinstance(e, dict):
            continue
        if e.get("feedback") == "like":
            likes += 1
        elif e.get("feedback") == "dislike":
            dislikes += 1

    return likes, dislikes


def extrair_memoria_com_gpt(texto: str) -> dict:
    prompt = f"""
Extraia somente fatos úteis e duradouros para lembrar no futuro.

Regras:
- Retorne apenas JSON válido.
- Não inclua opiniões momentâneas.
- Não inclua frases triviais.
- Use chaves curtas.
- Se não houver nada importante, retorne {{}}.

Texto:
{texto}
"""

    try:
        content = chamar_gpt_sync(
            [{"role": "user", "content": prompt}],
            model=MODEL_FAST,
            max_tokens=500
        )
        return json.loads(content)
    except Exception:
        return {}


async def resumir_contexto_antigo(user_id):
    caminho = ref.child(str(user_id)).child("contexto")
    todas = caminho.get() or {}
    textos = [x.get("texto", "") for x in todas.values() if isinstance(x, dict)]

    if len(textos) <= SUMMARY_TRIGGER:
        return

    antigas = textos[:-HISTORY_LIMIT]

    prompt = (
        "Resuma o histórico abaixo em formato compacto, preservando fatos úteis, "
        "preferências, decisões e contexto recorrente. Não invente.\n\n"
        + "\n".join(antigas)
    )

    try:
        resumo = chamar_gpt_sync(
            [
                {"role": "system", "content": "Resuma com objetividade e sem floreios."},
                {"role": "user", "content": prompt}
            ],
            model=MODEL_FAST,
            max_tokens=900
        )

        ref.child(str(user_id)).child(SUMMARY_KEY).set({
            "texto": resumo,
            "data": agora_iso()
        })

        for key in list(todas.keys())[:-HISTORY_LIMIT]:
            caminho.child(key).delete()

    except Exception as e:
        print("Erro ao resumir contexto:", e)


async def buscar_contexto_semantico(user_id: int, texto: str, top_k: int = 5):
    if not vec_index:
        return []

    try:
        emb = gerar_embedding(texto)

        res = vec_index.query(
            vector=emb,
            top_k=top_k,
            include_metadata=True,
            filter={"user_id": {"$eq": str(user_id)}}
        )

        fragmentos = []

        for match in res.matches:
            md = match.metadata or {}
            chave = md.get("chave")
            valor = md.get("valor")

            if chave and valor:
                fragmentos.append(f"{chave}: {valor}")

        return fragmentos

    except Exception as e:
        print("Erro busca semântica:", e)
        return []


def salvar_memoria_e_indexar(user_id, memoria_nova: dict):
    if not memoria_nova:
        return

    for chave, valor in memoria_nova.items():
        if not chave or valor in [None, ""]:
            continue

        chave = str(chave).strip()[:80]
        valor = str(valor).strip()[:1000]

        atual = ref.child(str(user_id)).child("memoria").child(chave).get()

        if atual == valor:
            continue

        salvar_memoria_relativa(user_id, chave, valor)

        if vec_index:
            try:
                texto_emb = f"{chave}: {valor}"
                emb = gerar_embedding(texto_emb)
                chave_ascii = remover_acentos(chave).replace(" ", "_")

                vec_index.upsert([
                    {
                        "id": f"{user_id}:{chave_ascii}",
                        "values": emb,
                        "metadata": {
                            "user_id": str(user_id),
                            "chave": chave,
                            "valor": valor
                        }
                    }
                ])

            except Exception as e:
                print("Erro ao indexar memória:", e)


# =============================================================================
# INTERVALS.ICU - RELATÓRIO
# =============================================================================

def normalizar_data_br(data_str):
    data_str = data_str.strip()
    formatos = ["%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"]

    for fmt in formatos:
        try:
            return datetime.strptime(data_str, fmt).date()
        except ValueError:
            pass

    raise ValueError(f"Data inválida: {data_str}")


def coletar_intervals(dias=7, inicio=None, fim=None):
    hoje = datetime.now().date()

    if inicio and fim:
        inicio = normalizar_data_br(inicio) if isinstance(inicio, str) else inicio
        fim = normalizar_data_br(fim) if isinstance(fim, str) else fim
    else:
        fim = hoje
        inicio = hoje - timedelta(days=dias)

    if fim < inicio:
        raise ValueError("Data final menor que data inicial.")

    auth = ("API_KEY", INTERVALS_API_KEY)
    base = f"https://intervals.icu/api/v1/athlete/{INTERVALS_ATHLETE_ID}"

    newest_api = fim + timedelta(days=1)

    ativ_resp = requests.get(
        f"{base}/activities",
        params={
            "oldest": inicio.isoformat(),
            "newest": newest_api.isoformat()
        },
        auth=auth,
        timeout=30
    )

    ativ_resp.raise_for_status()
    ativ = ativ_resp.json()

    if isinstance(ativ, dict):
        ativ = list(ativ.values())

    treinos = []

    for a in ativ:
        data_local = (a.get("start_date_local") or "")[:10]

        try:
            data_treino = datetime.fromisoformat(data_local).date()
            if data_treino < inicio or data_treino > fim:
                continue
        except Exception:
            pass

        vel = a.get("average_speed")

        treinos.append({
            "tipo": a.get("type"),
            "nome": a.get("name"),
            "data": data_local,
            "data_hora": a.get("start_date_local"),
            "dist_km": round((a.get("distance") or 0) / 1000, 2),
            "dur_min": round((a.get("moving_time") or 0) / 60, 1),
            "fc_med": a.get("average_heartrate"),
            "fc_max": a.get("max_heartrate"),
            "pace_min_km": round(1000 / vel / 60, 2) if vel else None,
            "potencia_w": a.get("icu_average_watts"),
            "elev_m": round(a.get("total_elevation_gain") or 0),
            "cadencia": a.get("average_cadence"),
            "carga_treino": a.get("icu_training_load"),
            "intensidade": a.get("icu_intensity"),
            "trimp": a.get("trimp"),
            "cal": a.get("calories"),
        })

    def soma_tipo(chave):
        return round(sum(
            (t.get("dist_km") or 0) * 1000 for t in treinos
            if chave in (t.get("tipo") or "").lower()
        ))

    totais = {
        "natacao_m": soma_tipo("swim"),
        "bike_km": round(soma_tipo("ride") / 1000, 1),
        "corrida_km": round(soma_tipo("run") / 1000, 1),
        "calorias": round(sum(t.get("cal") or 0 for t in treinos)),
        "carga_total": round(sum(t.get("carga_treino") or 0 for t in treinos)),
        "total_sessoes": len(treinos),
    }

    wel_resp = requests.get(
        f"{base}/wellness",
        params={
            "oldest": inicio.isoformat(),
            "newest": newest_api.isoformat()
        },
        auth=auth,
        timeout=30
    )

    wel_resp.raise_for_status()
    wel = wel_resp.json()

    if isinstance(wel, dict):
        wel = list(wel.values())

    wel_filtrado = []

    for w in wel:
        data_w = w.get("id") or w.get("date") or w.get("day")

        if not data_w:
            wel_filtrado.append(w)
            continue

        try:
            data_w_date = datetime.fromisoformat(str(data_w)[:10]).date()
            if inicio <= data_w_date <= fim:
                wel_filtrado.append(w)
        except Exception:
            wel_filtrado.append(w)

    wel = wel_filtrado

    def media(campo, transform=lambda x: x):
        vals = []

        for w in wel:
            valor = w.get(campo)

            if valor is not None:
                try:
                    vals.append(transform(valor))
                except Exception:
                    pass

        return round(sum(vals) / len(vals), 1) if vals else None

    ultimo = next((w for w in reversed(wel) if w.get("ctl") is not None), {})
    primeiro = next((w for w in wel if w.get("ctl") is not None), {})

    condicionamento = {
        "fitness_ctl": round(ultimo.get("ctl") or 0, 1),
        "fadiga_atl": round(ultimo.get("atl") or 0, 1),
        "forma_tsb": round((ultimo.get("ctl") or 0) - (ultimo.get("atl") or 0), 1),
        "vo2max": ultimo.get("vo2max"),
        "tendencia_fitness": round((ultimo.get("ctl") or 0) - (primeiro.get("ctl") or 0), 1),
    }

    recuperacao = {
        "hrv_medio": media("hrv"),
        "rhr_medio": media("restingHR"),
        "sono_medio_h": media("sleepSecs", lambda s: s / 3600),
        "sono_score_medio": media("sleepScore"),
        "readiness_medio": media("readiness"),
        "peso_medio": media("weight"),
    }

    return {
        "periodo": f"{inicio.isoformat()} a {fim.isoformat()}",
        "dias": (fim - inicio).days + 1,
        "totais": totais,
        "treinos": treinos,
        "condicionamento": condicionamento,
        "recuperacao": recuperacao,
    }


async def relatorio_command(update, context):
    uid = update.effective_user.id

    dias = 7
    inicio = None
    fim = None

    args = context.args

    if args:
        texto_args = (
            " ".join(args)
            .replace(" até ", " ")
            .replace(" a ", " ")
            .replace("-", " ")
        )

        partes = [p.strip() for p in texto_args.split() if p.strip()]
        datas = []

        for p in partes:
            try:
                normalizar_data_br(p)
                datas.append(p)
            except ValueError:
                pass

        if len(datas) >= 2:
            inicio = datas[0]
            fim = datas[1]
        else:
            try:
                dias = int(args[0])
            except ValueError:
                await context.bot.send_message(
                    update.effective_chat.id,
                    "Formato inválido. Use:\n/relatorio 7\nou\n/relatorio 25/05/26 31/05/26"
                )
                return

    msg_status = (
        f"📊 Gerando relatório de {inicio} a {fim}..."
        if inicio and fim
        else f"📊 Gerando relatório completo ({dias} dias)..."
    )

    await context.bot.send_message(update.effective_chat.id, msg_status)

    try:
        d = coletar_intervals(dias=dias, inicio=inicio, fim=fim)
    except Exception as e:
        print("Erro relatorio:", e)
        await context.bot.send_message(
            update.effective_chat.id,
            "⚠️ Falha ao coletar dados do Intervals.icu. Verifique API Key e Athlete ID."
        )
        return

    prompt = f"""
Você é coach de endurance e cientista de dados de performance. Não utilize: ** -- ## Markdown, utilize apenas texto puro para não consumir o limite de caracteres do telegram, ou seja, ajuste o relatório para no máximo 4000 caracteres, incluso quebra de linhas, botões de feedback, emojis e eventuais caracteres invisiveis. 
Analise meus dados do período {d['periodo']}.

DADOS COMPLETOS:
{json.dumps(d, ensure_ascii=False, default=str)}

Contexto técnico das métricas:
- fitness_ctl = condicionamento crônico (quanto maior, mais fit)
- fadiga_atl = fadiga aguda recente
- forma_tsb = forma (CTL menos ATL; positivo = descansado, negativo = sobrecarregado)
- carga_treino = training load por sessão

Estruture a resposta assim:

📊 NÚMEROS DA SEMANA
— volume por modalidade, carga total, sessões

🔗 CORRELAÇÕES
— relação entre HRV/sono/readiness e qualidade dos treinos
— padrões que se repetem

🧠 CONDICIONAMENTO
— leitura de fitness (CTL), fadiga (ATL) e forma (TSB) em linguagem simples
— tendência: estou ganhando ou perdendo condicionamento?

⚠️ PONTO DE ATENÇÃO
— maior risco (overtraining/subtreino) ou oportunidade

🎯 RECOMENDAÇÃO
— ajuste prático para a próxima semana

IMPORTANTE:

A resposta deve ter no máximo 4000 caracteres.

Remova:
- repetições
- explicações redundantes
- frases motivacionais
- contextualizações longas

Se duas frases transmitirem a mesma informação, mantenha apenas a mais objetiva.

Utilize linguagem executiva e direta, semelhante a um dashboard de performance.

Evite narrativas longas.
Evite repetir conclusões em seções diferentes.
Cada insight deve aparecer apenas uma vez.
"""

    resposta = chamar_gpt_sync(
        [
            {"role": "system", "content": ESTILO_SOPHOS},
            {"role": "user", "content": prompt}
        ],
        model=MODEL_MAIN,
        max_tokens=1500
    )

    context.user_data["ultima_resposta"] = resposta

    await context.bot.send_message(
        update.effective_chat.id,
        "📊 Relatório de Performance:\n\n" + resposta,
        reply_markup=marcadores_feedback("relatorio")
    )


# =============================================================================
# COMANDOS
# =============================================================================

async def start(update, context):
    uid = update.effective_user.id
    inicializar_usuario(uid)

    await context.bot.send_message(
        update.effective_chat.id,
        "👋 Sophos online. Envie uma mensagem, áudio, arquivo ou use /relatorio."
    )


async def comandos(update, context):
    msg = (
        "📌 Comandos disponíveis:\n"
        "/start — iniciar\n"
        "/relatorio <dias> — relatório de performance\n"
        "/relatorio 25/05/26 31/05/26 — relatório por período\n"
        "/processar_arquivo <instrução> — processar último arquivo pendente\n"
        "/comandos — mostrar menu"
    )

    await context.bot.send_message(update.effective_chat.id, msg)


# =============================================================================
# FEEDBACK
# =============================================================================

async def feedback_handler(update, context):
    q = update.callback_query
    await q.answer()

    try:
        typ, fb = q.data.split(":", 1)
    except ValueError:
        await q.message.reply_text("⚠️ Feedback mal formatado.")
        return

    uid = q.from_user.id
    tx = context.user_data.get("ultima_resposta", "")

    registrar_feedback(uid, typ, fb, tx)

    try:
        await q.edit_message_reply_markup(None)
    except Exception:
        pass

    await q.message.reply_text("✅ Feedback registrado.")


# =============================================================================
# VOZ
# =============================================================================

async def voz(update, context):
    uid = update.effective_user.id
    f = await update.message.voice.get_file()

    path = f"voz_{uid}.ogg"

    try:
        await f.download_to_drive(path)

        with open(path, "rb") as af:
            tr = client.audio.transcriptions.create(
                model="whisper-1",
                file=af
            )

        texto = tr.text or ""

        await context.bot.send_message(update.effective_chat.id, f"🗣️ Você disse: {texto}")
        await processar_texto(uid, texto, update, context)

    except Exception as e:
        print("Erro voz:", e)
        await context.bot.send_message(update.effective_chat.id, "⚠️ Erro ao transcrever áudio.")

    finally:
        try:
            os.remove(path)
        except Exception:
            pass


# =============================================================================
# PROCESSAMENTO PRINCIPAL
# =============================================================================

async def processar_texto(user_id, texto, update, context):
    inicializar_usuario(user_id)

    texto_original = texto.strip()

    await resumir_contexto_antigo(user_id)

    salvar_contexto(user_id, texto_original)

    if deve_extrair_memoria(texto_original):
        memoria_nova = extrair_memoria_com_gpt(texto_original)
        salvar_memoria_e_indexar(user_id, memoria_nova)

    likes, dislikes = recuperar_feedback_counts(user_id)

    estilo_dinamico = None

    if likes > dislikes + 5:
        estilo_dinamico = "Prefira respostas mais sucintas e diretas."
    elif dislikes > likes + 5:
        estilo_dinamico = "Adote tom mais explicativo e didático."

    base = recuperar_contexto(user_id)

    sem_ctx = await buscar_contexto_semantico(user_id, texto_original, top_k=5)

    if sem_ctx:
        base += "\n\nMemórias relevantes:\n" + "\n".join(f"- {m}" for m in sem_ctx)

    prompt = f"""
Contexto útil:
{base}

Mensagem atual do usuário:
{texto_original}
"""

    messages = [
        {"role": "system", "content": ESTILO_SOPHOS}
    ]

    if estilo_dinamico:
        messages.append({"role": "system", "content": estilo_dinamico})

    messages.append({"role": "user", "content": prompt})

    try:
        r = chamar_gpt_sync(messages, model=MODEL_MAIN)
    except Exception as e:
        print("❌ Erro OpenAI:", str(e))
        r = "⚠️ Erro ao gerar resposta. Tente novamente mais tarde."

    context.user_data["ultima_resposta"] = r

    await enviar_texto_longo(
        context,
        update.effective_chat.id,
        r,
        reply_markup=marcadores_feedback("geral")
    )


async def mensagem(update, context):
    uid = update.effective_user.id
    txt = update.message.text or ""

    print("🔔 Chegou texto:", txt[:200])

    await processar_texto(uid, txt, update, context)


# =============================================================================
# ARQUIVOS
# =============================================================================

def extrair_texto_arquivo(temp_path, file_name=""):
    nome = (file_name or temp_path or "").lower()
    extracted_text = ""

    if nome.endswith(".pdf") and PdfReader:
        reader = PdfReader(temp_path)
        pages = []

        for i, p in enumerate(reader.pages, start=1):
            try:
                texto_pagina = p.extract_text() or ""
                if texto_pagina.strip():
                    pages.append(f"\n--- Página {i} ---\n{texto_pagina}")
            except Exception:
                continue

        extracted_text = "\n".join(pages).strip()

    elif nome.endswith(".docx") and docx:
        docx_doc = docx.Document(temp_path)
        extracted_text = "\n".join(p.text for p in docx_doc.paragraphs if p.text).strip()

    elif nome.endswith((".xls", ".xlsx")):
        xls = pd.ExcelFile(temp_path)
        partes = []

        for sheet in xls.sheet_names[:5]:
            df = pd.read_excel(temp_path, sheet_name=sheet, dtype=str)
            partes.append(
                f"\n--- Aba: {sheet} ---\n" +
                df.fillna("").head(100).to_csv(sep="\t", index=False)
            )

        extracted_text = "\n".join(partes).strip()

    elif nome.endswith((".csv", ".txt", ".md", ".json")):
        with open(temp_path, "r", encoding="utf-8", errors="ignore") as f:
            extracted_text = f.read().strip()

    elif nome.endswith((".png", ".jpg", ".jpeg")) and pytesseract and Image:
        img = Image.open(temp_path)
        extracted_text = pytesseract.image_to_string(img).strip()

    return extracted_text.strip()


def preparar_texto_documento(texto):
    if not texto:
        return ""

    if len(texto) <= MAX_DOC_CHARS:
        return texto

    metade = MAX_DOC_CHARS // 2

    return (
        texto[:metade]
        + "\n\n[... conteúdo intermediário cortado para economizar tokens ...]\n\n"
        + texto[-metade:]
    )


async def analisar_documento(update, context, temp_path, file_name, instrucao):
    extracted_text = extrair_texto_arquivo(temp_path, file_name=file_name)

    if not extracted_text:
        context.user_data["ultimo_arquivo_temp"] = temp_path
        context.user_data["ultimo_arquivo_nome"] = file_name

        await context.bot.send_message(
            update.effective_chat.id,
            "Não consegui extrair texto automaticamente. Se for imagem escaneada/PDF escaneado, o OCR pode não estar disponível no Render. Use /processar_arquivo <instrução> para tentar novamente."
        )
        return

    texto_preparado = preparar_texto_documento(extracted_text)

    prompt = f"""
Arquivo recebido: {file_name}

Instrução do usuário:
{instrucao}

Texto extraído:
{texto_preparado}

Faça uma análise prática, objetiva e útil.

Estruture assim:
1. Resumo
2. Pontos importantes
3. Riscos, erros ou inconsistências
4. Dados relevantes
5. Ações recomendadas

Se for planilha, destaque números, padrões e possíveis problemas.
Se for contrato/documento técnico, destaque riscos, obrigações e brechas.
Se for texto genérico, resuma e proponha próximos passos.
"""

    resposta = chamar_gpt_sync(
        [
            {"role": "system", "content": ESTILO_SOPHOS},
            {"role": "user", "content": prompt}
        ],
        model=MODEL_FAST,
        max_tokens=1200
    )

    context.user_data["ultima_resposta"] = resposta

    await enviar_texto_longo(
        context,
        update.effective_chat.id,
        "📄 Análise do arquivo:\n\n" + resposta,
        reply_markup=marcadores_feedback("documento")
    )


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    temp_path = None

    try:
        if update.message.photo:
            file_obj = await update.message.photo[-1].get_file()
            file_name = f"photo_{uid}.jpg"

        elif update.message.document:
            doc: Document = update.message.document
            file_obj = await doc.get_file()
            file_name = doc.file_name or f"doc_{uid}"

        else:
            await context.bot.send_message(update.effective_chat.id, "Tipo de arquivo não suportado.")
            return

        suffix = os.path.splitext(file_name)[1] if file_name else ""
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        await file_obj.download_to_drive(temp_path)

        instrucao = update.message.caption or "Analise este arquivo de forma prática."

        await context.bot.send_message(update.effective_chat.id, "📥 Arquivo recebido. Processando...")

        await analisar_documento(update, context, temp_path, file_name, instrucao)

    except Exception as e:
        print("Erro handle_media:", e)
        traceback.print_exc(file=sys.stdout)
        await context.bot.send_message(update.effective_chat.id, "⚠️ Falha ao processar o arquivo.")

    finally:
        if temp_path and context.user_data.get("ultimo_arquivo_temp") != temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass


async def processar_ultimo_arquivo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    temp_path = context.user_data.get("ultimo_arquivo_temp")
    file_name = context.user_data.get("ultimo_arquivo_nome", "arquivo")

    if not temp_path or not os.path.exists(temp_path):
        await context.bot.send_message(
            update.effective_chat.id,
            "Nenhum arquivo pendente encontrado. Envie o arquivo novamente com uma legenda dizendo o que deseja."
        )
        return

    instr = " ".join(context.args) if context.args else ""

    if not instr:
        await context.bot.send_message(
            update.effective_chat.id,
            "Diga o que quer que eu faça com o arquivo.\nEx: /processar_arquivo resuma os riscos e pontos de atenção"
        )
        return

    try:
        await analisar_documento(update, context, temp_path, file_name, instr)

    except Exception as e:
        print("Erro processar_ultimo_arquivo:", e)
        await context.bot.send_message(update.effective_chat.id, "⚠️ Erro ao processar arquivo.")

    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass

        context.user_data.pop("ultimo_arquivo_temp", None)
        context.user_data.pop("ultimo_arquivo_nome", None)


# =============================================================================
# MAIN
# =============================================================================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("comandos", comandos))
    app.add_handler(CommandHandler("relatorio", relatorio_command))
    app.add_handler(CommandHandler("processar_arquivo", processar_ultimo_arquivo_cmd))

    app.add_handler(CallbackQueryHandler(feedback_handler))
    app.add_handler(MessageHandler(filters.VOICE, voz))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), mensagem))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.ALL) & (~filters.COMMAND), handle_media))

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 3000)),
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL,
    )


if __name__ == "__main__":
    main()
