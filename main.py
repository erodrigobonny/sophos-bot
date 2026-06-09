# Sophos V17 Enxuto – main.py

import os
import re
import json
import sys
import tempfile
import traceback
import unicodedata
import requests
import base64
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

# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

HISTORY_LIMIT = 6
SUMMARY_TRIGGER = 20
SUMMARY_KEY = "resumo_anterior"

MODEL_MAIN = os.environ.get("OPENAI_MODEL_MAIN")
MODEL_FAST = os.environ.get("OPENAI_MODEL_FAST")
MODEL_INT = os.environ.get("OPENAI_MODEL_INT")
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

IMPORTANTE:
Não utilize: ** -- ## Markdown, utilize apenas texto puro.
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

client = OpenAI(api_key=OPENAI_API_KEY, timeout=60.0, max_retries=2)

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

        if corte == -1 or corte < 1000:
            corte = limite

        parte = texto[:corte].strip()
        if parte:
            partes.append(parte)

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

def chamar_gpt_sync(messages, model=MODEL_FAST, max_tokens=None, user_id=None):
    kwargs = {
        "model": model,
        "messages": messages,
    }

    if max_tokens:
        kwargs["max_completion_tokens"] = max_tokens

    resp = client.chat.completions.create(**kwargs)

    # Log de uso no Firebase (custo zero de chamada extra)
    try:
        if user_id and resp.usage:
            uso = {
                "modelo": model,
                "input_tokens": resp.usage.prompt_tokens,
                "output_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
                "data": agora_iso(),
            }
            push_ref = ref.child(str(user_id)).child("uso_tokens").push(uso)
            # Limpeza esporádica: ~1 a cada 50 chamadas
            if push_ref.key and push_ref.key[-1] in ("0", "5"):
                limpar_uso_antigo(user_id)
    except Exception as e:
        print("Erro ao logar uso:", e)           

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

def limpar_uso_antigo(user_id, max_registros=5000):
    """Mantém só os registros mais recentes de uso_tokens."""
    try:
        uso_ref = ref.child(str(user_id)).child("uso_tokens")
        todos = uso_ref.get() or {}

        if len(todos) <= max_registros:
            return

        # Ordena por chave (push do Firebase é cronológico) e remove os mais antigos
        chaves_ordenadas = sorted(todos.keys())
        excesso = len(todos) - max_registros

        for chave in chaves_ordenadas[:excesso]:
            uso_ref.child(chave).delete()

        print(f"🧹 Limpeza uso_tokens: removidos {excesso} registros antigos.")
    except Exception as e:
        print("Erro ao limpar uso_tokens:", e)

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

