# Sophos V15 Otimizada – main.py

import os
import re
import json
import sys
import tempfile
import traceback
import unicodedata
import requests
from datetime import datetime, timedelta, timezone

import pandas as pd
import aiofiles

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

MODEL_MAIN = os.environ.get("OPENAI_MODEL_MAIN")
MODEL_FAST = os.environ.get("OPENAI_MODEL_FAST")
MODEL_EMBED = "text-embedding-3-small"

MAX_DOC_CHARS = 6000
MAX_TELEGRAM_CHARS = 3900

EMOCOES = [
    "ansioso", "animado", "cansado", "focado",
    "triste", "feliz", "nervoso", "motivado"
]

TEMAS = [
    "investimento", "treino", "relacionamento",
    "espiritualidade", "saúde", "trabalho",
    "filho", "carreira", "finanças", "sophos"
]

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
# INICIALIZAÇÃO DE SERVIÇOS
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


def limitar_texto(texto: str, limite: int = MAX_TELEGRAM_CHARS) -> str:
    if not texto:
        return ""
    if len(texto) <= limite:
        return texto
    return texto[:limite - 80] + "\n\n[Resposta cortada por limite do Telegram.]"


def escapar_markdown_v2(texto: str) -> str:
    if texto is None:
        return ""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", str(texto))


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


def detectar_data_hoje(texto: str):
    match = re.search(r"hoje\s+(é\s+dia\s+|é\s+)?(\d{1,2}/\d{1,2}/\d{2,4})", texto.lower())
    if not match:
        return None

    data_str = match.group(2)

    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(data_str, fmt).date().isoformat()
        except Exception:
            continue

    return None


def detectar_emocao(texto: str):
    t = texto.lower()
    for emo in EMOCOES:
        if emo in t:
            return emo
    return None


def detectar_tema(texto: str):
    t = texto.lower()
    for tema in TEMAS:
        if tema in t:
            return tema
    return None


def marcadores_feedback(tipo):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👍", callback_data=f"{tipo}:like"),
            InlineKeyboardButton("👎", callback_data=f"{tipo}:dislike"),
        ]
    ])


# =============================================================================
# FIREBASE
# =============================================================================

def inicializar_usuario(user_id):
    user_ref = ref.child(str(user_id))

    if not user_ref.get():
        user_ref.set({"init": {"timestamp": agora_iso()}})

    for sub in [
        "contexto",
        "memoria",
        "emocao",
        "temas",
        "score_emocional",
        "feedback_respostas",
        "perfil",
    ]:
        if not user_ref.child(sub).get():
            user_ref.child(sub).set({})


def salvar_dado(user_id, tipo, valor):
    ref.child(str(user_id)).child(tipo).push({
        "valor": valor,
        "data": agora_iso()
    })


def salvar_por_tema(user_id, tema, texto):
    ref.child(str(user_id)).child("temas").child(tema).push({
        "texto": texto,
        "data": agora_iso()
    })


def salvar_emocao_por_tema(user_id, tema, emocao):
    ref.child(str(user_id)).child("score_emocional").child(tema).push({
        "emocao": emocao,
        "data": agora_iso()
    })


def registrar_feedback(user_id, tipo_resposta, feedback, texto_resposta):
    ref.child(str(user_id)).child("feedback_respostas").push({
        "tipo": tipo_resposta,
        "feedback": feedback,
        "resposta": texto_resposta[:500],
        "data": agora_iso()
    })


def salvar_memoria_relativa(user_id, chave, valor):
    ref.child(str(user_id)).child("memoria").child(chave).set(valor)


def obter_dados(user_id, tipo):
    return ref.child(str(user_id)).child(tipo).get() or {}


def buscar_por_tema(user_id, tema):
    d = ref.child(str(user_id)).child("temas").child(tema).get()
    return [x.get("texto", "") for x in d.values()] if d else []


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


# =============================================================================
# MEMÓRIA E RESUMO
# =============================================================================

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