def calcular_indicadores(d):
    totais = d.get("totais", {})
    cond = d.get("condicionamento", {})
    rec = d.get("recuperacao", {})
    treinos = d.get("treinos", [])
    dias = d.get("dias", 0) or 0

    carga = totais.get("carga_total") or 0
    sessoes = totais.get("total_sessoes") or 0
    ctl = cond.get("fitness_ctl") or 0
    atl = cond.get("fadiga_atl") or 0

    dias_ativos = len(set(t.get("data") for t in treinos if t.get("data")))

    carga_por_modalidade = {}

    for t in treinos:
        tipo = (t.get("tipo") or "outros").lower()

        if "run" in tipo:
            grupo = "corrida"
        elif "ride" in tipo or "bike" in tipo:
            grupo = "bike"
        elif "swim" in tipo:
            grupo = "natacao"
        elif "strength" in tipo or "weight" in tipo:
            grupo = "forca"
        else:
            grupo = "outros"

        carga_t = t.get("carga_treino") or 0
        carga_por_modalidade[grupo] = carga_por_modalidade.get(grupo, 0) + carga_t

    distribuicao_carga_pct = {
        k: round((v / carga) * 100, 1) if carga else 0
        for k, v in carga_por_modalidade.items()
    }

    maior_carga = max(treinos, key=lambda t: t.get("carga_treino") or 0, default=None)
    maior_duracao = max(treinos, key=lambda t: t.get("dur_min") or 0, default=None)
    maior_distancia = max(treinos, key=lambda t: t.get("dist_km") or 0, default=None)

    def treino_resumo(t):
        if not t:
            return None

        return {
            "tipo": t.get("tipo"),
            "nome": t.get("nome"),
            "data": t.get("data"),
            "dist_km": t.get("dist_km"),
            "dur_min": t.get("dur_min"),
            "carga": t.get("carga_treino"),
            "fc_med": t.get("fc_med"),
        }

    sono_medio = rec.get("sono_medio_h")
    hrv_medio = rec.get("hrv_medio")
    rhr_medio = rec.get("rhr_medio")

    carga_por_dia = round(carga / dias, 1) if dias else 0
    acwr = round(atl / ctl, 2) if ctl else None

    alerta_recuperacao = "baixo"
    sinais = []

    # Cortes genéricos e conservadores.
    # Versão futura: comparar contra baseline individual salva no Firebase.
    if sono_medio is not None and sono_medio < 6.0:
        sinais.append("sono baixo")

    if hrv_medio is not None and hrv_medio < 40:
        sinais.append("HRV baixo")

    if rhr_medio is not None and rhr_medio > 60:
        sinais.append("RHR elevado")

    if acwr is not None and acwr > 1.4:
        sinais.append("carga aguda elevada")

    if len(sinais) >= 3:
        alerta_recuperacao = "alto"
    elif len(sinais) == 2:
        alerta_recuperacao = "moderado"

        # cargas diárias
    cargas_por_dia = {}

    for t in treinos:
        data = t.get("data")
        if not data:
            continue

        cargas_por_dia[data] = cargas_por_dia.get(data, 0) + (t.get("carga_treino") or 0)

    cargas_lista = list(cargas_por_dia.values())

    if len(cargas_lista) >= 2:
        media_carga_diaria = sum(cargas_lista) / len(cargas_lista)
        variancia = sum((x - media_carga_diaria) ** 2 for x in cargas_lista) / len(cargas_lista)
        desvio = variancia ** 0.5
        monotonia = round(media_carga_diaria / desvio, 2) if desvio else None
        strain = round(media_carga_diaria * monotonia, 1) if monotonia else None
    else:
        monotonia = None
        strain = None

    natacoes = [
        t for t in treinos
        if "swim" in (t.get("tipo") or "").lower()
        and (t.get("dist_km") or 0) > 0
        and (t.get("dur_min") or 0) > 0
    ]

    metricas_natacao = []

    for t in natacoes:
        dist_m = (t.get("dist_km") or 0) * 1000
        dur_min = t.get("dur_min") or 0
        cad = t.get("cadencia")

        pace_100m = round(dur_min / (dist_m / 100), 2) if dist_m else None

        dps_estimado = None
        swolf_estimado = None

        if cad and dur_min and dist_m:
            total_braçadas = cad * dur_min
            dps_estimado = round(dist_m / total_braçadas, 2) if total_braçadas else None

            comprimentos = t.get("comprimentos")
            if comprimentos:
                seg_por_piscina = (dur_min * 60) / comprimentos
                bracadas_por_piscina = total_braçadas / comprimentos
                swolf_estimado = round(seg_por_piscina + bracadas_por_piscina, 1)

        metricas_natacao.append({
            "data": t.get("data"),
            "tipo": t.get("tipo"),
            "dist_m": round(dist_m),
            "dur_min": dur_min,
            "pace_100m_min": pace_100m,
            "cadencia": round(cad, 1) if cad else None,
            "dps_estimado": dps_estimado,
            "swolf_estimado": swolf_estimado,
        })

    ftps_treino = [t.get("ftp") for t in treinos if t.get("ftp")]
    ftp_bike_detectado = ftps_treino[-1] if ftps_treino else None

    eftp = cond.get("eftp")

    diferenca_ftp_eftp = None
    if ftp_bike_detectado and eftp:
        diferenca_ftp_eftp = round(ftp_bike_detectado - eftp, 1)

    carga_corrida = carga_por_modalidade.get("corrida", 0)
    carga_bike = carga_por_modalidade.get("bike", 0)

    razao_corrida_bike = round(carga_corrida / carga_bike, 2) if carga_bike else None

    sessoes_alta_intensidade = [
        t for t in treinos
        if (t.get("intensidade") or 0) >= 90
    ]

    percentual_intensidade_alta = round(
        (len(sessoes_alta_intensidade) / len(treinos)) * 100,
        1
    ) if treinos else 0

    maior_carga_por_modalidade = {}

    for grupo in carga_por_modalidade:
        treinos_grupo = []

        for t in treinos:
            tipo = (t.get("tipo") or "").lower()

            if grupo == "corrida" and "run" in tipo:
                treinos_grupo.append(t)
            elif grupo == "bike" and ("ride" in tipo or "bike" in tipo):
                treinos_grupo.append(t)
            elif grupo == "natacao" and "swim" in tipo:
                treinos_grupo.append(t)
            elif grupo == "forca" and ("strength" in tipo or "weight" in tipo):
                treinos_grupo.append(t)

        maior = max(treinos_grupo, key=lambda x: x.get("carga_treino") or 0, default=None)
        maior_carga_por_modalidade[grupo] = treino_resumo(maior)

    return {
        "acwr": acwr,
        "carga_por_dia": carga_por_dia,
        "carga_por_sessao": round(carga / sessoes, 1) if sessoes else 0,
        "densidade_treino": round(sessoes / dias, 2) if dias else 0,
        "dias_ativos": dias_ativos,
        "dias_off": max(dias - dias_ativos, 0),
        "dias_ativos_pct": round((dias_ativos / dias) * 100, 1) if dias else 0,
        "distribuicao_carga_pct": distribuicao_carga_pct,
        "maior_treino_carga": treino_resumo(maior_carga),
        "maior_treino_duracao": treino_resumo(maior_duracao),
        "maior_treino_distancia": treino_resumo(maior_distancia),
        "monotonia_carga": monotonia,
        "strain": strain,
        "metricas_natacao": metricas_natacao,
        "ftp_bike_detectado": ftp_bike_detectado,
        "eftp_intervals": eftp,
        "diferenca_ftp_eftp": diferenca_ftp_eftp,
        "razao_carga_corrida_bike": razao_corrida_bike,
        "percentual_sessoes_alta_intensidade": percentual_intensidade_alta,
        "maior_carga_por_modalidade": maior_carga_por_modalidade,
        "alerta_recuperacao": {
            "nivel": alerta_recuperacao,
            "sinais": sinais,
            "observacao": "cortes genéricos provisórios; ideal futuro é comparar com baseline individual"
        }
    }

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

    ##print("\n===== ACTIVITY SAMPLE =====")
    ##if ativ:
    ##    print(json.dumps(ativ[0], indent=2, ensure_ascii=False))

    ##for a in ativ:
    ##    if a.get("type") in ["Swim", "OpenWaterSwim"]:
    ##        print("\n===== SWIM SAMPLE =====")
    ##        print(json.dumps(a, indent=2, ensure_ascii=False))
    ##        break

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
            "trimp": round(a.get("trimp"), 1) if a.get("trimp") is not None else None,
            "cal": a.get("calories"),
            
            "ftp": a.get("icu_ftp") or a.get("icu_pm_ftp") or a.get("icu_rolling_ftp"),
            "power_range": a.get("power_range"),
            "power_load": a.get("power_load"),
            "lthr": a.get("lthr"),
            "hr_load": a.get("hr_load"),
            "hr_load_type": a.get("hr_load_type"),
            "zonas_fc": a.get("icu_hr_zones"),
            "zona_fc_tempos": a.get("icu_hr_zone_times"),
            "stride_m": a.get("average_stride"),
            "eficiencia": a.get("icu_efficiency_factor"),
            "decoupling": a.get("decoupling"),
            "comprimentos": a.get("lengths"),
            "comprimento_piscina": a.get("pool_length"),
            
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

    ##print("\n===== WELLNESS SAMPLE =====")
    ##if wel:
    ##    print(json.dumps(wel[-1], indent=2, ensure_ascii=False))

    wel_filtrado = []
    wel.sort(key=lambda w: str(w.get("id") or w.get("date") or w.get("day") or ""))

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

    def tendencia(campo, transform=lambda x: x):
        vals = []

        for w in wel:
            valor = w.get(campo)
            if valor is not None:
                try:
                    vals.append(transform(valor))
                except Exception:
                    pass

        if len(vals) < 4:
            return None

        metade = len(vals) // 2
        inicio_vals = vals[:metade]
        fim_vals = vals[metade:]

        media_inicio = sum(inicio_vals) / len(inicio_vals)
        media_fim = sum(fim_vals) / len(fim_vals)

        return {
            "inicio": round(media_inicio, 1),
            "fim": round(media_fim, 1),
            "variacao": round(media_fim - media_inicio, 1)
        }

    ultimo = next((w for w in reversed(wel) if w.get("ctl") is not None), {})
    primeiro = next((w for w in wel if w.get("ctl") is not None), {})

    ride_info = next(
        (s for s in (ultimo.get("sportInfo") or [])
         if s.get("type") == "Ride"),
        {}
    )

    condicionamento = {
        "fitness_ctl": round(ultimo.get("ctl") or 0, 1),
        "fadiga_atl": round(ultimo.get("atl") or 0, 1),
        "forma_tsb": round((ultimo.get("ctl") or 0) - (ultimo.get("atl") or 0), 1),
        "vo2max": ultimo.get("vo2max"),
        "ftp": ultimo.get("ftp"),
        "ftp_wkg": ultimo.get("ftp_wkg"),
        "tendencia_fitness": round((ultimo.get("ctl") or 0) - (primeiro.get("ctl") or 0), 1),
        "eftp": round(ride_info.get("eftp"), 1) if ride_info.get("eftp") else None,
        "wprime": round(ride_info.get("wPrime"), 0) if ride_info.get("wPrime") else None,
        "pmax": round(ride_info.get("pMax"), 0) if ride_info.get("pMax") else None,
    }

    recuperacao = {
        "hrv_medio": media("hrv"),
        "rhr_medio": media("restingHR"),
        "sono_medio_h": media("sleepSecs", lambda s: s / 3600),
        "sono_score_medio": media("sleepScore"),
        "readiness_medio": media("readiness"),
        "peso_medio": media("weight"),
        "passos_medio": media("steps"),
        "stress_medio": media("avgStress"),
        "body_battery_medio": media("bodyBattery"),
        "spo2_medio": media("spO2"),
        "tendencia_hrv": tendencia("hrv"),
        "tendencia_rhr": tendencia("restingHR"),
        "tendencia_sono_h": tendencia("sleepSecs", lambda s: s / 3600),
    }

    resultado = {
        "periodo": f"{inicio.isoformat()} a {fim.isoformat()}",
        "dias": (fim - inicio).days + 1,
        "totais": totais,
        "treinos": treinos,
        "condicionamento": condicionamento,
        "recuperacao": recuperacao,
    }

    resultado["indicadores"] = calcular_indicadores(resultado)

    return resultado