async def buscar_contexto_semantico(user_id: int, texto: str, top_k: int = 5) -> list[str]:
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
# PERFIL E PADRÕES
# =============================================================================

def definir_perfil_usuario(user_id):
    emo_data = obter_dados(user_id, "emocao")
    tema_data = obter_dados(user_id, "score_emocional")

    freq = {}

    for e in emo_data.values():
        valor = e.get("valor")
        if valor:
            freq[valor] = freq.get(valor, 0) + 1

    tema_freq = {
        tema: len(entries)
        for tema, entries in tema_data.items()
        if isinstance(entries, dict)
    }

    perfil = "equilibrado"

    if freq.get("triste", 0) > freq.get("feliz", 0):
        perfil = "sensível empático"
    elif freq.get("focado", 0) > freq.get("cansado", 0):
        perfil = "estoico racional"
    elif tema_freq.get("espiritualidade", 0) > tema_freq.get("trabalho", 0):
        perfil = "visionário reflexivo"

    ref.child(str(user_id)).child("perfil").set({
        "tipo": perfil,
        "data": agora_iso()
    })

    return perfil


async def analisar_padroes(context: ContextTypes.DEFAULT_TYPE):
    hoje = datetime.now(timezone.utc).date()
    semana_atras = hoje - timedelta(days=7)

    usuarios = ref.get() or {}

    for uid_str in usuarios.keys():
        emoc_entries = ref.child(uid_str).child("emocao").get() or {}
        cont_emoc = {}

        for e in emoc_entries.values():
            try:
                data = datetime.fromisoformat(e["data"]).date()
                if data >= semana_atras:
                    valor = e.get("valor")
                    if valor:
                        cont_emoc[valor] = cont_emoc.get(valor, 0) + 1
            except Exception:
                continue

        humor_predominante = max(cont_emoc, key=cont_emoc.get) if cont_emoc else None

        tema_entries = ref.child(uid_str).child("temas").get() or {}
        cont_tema = {}

        for tema, msgs in tema_entries.items():
            if not isinstance(msgs, dict):
                continue

            for m in msgs.values():
                try:
                    data = datetime.fromisoformat(m["data"]).date()
                    if data >= semana_atras:
                        cont_tema[tema] = cont_tema.get(tema, 0) + 1
                except Exception:
                    continue

        ref.child(uid_str).child("padroes_semanais").set({
            "de": semana_atras.isoformat(),
            "ate": hoje.isoformat(),
            "emocoes": cont_emoc,
            "temas": cont_tema,
            "humor_predominante": humor_predominante
        })

# =============================================================================
# INTERVALS.ICU
# =============================================================================

def coletar_intervals(dias=7):
    hoje = datetime.now().date()
    inicio = hoje - timedelta(days=dias)
    auth = ("API_KEY", INTERVALS_API_KEY)
    base = f"https://intervals.icu/api/v1/athlete/{INTERVALS_ATHLETE_ID}"

    # === ATIVIDADES ===
    ativ = requests.get(
        f"{base}/activities",
        params={"oldest": inicio.isoformat(), "newest": (hoje + timedelta(days=1)).isoformat()},
                #"newest": hoje.isoformat()},
        auth=auth, timeout=30
    ).json()

    treinos = []
    for a in ativ:
        vel = a.get("average_speed")
        treinos.append({
            "tipo": a.get("type"),
            "nome": a.get("name"),
            "data": (a.get("start_date_local") or "")[:10],
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
            (a.get("distance") or 0) for a in ativ
            if chave in (a.get("type") or "").lower()
        ))

    totais = {
        "natacao_m": soma_tipo("swim"),
        "bike_km": round(soma_tipo("ride") / 1000, 1),
        "corrida_km": round(soma_tipo("run") / 1000, 1),
        "calorias": round(sum(a.get("calories") or 0 for a in ativ)),
        "carga_total": round(sum(a.get("icu_training_load") or 0 for a in ativ)),
        "total_sessoes": len(ativ),
    }

    # === WELLNESS (fitness, fadiga, forma, HRV, sono, VO2) ===
    wel = requests.get(
        f"{base}/wellness",
        params={"oldest": inicio.isoformat(), "newest": hoje.isoformat()},
        auth=auth, timeout=30
    ).json()

    if isinstance(wel, dict):
        wel = list(wel.values())

    def media(campo, transform=lambda x: x):
        vals = [transform(w[campo]) for w in wel if w.get(campo)]
        return round(sum(vals) / len(vals), 1) if vals else None

    # Condicionamento — pega o registro mais recente que tiver dados
    ultimo = next((w for w in reversed(wel) if w.get("ctl")), {})
    primeiro = next((w for w in wel if w.get("ctl")), {})

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
        "periodo": f"{inicio.isoformat()} a {hoje.isoformat()}",
        "dias": dias,
        "totais": totais,
        "treinos": treinos,
        "condicionamento": condicionamento,
        "recuperacao": recuperacao,
    }


async def relatorio_command(update, context):
    uid = update.effective_user.id
    dias = 7
    if context.args:
        try:
            dias = int(context.args[0])
        except ValueError:
            pass

    await context.bot.send_message(
        update.effective_chat.id,
        f"📊 Gerando relatório completo ({dias} dias)..."
    )

    try:
        d = coletar_intervals(dias)
    except Exception as e:
        print("Erro relatorio:", e)
        await context.bot.send_message(
            update.effective_chat.id,
            "⚠️ Falha ao coletar dados do Intervals.icu. Verifique API Key e Athlete ID."
        )
        return

    prompt = f"""
Você é coach de endurance e cientista de dados de performance. Não utilize: ** _ _ ## Markdown, utilize apenas texto puro para não consumir o limite de caracteres do telegram.
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
        limitar_texto("📊 Relatório de Performance:\n\n" + resposta),
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
        "👋 Olá! Eu sou o Sophos. Pronto pra te ouvir e evoluir contigo 🧠"
    )


async def comandos(update, context):
    msg = (
        "📌 *Comandos disponíveis:*\n"
        "/start — iniciar conversa\n"
        "/perfil — ver perfil\n"
        "/resumo — resumo emocional\n"
        "/consultar <tema> — histórico por tema\n"
        "/resumir <texto> — gerar resumo\n"
        "/conselheiro — conselho emocional\n"
        "/padroes — padrões semanais\n"
        "/estatisticas — feedback das respostas\n"
        "/exportar — backup Excel/TXT\n"
        "/processar_arquivo <instrução> — processar último arquivo pendente\n"
        "/relatorio <dias> — análise completa de treino\n"
        "/comandos — mostrar este menu"
        
        
    )

    await context.bot.send_message(update.effective_chat.id, msg)


async def perfil_command(update, context):
    uid = update.effective_user.id
    perfil = ref.child(str(uid)).child("perfil").get()

    if not perfil:
        perfil_tipo = definir_perfil_usuario(uid)
    else:
        perfil_tipo = perfil.get("tipo", "desconhecido")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🧩 Perfil atual: {perfil_tipo}"
    )


async def resumo(update, context):
    uid = update.effective_user.id
    d = obter_dados(uid, "emocao")

    if not d:
        await context.bot.send_message(update.effective_chat.id, "Nenhuma emoção registrada.")
        return

    cnt = {}

    for e in d.values():
        valor = e.get("valor")
        if valor:
            cnt[valor] = cnt.get(valor, 0) + 1

    texto = "📊 Resumo emocional:\n" + "\n".join(
        f"- {k}: {v}x" for k, v in cnt.items()
    )

    await context.bot.send_message(update.effective_chat.id, texto)


async def padroes_semanais_command(update, context):
    uid = update.effective_user.id
    dados = ref.child(str(uid)).child("padroes_semanais").get() or {}

    if not dados:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔍 Ainda não há análise semanal disponível."
        )
        return

    humor = dados.get("humor_predominante", "-")
    emocoes = ", ".join(f"{k}: {v}" for k, v in dados.get("emocoes", {}).items()) or "-"
    temas = ", ".join(f"{k}: {v}" for k, v in dados.get("temas", {}).items()) or "-"

    texto = (
        f"📅 Padrões de {dados.get('de')} até {dados.get('ate')}\n\n"
        f"🧠 Humor predominante: {humor}\n"
        f"🧠 Emoções: {emocoes}\n"
        f"📂 Temas: {temas}"
    )

    await context.bot.send_message(update.effective_chat.id, texto)


async def conselheiro(update, context):
    uid = update.effective_user.id
    d = obter_dados(uid, "emocao")

    if not d or len(d) < 3:
        await context.bot.send_message(update.effective_chat.id, "Poucos dados pra gerar conselho.")
        return

    recentes = list(d.values())[-7:]

    prompt = (
        "Com base nas emoções recentes abaixo, gere um conselho prático, direto e equilibrado:\n\n"
        + "\n".join(f"- {e.get('data', '')[:10]}: {e.get('valor', '')}" for e in recentes)
    )

    r = chamar_gpt_sync(
        [
            {"role": "system", "content": ESTILO_SOPHOS},
            {"role": "user", "content": prompt}
        ],
        model=MODEL_FAST,
        max_tokens=700
    )

    context.user_data["ultima_resposta"] = r

    await context.bot.send_message(
        update.effective_chat.id,
        limitar_texto("📜 " + r),
        reply_markup=marcadores_feedback("conselheiro")
    )


async def consultar_tema(update, context):
    uid = update.effective_user.id

    if not context.args:
        await context.bot.send_message(update.effective_chat.id, "Ex: /consultar treino")
        return

    tema = context.args[0].lower()
    msgs = buscar_por_tema(uid, tema)

    if not msgs:
        await context.bot.send_message(update.effective_chat.id, f"Nenhum registro de '{tema}'.")
        return

    texto = f"📂 Últimos sobre '{tema}':\n" + "\n".join(msgs[-5:])
    await context.bot.send_message(update.effective_chat.id, limitar_texto(texto))


async def resumir(update, context):
    if not context.args:
        await context.bot.send_message(update.effective_chat.id, "Ex: /resumir <texto>")
        return

    orig = " ".join(context.args)

    r = chamar_gpt_sync(
        [{"role": "user", "content": f"Resuma de forma prática:\n\n{orig}"}],
        model=MODEL_FAST,
        max_tokens=700
    )

    context.user_data["ultima_resposta"] = r

    await context.bot.send_message(
        update.effective_chat.id,
        limitar_texto("📝 " + r),
        reply_markup=marcadores_feedback("resumir")
    )


async def estatisticas(update, context):
    uid = update.effective_user.id
    fb = ref.child(str(uid)).child("feedback_respostas").get() or {}

    resumo_fb = {}

    for e in fb.values():
        if not isinstance(e, dict):
            continue

        resposta = e.get("resposta", "")
        feedback = e.get("feedback")

        if not resposta or feedback not in ["like", "dislike"]:
            continue

        chave = resposta[:120].replace("\n", " ")
        resumo_fb.setdefault(chave, {"like": 0, "dislike": 0})
        resumo_fb[chave][feedback] += 1

    linhas = ["📊 Suas estatísticas de feedback:"]

    if not resumo_fb:
        linhas.append("Nenhum feedback registrado ainda.")
    else:
        for txt, cnt in resumo_fb.items():
            linhas.append(f"- {txt} (👍 {cnt['like']} | 👎 {cnt['dislike']})")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=limitar_texto("\n".join(linhas))
    )


async def exportar(update, context):
    user_id = update.effective_user.id
    dados = ref.child(str(user_id)).get()

    if not dados:
        await context.bot.send_message(update.effective_chat.id, "⚠️ Nenhum dado encontrado.")
        return

    registros = []

    for tipo, entradas in dados.items():
        if not isinstance(entradas, dict):
            continue

        for e in entradas.values():
            if not isinstance(e, dict):
                continue

            valor = e.get("valor") or e.get("texto") or e.get("emocao")
            data = e.get("data", "")

            if valor:
                registros.append({
                    "tipo": tipo,
                    "valor": valor,
                    "data": data
                })

    if not registros:
        await context.bot.send_message(update.effective_chat.id, "⚠️ Nenhum registro válido.")
        return

    df = pd.DataFrame(registros)

    excel_path = f"sophos_{user_id}.xlsx"
    txt_path = f"sophos_{user_id}.txt"

    df.to_excel(excel_path, index=False)
    df.to_csv(txt_path, index=False, sep="\t")

    for path in (excel_path, txt_path):
        async with aiofiles.open(path, "rb") as f:
            data = await f.read()
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=InputFile(data, filename=os.path.basename(path))
            )

        try:
            os.remove(path)
        except Exception:
            pass


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

    await q.message.reply_text("✅ Feedback registrado. Obrigado!")


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
    texto_lower = texto_original.lower()

    await resumir_contexto_antigo(user_id)

    salvar_contexto(user_id, texto_original)

    # Memória só quando fizer sentido
    if deve_extrair_memoria(texto_original):
        memoria_nova = extrair_memoria_com_gpt(texto_original)
        salvar_memoria_e_indexar(user_id, memoria_nova)

    # Data
    dhoje = detectar_data_hoje(texto_original)

    if dhoje:
        salvar_memoria_relativa(user_id, "data_atual", dhoje)
        await context.bot.send_message(update.effective_chat.id, f"📅 Data registrada: {dhoje}")

    # Emoção
    emocao = detectar_emocao(texto_lower)

    if emocao:
        salvar_dado(user_id, "emocao", emocao)
        await context.bot.send_message(update.effective_chat.id, f"🧠 Emoção '{emocao}' registrada.")

    # Tema
    tema = detectar_tema(texto_lower)

    if tema:
        salvar_por_tema(user_id, tema, texto_original)
        if emocao:
            salvar_emocao_por_tema(user_id, tema, emocao)

    # Estilo dinâmico
    likes, dislikes = recuperar_feedback_counts(user_id)

    estilo_dinamico = None

    if likes > dislikes + 5:
        estilo_dinamico = "Prefira respostas mais sucintas e diretas."
    elif dislikes > likes + 5:
        estilo_dinamico = "Adote tom mais explicativo e didático."

    # Contexto
    base = recuperar_contexto(user_id)

    perfil = ref.child(str(user_id)).child("perfil").get() or {}
    perfil_tipo = perfil.get("tipo", "")

    if perfil_tipo:
        base += f"\n\nPerfil detectado: {perfil_tipo}"

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

    await context.bot.send_message(
        update.effective_chat.id,
        limitar_texto(r),
        reply_markup=marcadores_feedback("geral")
    )


async def mensagem(update, context):
    uid = update.effective_user.id
    txt = update.message.text or ""

    print("🔔 Chegou texto:", txt[:200])

    await processar_texto(uid, txt, update, context)


# =============================================================================
# ARQUIVOS E IMAGENS
# =============================================================================

def extrair_texto_arquivo(temp_path):
    extracted_text = ""

    if temp_path.lower().endswith(".pdf") and PdfReader:
        reader = PdfReader(temp_path)
        pages = []

        for p in reader.pages:
            try:
                pages.append(p.extract_text() or "")
            except Exception:
                continue

        extracted_text = "\n".join(pages).strip()

    elif temp_path.lower().endswith(".docx") and docx:
        docx_doc = docx.Document(temp_path)
        extracted_text = "\n".join(p.text for p in docx_doc.paragraphs).strip()

    elif temp_path.lower().endswith((".xls", ".xlsx")):
        df = pd.read_excel(temp_path, dtype=str)
        extracted_text = df.fillna("").to_csv(sep="\t", index=False)

    elif temp_path.lower().endswith((".png", ".jpg", ".jpeg")) and pytesseract and Image:
        img = Image.open(temp_path)
        extracted_text = pytesseract.image_to_string(img)

    return extracted_text.strip()


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    file_obj = None
    file_name = None
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
        await context.bot.send_message(update.effective_chat.id, "📥 Arquivo recebido. Processando...")

        extracted_text = extrair_texto_arquivo(temp_path)

        if not extracted_text:
            context.user_data["ultimo_arquivo_temp"] = temp_path
            await context.bot.send_message(
                update.effective_chat.id,
                "Não consegui extrair texto automaticamente. Use /processar_arquivo <instrução> se quiser tentar de novo."
            )
            return

        prompt = f"""