#--------------- METRICAS--------------------#
def valor(v, sufixo=""):
    if v is None:
        return "sem dado"
    return f"{v}{sufixo}"


def data_curta(data):
    if not data:
        return "-"
    try:
        return datetime.fromisoformat(data).strftime("%d/%m")
    except Exception:
        return data


def tipo_label(tipo):
    t = (tipo or "").lower()

    if "swim" in t:
        return "🏊 Natação"
    if "ride" in t or "bike" in t:
        return "🚴 Bike"
    if "run" in t:
        return "🏃 Corrida"
    if "weight" in t or "strength" in t:
        return "🏋️ Força"

    return "📌 Outros"


def treino_linha(t):
    partes = []

    partes.append(f"{data_curta(t.get('data'))} — {t.get('nome') or t.get('tipo')}")

    if t.get("dist_km") and t.get("dist_km") > 0:
        partes.append(f"{t.get('dist_km')} km")

    if t.get("dur_min"):
        partes.append(f"{t.get('dur_min')} min")

    if t.get("carga_treino") is not None:
        partes.append(f"carga {t.get('carga_treino')}")

    if t.get("trimp") is not None:
        partes.append(f"TRIMP {round(t.get('trimp'), 1)}")

    if t.get("fc_med") is not None or t.get("fc_max") is not None:
        partes.append(f"FC {valor(t.get('fc_med'))}/{valor(t.get('fc_max'))}")

    if t.get("pace_min_km") is not None:
        partes.append(f"pace {t.get('pace_min_km')}")

    if t.get("cadencia") is not None:
        partes.append(f"cad {round(t.get('cadencia'), 1)}")

    if t.get("ftp") is not None:
        partes.append(f"FTP {t.get('ftp')}W")

    if t.get("lthr") is not None:
        partes.append(f"LTHR {t.get('lthr')}")

    return " • ".join(partes)