Texto extraído do arquivo:
{extracted_text[:MAX_DOC_CHARS]}

Faça uma análise prática:
- resumo;
- pontos importantes;
- riscos ou inconsistências;
- dados relevantes;
- ações recomendadas.
"""

        resposta = chamar_gpt_sync(
            [
                {"role": "system", "content": ESTILO_SOPHOS},
                {"role": "user", "content": prompt}
            ],
            model=MODEL_FAST,
            max_tokens=1000
        )

        context.user_data["ultima_resposta"] = resposta

        await context.bot.send_message(
            update.effective_chat.id,
            limitar_texto("📄 Análise:\n" + resposta),
            reply_markup=marcadores_feedback("documento")
        )

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

    if not temp_path or not os.path.exists(temp_path):
        await context.bot.send_message(update.effective_chat.id, "Nenhum arquivo pendente encontrado.")
        return

    instr = " ".join(context.args) if context.args else ""

    if not instr:
        await context.bot.send_message(
            update.effective_chat.id,
            "Diga o que quer que eu faça com o arquivo: resumir/analisar/validar/extrair dados."
        )
        return

    try:
        extracted_text = extrair_texto_arquivo(temp_path)

        if not extracted_text:
            await context.bot.send_message(
                update.effective_chat.id,
                "Não consegui extrair texto automaticamente deste arquivo."
            )
            return

        prompt = f"""