def formatar_treino_destaque(t):
    if not t:
        return "sem dado"

    linhas = []
    linhas.append(f"{tipo_label(t.get('tipo'))}")
    linhas.append(f"Data: {data_curta(t.get('data'))}")
    linhas.append(f"Treino: {t.get('nome') or '-'}")

    if t.get("dist_km") is not None:
        linhas.append(f"Distância: {t.get('dist_km')} km")

    if t.get("dur_min") is not None:
        linhas.append(f"Duração: {t.get('dur_min')} min")

    if t.get("carga") is not None:
        linhas.append(f"Carga: {t.get('carga')}")

    if t.get("fc_med") is not None:
        linhas.append(f"FC média: {t.get('fc_med')}")

    return "\n".join(linhas)


def formatar_distribuicao(distrib):
    if not distrib:
        return "sem dado"

    ordem = sorted(distrib.items(), key=lambda x: x[1], reverse=True)

    nomes = {
        "corrida": "Corrida",
        "natacao": "Natação",
        "bike": "Bike",
        "forca": "Força",
        "outros": "Outros"
    }

    return "\n".join(
        f"• {nomes.get(k, k.title())}: {v}%"
        for k, v in ordem
    )


def formatar_alerta(alerta):
    if not alerta:
        return "sem dado"

    nivel = alerta.get("nivel", "sem dado")
    sinais = alerta.get("sinais") or []

    linhas = []
    linhas.append(f"Nível: {nivel}")

    if sinais:
        linhas.append("Sinais:")
        for s in sinais:
            linhas.append(f"• {s}")
    else:
        linhas.append("Sinais: nenhum")

    obs = alerta.get("observacao")
    if obs:
        linhas.append(f"Obs: {obs}")

    return "\n".join(linhas)


def formatar_metricas(d):
    totais = d.get("totais", {})
    cond = d.get("condicionamento", {})
    rec = d.get("recuperacao", {})
    ind = d.get("indicadores", {})
    treinos = d.get("treinos", [])

    ftp_treino = next((t.get("ftp") for t in treinos if t.get("ftp")), None)

    linhas = []

    linhas.append("📊 MÉTRICAS DE PERFORMANCE")
    linhas.append(f"Período: {d.get('periodo')}")
    linhas.append(f"Dias: {d.get('dias')}")
    linhas.append("")

    linhas.append("1. TOTAIS")
    linhas.append(f"Sessões: {valor(totais.get('total_sessoes'))}")
    linhas.append(f"Carga total: {valor(totais.get('carga_total'))}")
    linhas.append(f"Calorias: {valor(totais.get('calorias'))}")
    linhas.append(f"Natação: {valor(totais.get('natacao_m'), ' m')}")
    linhas.append(f"Bike: {valor(totais.get('bike_km'), ' km')}")
    linhas.append(f"Corrida: {valor(totais.get('corrida_km'), ' km')}")
    linhas.append("")

    linhas.append("2. CONDICIONAMENTO")
    linhas.append(f"CTL / Fitness: {valor(cond.get('fitness_ctl'))}")
    linhas.append(f"ATL / Fadiga: {valor(cond.get('fadiga_atl'))}")
    linhas.append(f"TSB / Forma: {valor(cond.get('forma_tsb'))}")
    linhas.append(f"Tendência fitness: {valor(cond.get('tendencia_fitness'))}")
    linhas.append(f"VO2max: {valor(cond.get('vo2max'))}")
    linhas.append(f"FTP bike: {valor(cond.get('ftp') or ftp_treino, ' W')}")
    linhas.append(f"eFTP: {valor(cond.get('eftp'), ' W')}")
    linhas.append(f"W': {valor(cond.get('wprime'))}")
    linhas.append(f"Pmax: {valor(cond.get('pmax'), ' W')}")
    linhas.append("")

    linhas.append("3. RECUPERAÇÃO / WELLNESS")
    linhas.append(f"HRV médio: {valor(rec.get('hrv_medio'))}")
    linhas.append(f"RHR médio: {valor(rec.get('rhr_medio'))}")
    linhas.append(f"Sono médio: {valor(rec.get('sono_medio_h'), ' h')}")
    linhas.append(f"Sleep score médio: {valor(rec.get('sono_score_medio'))}")
    linhas.append(f"Readiness médio: {valor(rec.get('readiness_medio'))}")
    linhas.append(f"Peso médio: {valor(rec.get('peso_medio'), ' kg')}")
    linhas.append(f"Passos médios: {valor(rec.get('passos_medio'))}")
    linhas.append(f"Stress médio: {valor(rec.get('stress_medio'))}")
    linhas.append(f"Body Battery médio: {valor(rec.get('body_battery_medio'))}")
    linhas.append(f"SpO2 médio: {valor(rec.get('spo2_medio'))}")
    linhas.append("")

    linhas.append("4. INDICADORES DERIVADOS")
    linhas.append(f"ACWR: {valor(ind.get('acwr'))}")
    linhas.append(f"Carga por dia: {valor(ind.get('carga_por_dia'))}")
    linhas.append(f"Carga por sessão: {valor(ind.get('carga_por_sessao'))}")
    linhas.append(f"Densidade treino: {valor(ind.get('densidade_treino'), ' sessão/dia')}")
    linhas.append(f"Dias ativos: {valor(ind.get('dias_ativos'))}")
    linhas.append(f"Dias off: {valor(ind.get('dias_off'))}")
    linhas.append(f"Dias ativos %: {valor(ind.get('dias_ativos_pct'), '%')}")
    linhas.append("")
    linhas.append("Distribuição da carga:")
    linhas.append(formatar_distribuicao(ind.get("distribuicao_carga_pct")))
    linhas.append("")
    linhas.append("Alerta de recuperação:")
    linhas.append(formatar_alerta(ind.get("alerta_recuperacao")))
    linhas.append("")

    linhas.append("5. DESTAQUES")
    linhas.append("Maior treino por carga:")
    linhas.append(formatar_treino_destaque(ind.get("maior_treino_carga")))
    linhas.append("")
    linhas.append("Maior treino por duração:")
    linhas.append(formatar_treino_destaque(ind.get("maior_treino_duracao")))
    linhas.append("")
    linhas.append("Maior treino por distância:")
    linhas.append(formatar_treino_destaque(ind.get("maior_treino_distancia")))
    linhas.append("")

    linhas.append("6. TREINOS POR MODALIDADE")

    grupos = {
        "🏊 Natação": [],
        "🚴 Bike": [],
        "🏃 Corrida": [],
        "🏋️ Força": [],
        "📌 Outros": []
    }

    for t in treinos:
        grupos[tipo_label(t.get("tipo"))].append(t)

    for grupo, lista in grupos.items():
        if not lista:
            continue

        linhas.append("")
        linhas.append(grupo)

        for t in lista:
            linhas.append(f"• {treino_linha(t)}")

    return "\n".join(linhas)