Texto extraído do arquivo:
{extracted_text[:MAX_DOC_CHARS]}

Instrução do usuário:
{instr}

Responda de forma prática e direta.
"""

        resposta = chamar_gpt_sync(
            [
                {"role": "system", "content": ESTILO_SOPHOS},
                {"role": "user", "content": prompt}
            ],
            model=MODEL_FAST,
            max_tokens=1000
        )

        context.user_data["ultima_resposta"] = resposta

        await context.bot.send_message(
            update.effective_chat.id,
            limitar_texto("📄 Resultado:\n" + resposta),
            reply_markup=marcadores_feedback("documento")
        )

    except Exception as e:
        print("Erro processar_ultimo_arquivo:", e)
        await context.bot.send_message(update.effective_chat.id, "⚠️ Erro ao processar arquivo.")

    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass

        context.user_data.pop("ultimo_arquivo_temp", None)


# =============================================================================
# MAIN
# =============================================================================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.job_queue.run_repeating(
        analisar_padroes,
        interval=timedelta(days=7),
        first=30
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("comandos", comandos))
    app.add_handler(CommandHandler("perfil", perfil_command))
    app.add_handler(CommandHandler("resumo", resumo))
    app.add_handler(CommandHandler("consultar", consultar_tema))
    app.add_handler(CommandHandler("resumir", resumir))
    app.add_handler(CommandHandler("conselheiro", conselheiro))
    app.add_handler(CommandHandler("padroes", padroes_semanais_command))
    app.add_handler(CommandHandler("estatisticas", estatisticas))
    app.add_handler(CommandHandler("exportar", exportar))
    app.add_handler(CommandHandler("processar_arquivo", processar_ultimo_arquivo_cmd))
    app.add_handler(CommandHandler("relatorio", relatorio_command))


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