def limpar_vazios(obj):
    if isinstance(obj, dict):
        return {
            k: limpar_vazios(v)
            for k, v in obj.items()
            if v is not None and v != "" and v != [] and v != {}
        }

    if isinstance(obj, list):
        return [
            limpar_vazios(v)
            for v in obj
            if v is not None and v != "" and v != [] and v != {}
        ]

    return obj


def preparar_dados_relatorio(d):
    treinos = d.get("treinos", [])
    treinos_limpos = []

    for t in treinos:
        item = {
            "tipo": t.get("tipo"),
            "nome": t.get("nome"),
            "data": t.get("data"),
            "dist_km": t.get("dist_km"),
            "dur_min": t.get("dur_min"),
            "fc_med": t.get("fc_med"),
            "fc_max": t.get("fc_max"),
            "pace_min_km": t.get("pace_min_km"),
            "potencia_w": t.get("potencia_w"),
            "cadencia": round(t.get("cadencia"), 1) if t.get("cadencia") is not None else None,
            "carga_treino": t.get("carga_treino"),
            "intensidade": t.get("intensidade"),
            "trimp": t.get("trimp"),
            "ftp": t.get("ftp"),
            "lthr": t.get("lthr"),
            "hr_load": t.get("hr_load"),
            "power_load": t.get("power_load"),
            "comprimentos": t.get("comprimentos"),
            "comprimento_piscina": t.get("comprimento_piscina"),
        }

        treinos_limpos.append(limpar_vazios(item))

    dados = {
        "periodo": d.get("periodo"),
        "dias": d.get("dias"),
        "totais": d.get("totais"),
        "condicionamento": d.get("condicionamento"),
        "recuperacao": d.get("recuperacao"),
        "indicadores": d.get("indicadores"),
        "treinos": treinos_limpos,
    }

    return limpar_vazios(dados)
#------------------------------------------------------------------

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
Você é coach de endurance e cientista de dados de performance.

Analise os dados do período {d['periodo']}.

DADOS:
{json.dumps(preparar_dados_relatorio(d), ensure_ascii=False, default=str)}

REGRAS:
- Texto puro. Sem Markdown (**, --, ##).
- Máximo 3700 caracteres.
- Use os indicadores já calculados. Não recalcule.
- Não invente dado ausente.
- Não faça diagnóstico médico; use "maior risco de recuperação comprometida".
- Se alerta_recuperacao vier moderado/alto, recomende reduzir intensidade e priorizar sono.
- Priorize conclusão sobre descrição. Cada insight aparece uma vez.

INTERPRETAÇÕES FIXAS:
ACWR < 0.8 = subestímulo | 0.8-1.3 = controlado | 1.3-1.5 = atenção | >1.5 = risco de lesão
TSB positivo = descansado | negativo = carregado
CTL subindo = ganho de base | caindo = perda de tração
Monotonia/strain altos = risco de fadiga acumulada

MÉTRICAS A CORRELACIONAR (use todas disponíveis):
CTL, ATL, TSB, ACWR, monotonia, strain, carga_por_dia, carga_por_sessao, densidade_treino,
dias_ativos_pct, distribuição de carga, maior_treino_carga/duracao/distancia,
HRV/tendência HRV, RHR/tendência RHR, sono/tendência sono, readiness, body battery,
stress, VO2max, FTP/eFTP, razão carga corrida/bike, percentual sessões alta intensidade,
potência, cadência, TRIMP, pace_100m, DPS e SWOLF de natação.

📊 RESUMO DO PERÍODO
Volume por modalidade, carga total, sessões, distribuição e destaques.

🔗 CORRELAÇÕES
Conecte recuperação, carga e qualidade dos treinos. Identifique padrões.

🧠 CONDICIONAMENTO
Para cada métrica disponível em DADOS (CTL, ATL, TSB, ACWR, VO2max, FTP/eFTP,
monotonia, strain, tendências de HRV/sono/RHR, métricas de natação):
nível atual, tendência, impacto na performance e risco de lesão.

📈 TENDÊNCIAS
O que melhorou, piorou e principal gargalo.

⚠️ PONTO DE ATENÇÃO
Maior risco ou oportunidade. Sem termos diagnósticos.

🎯 RECOMENDAÇÃO
Ajuste prático para a próxima semana.

PRIORIDADE: 1. ponto forte | 2. gargalo | 3. risco | 4. ação prática
"""

    resposta = chamar_gpt_sync(
        [
            {"role": "system", "content": ESTILO_SOPHOS},
            {"role": "user", "content": prompt}
        ],
        model=MODEL_MAIN,
        max_tokens=4000,
        user_id=uid
    )

    context.user_data["ultima_resposta"] = resposta

    await enviar_texto_longo(
    context,
    update.effective_chat.id,
    "📊 Relatório de Performance:\n\n" + resposta,
    reply_markup=marcadores_feedback("relatorio")
    )

async def metricas_command(update, context):
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
                    "Formato inválido. Use:\n/metricas 7\nou\n/metricas 25/05/26 31/05/26"
                )
                return

    msg_status = (
        f"📊 Coletando métricas de {inicio} a {fim}..."
        if inicio and fim
        else f"📊 Coletando métricas dos últimos {dias} dias..."
    )

    await context.bot.send_message(update.effective_chat.id, msg_status)

    try:
        d = coletar_intervals(dias=dias, inicio=inicio, fim=fim)
    except Exception as e:
        print("Erro metricas:", e)
        await context.bot.send_message(
            update.effective_chat.id,
            "⚠️ Falha ao coletar métricas do Intervals.icu."
        )
        return

    texto = formatar_metricas(d)

    await enviar_texto_longo(
        context,
        update.effective_chat.id,
        texto
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

async def custos_command(update, context):
    uid = update.effective_user.id

    uso_data = ref.child(str(uid)).child("uso_tokens").get() or {}

    if not uso_data:
        await context.bot.send_message(
            update.effective_chat.id,
            "Nenhum registro de uso ainda."
        )
        return

    from datetime import datetime, timezone
    agora = datetime.now(timezone.utc)
    mes_atual = agora.strftime("%Y-%m")

    total_input = 0
    total_output = 0
    por_modelo = {}

    for entry in uso_data.values():
        if not isinstance(entry, dict):
            continue

        data_entry = entry.get("data", "")
        if not data_entry.startswith(mes_atual):
            continue

        modelo = entry.get("modelo", "desconhecido")
        inp = entry.get("input_tokens", 0)
        out = entry.get("output_tokens", 0)

        total_input += inp
        total_output += out

        if modelo not in por_modelo:
            por_modelo[modelo] = {"input": 0, "output": 0}
        por_modelo[modelo]["input"] += inp
        por_modelo[modelo]["output"] += out

    # Preços aproximados por 1M tokens (ajuste conforme sua conta)
    PRECOS = {
        "gpt-5": {"input": 1.25, "output": 10.00},
        "gpt-5-mini": {"input": 0.25, "output": 2.00},
        "gpt-5.4": {"input": 2.50, "output": 15.00},
        "gpt-5.4-mini": {"input": 0.75, "output": 4.50}
    }

    custo_total = 0.0
    linhas = [f"💰 Uso de tokens — {mes_atual}\n"]

    for modelo, uso in por_modelo.items():
        preco = PRECOS.get(modelo, {"input": 2.50, "output": 10.00})
        custo_inp = uso["input"] / 1_000_000 * preco["input"]
        custo_out = uso["output"] / 1_000_000 * preco["output"]
        custo_mod = custo_inp + custo_out
        custo_total += custo_mod

        linhas.append(
            f"{modelo}\n"
            f"  Input:  {uso['input']:,} tokens\n"
            f"  Output: {uso['output']:,} tokens\n"
            f"  Custo:  ~US$ {custo_mod:.4f}\n"
        )

    linhas.append(f"\nTotal estimado: ~US$ {custo_total:.4f}")
    linhas.append(f"({total_input + total_output:,} tokens no mês)")

    await context.bot.send_message(
        update.effective_chat.id,
        "\n".join(linhas)
    )

async def comandos(update, context):
    msg = (
        "📌 Comandos disponíveis:\n"
        "/start — iniciar\n"
        "/relatorio <dias> — relatório de performance\n"
        "/relatorio <xx/xx/xx xx/xx/xx> — relatório por período\n"
        "/metricas <dias ou período> — envia apenas métricas brutas, sem análise\n"
        "/processar_arquivo <instrução> — processar último arquivo pendente\n"
        "/custos — uso e custo estimado do mês\n"
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

def escolher_modelo(texto: str) -> str:
    t = texto.lower().strip()

    gatilhos_complexos = [
        "analise", "analisa", "avaliar", "avalie",
        "compare", "comparar",
        "estratégia", "decisão", "risco",
        "investimento", "contrato", "carreira",
        "relatório", "suplemento",
        "código", "corrija", "erro", "bug",
        "projeto", "planejamento",
        "jurídico", "financeiro",
    ]

    if any(g in t for g in gatilhos_complexos):
        return MODEL_MAIN

    if len(t) < 300:
        return MODEL_FAST

    return MODEL_MAIN

def deve_buscar_memoria(texto: str) -> bool:
    t = texto.lower().strip()

    if len(t) < 80:
        return False

    gatilhos = [
        "lembra", "lembrar", "com base",
        "histórico", "antes", "já falei",
        "minha rotina", "meu treino", "meus dados",
        "minha carteira", "meu filho", "sophos",
        "meu trabalho", "minha dieta"
    ]

    return any(g in t for g in gatilhos)

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

    sem_ctx = []
    if deve_buscar_memoria(texto_original):
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
        r = chamar_gpt_sync(messages, model=escolher_modelo(texto_original), user_id=user_id)    
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

def analisar_imagem_com_ia(temp_path, instrucao="Analise esta imagem."):
    modelo = MODEL_MAIN if "modo avançado" in (instrucao or "").lower() else MODEL_FAST

    with open(temp_path, "rb") as img:
        base64_image = base64.b64encode(img.read()).decode("utf-8")

    prompt = f"""
Instrução do usuário:
{instrucao}

Analise esta imagem de forma prática.

Faça:
1. Extração de textos visíveis
2. Identificação de números, tabelas ou dados
3. Resumo do conteúdo
4. Pontos importantes
5. Riscos, erros ou inconsistências
6. Ações recomendadas, se aplicável

Se for print de treino, dashboard, planilha, contrato, conversa ou documento, adapte a análise ao contexto.
"""

    resp = client.chat.completions.create(
        model=modelo,
        messages=[   
            {"role": "system", "content": ESTILO_SOPHOS},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        max_completion_tokens=1200
    )

    return resp.choices[0].message.content or ""

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
    nome = (file_name or temp_path or "").lower()

    # IMAGENS: usa IA visual, não OCR local
    if nome.endswith((".png", ".jpg", ".jpeg", ".webp")):
        try:
            resposta = analisar_imagem_com_ia(temp_path, instrucao)
        except Exception as e:
            print("Erro análise imagem IA:", e)
            await context.bot.send_message(
                update.effective_chat.id,
                "⚠️ Falha ao analisar a imagem com IA."
            )
            return

        context.user_data["ultima_resposta"] = resposta

        await enviar_texto_longo(
            context,
            update.effective_chat.id,
            "🖼️ Análise da imagem:\n\n" + resposta,
            reply_markup=marcadores_feedback("imagem")
        )
        return

    # DOCUMENTOS: mantém extração tradicional
    extracted_text = extrair_texto_arquivo(temp_path, file_name=file_name)

    if not extracted_text:
        context.user_data["ultimo_arquivo_temp"] = temp_path
        context.user_data["ultimo_arquivo_nome"] = file_name

        await context.bot.send_message(
            update.effective_chat.id,
            "Não consegui extrair texto automaticamente. Use /processar_arquivo <instrução> para tentar novamente."
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
    app.add_handler(CommandHandler("metricas", metricas_command))
    app.add_handler(CommandHandler("processar_arquivo", processar_ultimo_arquivo_cmd))
    app.add_handler(CommandHandler("custos", custos_command))

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
