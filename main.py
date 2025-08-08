# sophos_v14_gpt5.py
# V14 atualizado: GPT-5 + leitura de imagens e documentos (PDF/DOCX/XLSX/PNG/JPG)
# Requisitos (sugestão): python-telegram-bot[job-queue,webhooks]==22, openai, firebase-admin, pinecone-client,
# pandas, PyPDF2, python-docx, python-pptx (opcional), pillow, pytesseract (opcional), reportlab
# Ajuste variáveis de ambiente: TOKEN_TELEGRAM, OPENAI_API_KEY, FIREBASE_CRED_JSON, PINECONE_API_KEY, PINECONE_ENVIRONMENT, BOT_URL

import os
import re
import json
from datetime import datetime, timedelta
import pandas as pd
import pytz
import aiofiles
import threading
import openai
import firebase_admin
from pinecone import Pinecone, ServerlessSpec
from telegram import InputFile, InlineKeyboardButton, InlineKeyboardMarkup, Update, Document
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from openai import OpenAI
from firebase_admin import credentials, db
import unicodedata
import io
import tempfile
import sys
import traceback

# → extras para leitura de arquivos/imagens (tentamos com libs locais; se não existirem, caímos para fallback)
try:
    from PyPDF2 import PdfReader
except Exception:
    PdfReader = None

try:
    import docx  # python-docx
except Exception:
    docx = None

try:
    import pytesseract
    from PIL import Image
except Exception:
    pytesseract = None
    Image = None

# ---------------- utilidades ----------------
def remover_acentos(texto):
    return unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')

def escapar_markdown_v2(texto: str) -> str:
    # usado para enviar MarkdownV2 seguro
    if not isinstance(texto, str):
        texto = str(texto)
    chars = r'\_*[]()~`>#+-=|{}.!'
    return "".join(f"\\{c}" if c in chars else c for c in texto)

# ---------------- CONFIG ----------------
HISTORY_LIMIT = 5
SUMMARY_KEY = "resumo_anterior"

ESTILO_SOPHOS = (
    "Seu usuário é disciplinado, estoico, direto, cético e não tolera respostas evasivas. "
    "Responda na lata, prático, técnico quando necessário, com humor rápido e sagaz ocasional. "
    "Priorize instruções acionáveis e dados concretos. Seja crítico e proponha cortes quando algo é desnecessário. "
)

# TOKENs / clientes
TOKEN = os.environ.get("TOKEN_TELEGRAM")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)

# Firebase
FIREBASE_URL = os.environ.get("FIREBASE_URL", "https://sophos-ddbed-default-rtdb.firebaseio.com")
cred_dict = json.loads(os.environ["FIREBASE_CRED_JSON"])
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_URL})
ref = db.reference("/usuarios")

# Pinecone
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_ENVIRONMENT = os.environ.get("PINECONE_ENVIRONMENT")
pc = Pinecone(api_key=PINECONE_API_KEY, spec=ServerlessSpec(cloud="gcp", region=PINECONE_ENVIRONMENT))
if "sophos-memoria" not in pc.list_indexes().names():
    pc.create_index(name="sophos-memoria", dimension=1536, metric="cosine", spec=ServerlessSpec(cloud="gcp", region=PINECONE_ENVIRONMENT))
vec_index = pc.Index("sophos-memoria")

EMOCOES = ["ansioso", "animado", "cansado", "focado", "triste", "feliz", "nervoso", "motivado"]
TEMAS = ["investimento", "treino", "relacionamento", "espiritualidade", "saúde", "trabalho"]

# ---------------- FUNCOES DE BANCO ----------------
def inicializar_usuario(user_id):
    user_ref = ref.child(str(user_id))
    if not user_ref.get():
        user_ref.set({"init": {"timestamp": datetime.now().isoformat()}})
    for sub in ["contexto","memoria","emocao","temas","score_emocional","feedback_respostas","perfil"]:
        if not user_ref.child(sub).get():
            user_ref.child(sub).set({})

def salvar_dado(user_id, tipo, valor):
    ref.child(str(user_id)).child(tipo).push({"valor": valor, "data": datetime.now().isoformat()})

def salvar_por_tema(user_id, tema, texto):
    ref.child(str(user_id)).child("temas").child(tema).push({"texto": texto, "data": datetime.now().isoformat()})

def salvar_emocao_por_tema(user_id, tema, emocao):
    ref.child(str(user_id)).child("score_emocional").child(tema).push({"emocao": emocao, "data": datetime.now().isoformat()})

def registrar_feedback(user_id, tipo_resposta, feedback, texto_resposta):
    ref.child(str(user_id)).child("feedback_respostas").push({"tipo": tipo_resposta, "feedback": feedback, "resposta": texto_resposta, "data": datetime.now().isoformat()})

def salvar_memoria_relativa(user_id, chave, valor):
    ref.child(str(user_id)).child("memoria").child(chave).set(valor)

def obter_dados(user_id, tipo):
    return ref.child(str(user_id)).child(tipo).get() or {}

def buscar_por_tema(user_id, tema):
    d = ref.child(str(user_id)).child("temas").child(tema).get()
    return [x["texto"] for x in d.values()] if d else []

def salvar_contexto(user_id, texto):
    contexto = ref.child(str(user_id)).child("contexto").get() or {}
    ultimos = [v["texto"] for v in contexto.values() if isinstance(v, dict)]
    if ultimos and texto.strip() == ultimos[-1].strip():
        return
    ref.child(str(user_id)).child("contexto").push({"texto": texto, "data": datetime.now().isoformat()})

def recuperar_contexto(user_id, limite=HISTORY_LIMIT):
    resumo_node = ref.child(str(user_id)).child(SUMMARY_KEY).get() or {}
    partes = []
    if resumo_node.get("texto"):
        partes.append(f"Resumo anterior: {resumo_node['texto']}")
    d = ref.child(str(user_id)).child("contexto").get() or {}
    ult = list(d.values())[-limite:]
    for x in ult:
        if 'texto' in x:
            partes.append(f"Usuário: {x['texto']}")
    return "\n".join(partes)

def recuperar_memoria(user_id):
    m = ref.child(str(user_id)).child("memoria")
    if not m.get():
        m.set({})
    return m.get() or {}

# ---------------- GPT-5 helpers ----------------
def chamar_gpt5_sync(messages, temperature=0.0, max_tokens=1500):
    """
    Chamada síncrona simplificada ao GPT-5 via cliente OpenAI.
    """
    resp = client.chat.completions.create(
        model="gpt-5",
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return resp.choices[0].message.content

def extrair_memoria_com_gpt(user_id: int, texto: str) -> dict:
    prompt = (
        "Extraia do texto os fatos concisos e úteis para lembrar no futuro. "
        "Retorne apenas um JSON plano, sem comentários. Exemplo: {\"filho\":\"Isaac\",\"profissao\":\"engenheiro\"}\n\n"
        f"Texto: {texto}"
    )
    try:
        resp_text = chamar_gpt5_sync([{"role":"user","content":prompt}], temperature=0.0, max_tokens=400)
        return json.loads(resp_text)
    except Exception:
        return {}

async def resumir_contexto_antigo(user_id):
    caminho = ref.child(str(user_id)).child("contexto")
    todas = caminho.get() or {}
    textos = [x["texto"] for x in todas.values() if isinstance(x, dict)]
    if len(textos) <= HISTORY_LIMIT:
        return
    antigas = textos[:-HISTORY_LIMIT]
    prompt = "Resuma brevemente o seguinte histórico de conversas, destacando apenas fatos úteis:\n\n" + "\n".join(antigas)
    try:
        resumo = chamar_gpt5_sync([{"role":"system","content":ESTILO_SOPHOS},{"role":"user","content":prompt}], temperature=0.0, max_tokens=600)
        ref.child(str(user_id)).child(SUMMARY_KEY).set({"texto": resumo, "data": datetime.now().isoformat()})
        for key in list(todas.keys())[:-HISTORY_LIMIT]:
            caminho.child(key).delete()
    except Exception as e:
        print("Erro ao resumir contexto:", e)

# ---------------- Data detection ----------------
def detectar_data_hoje(texto):
    match = re.search(r"hoje\s+(é\s+dia\s+|é\s+)?(\d{1,2}/\d{1,2}/\d{2,4})", texto)
    if not match:
        return None
    data_str = match.group(2)
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(data_str, fmt).date().isoformat()
        except:
            continue
    return None

# ---------------- Perfil (mantido por compatibilidade) ----------------
def definir_perfil_usuario(user_id):
    emo_data = obter_dados(user_id, "emocao")
    tema_data = obter_dados(user_id, "score_emocional")
    freq = {}
    for e in emo_data.values():
        freq[e["valor"]] = freq.get(e["valor"], 0) + 1
    tema_freq = { tema: len(entries) for tema, entries in (tema_data or {}).items() }
    perfil = "equilibrado"
    if freq.get("triste", 0) > freq.get("feliz", 0):
        perfil = "sensível empático"
    elif freq.get("focado", 0) > freq.get("cansado", 0):
        perfil = "estoico racional"
    elif tema_freq.get("espiritualidade", 0) > tema_freq.get("trabalho", 0):
        perfil = "visionário reflexivo"
    ref.child(str(user_id)).child("perfil").set({"tipo": perfil, "data": datetime.now().isoformat()})
    return perfil

# ---------------- Análise semanal (job) ----------------
async def analisar_padroes(context: ContextTypes.DEFAULT_TYPE):
    hoje = datetime.utcnow().date()
    semana_atras = hoje - timedelta(days=7)
    usuarios = ref.get() or {}
    for uid_str, dados in usuarios.items():
        emoc_entries = ref.child(uid_str).child("emocao").get() or {}
        cont_emoc = {}
        for e in emoc_entries.values():
            try:
                data = datetime.fromisoformat(e["data"]).date()
            except:
                continue
            if data >= semana_atras:
                cont_emoc[e["valor"]] = cont_emoc.get(e["valor"], 0) + 1
        humor_predominante = max(cont_emoc, key=cont_emoc.get) if cont_emoc else None
        tema_entries = ref.child(uid_str).child("temas").get() or {}
        cont_tema = {}
        for tema, msgs in (tema_entries or {}).items():
            for m in msgs.values():
                try:
                    data = datetime.fromisoformat(m["data"]).date()
                except:
                    continue
                if data >= semana_atras:
                    cont_tema[tema] = cont_tema.get(tema, 0) + 1
        pad = {"de": semana_atras.isoformat(), "ate": hoje.isoformat(), "emocoes": cont_emoc, "temas": cont_tema, "humor_predominante": humor_predominante}
        ref.child(uid_str).child("padroes_semanais").set(pad)

# ---------------- Exportar ----------------
async def exportar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    dados = ref.child(str(user_id)).get()
    if not dados:
        await context.bot.send_message(update.effective_chat.id, "⚠️ Nenhum dado encontrado.")
        return
    registros = []
    for tipo, entradas in dados.items():
        if isinstance(entradas, dict):
            for e in entradas.values():
                if isinstance(e, dict):
                    v = e.get("valor") or e.get("texto") or e.get("emocao")
                    if v:
                        registros.append({"tipo": tipo, "valor": v, "data": e.get("data", "")})
    if not registros:
        await context.bot.send_message(update.effective_chat.id, "⚠️ Nenhum registro válido.")
        return
    df = pd.DataFrame(registros)
    excel_path = f"sophos_{user_id}.xlsx"
    txt_path = f"sophos_{user_id}.txt"
    df.to_excel(excel_path, index=False)
    df.to_csv(txt_path, index=False, sep="\t")
    import aiofiles
    for path in (excel_path, txt_path):
        async with aiofiles.open(path, "rb") as f:
            data = await f.read()
            await context.bot.send_document(chat_id=update.effective_chat.id, document=InputFile(data, filename=os.path.basename(path)))

# ---------------- Feedback inline ----------------
async def feedback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await q.edit_message_reply_markup(None)
    await q.message.reply_text("✅ Feedback registrado. Obrigado!")

def marcadores_feedback(tipo):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👍", callback_data=f"{tipo}:like"),
        InlineKeyboardButton("👎", callback_data=f"{tipo}:dislike")
    ]])

# ---------------- Comandos simples ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    inicializar_usuario(uid)
    await context.bot.send_message(update.effective_chat.id, "👋 Olá! Eu sou o Sophos. Pronto pra te ouvir e evoluir contigo 🧠")

async def comandos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📌 *Comandos disponíveis:*\n"
        "/start — iniciar conversa\n"
        "/perfil — ver perfil\n"
        "/resumo — resumo emocional\n"
        "/consultar <tema> — histórico por tema\n"
        "/resumir <texto> — gerar resumo\n"
        "/conselheiro — conselho emocional\n"
        "/padroes — padrões semanais\n"
        "/exportar — backup (Excel/TXT)\n"
        "/comandos — mostrar este menu"
    )
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="MarkdownV2")

async def perfil_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    perfil = ref.child(str(user_id)).child("perfil").get()
    if not perfil:
        perfil_tipo = definir_perfil_usuario(user_id)
    else:
        perfil_tipo = perfil.get("tipo", "desconhecido")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🧩 Seu perfil atual: *{perfil_tipo}*", parse_mode="Markdown")

async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    d = obter_dados(uid, "emocao")
    if not d:
        await context.bot.send_message(update.effective_chat.id, "Nenhuma emoção registrada.")
        return
    cnt = {}
    for e in d.values():
        cnt[e["valor"]] = cnt.get(e["valor"], 0) + 1
    texto = "📊 Resumo emocional:\n" + "\n".join(f"- {k}: {v}x" for k, v in cnt.items())
    await context.bot.send_message(update.effective_chat.id, texto)

# ---------------- Padrões semanais view ----------------
async def padroes_semanais_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    dados = ref.child(str(uid)).child("padroes_semanais").get() or {}
    if not dados:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="🔍 Ainda não há análise semanal disponível. Tente novamente mais tarde.", parse_mode="Markdown")
        return
    humor = dados.get("humor_predominante", "-")
    emocoes = ", ".join(f"{k}: {v}" for k, v in dados.get("emocoes", {}).items())
    temas = ", ".join(f"{k}: {v}" for k, v in dados.get("temas", {}).items())
    texto = (f"*📅 Padrões de {dados['de']} até {dados['ate']}*\n\n"
             f"🧠 Humor predominante: {humor}\n"
             f"🧠 Emoções: {emocoes}\n"
             f"📂 Temas: {temas}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=texto, parse_mode="Markdown")

# ---------------- Conselheiro / Resumir ----------------
async def conselheiro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    d = obter_dados(uid, "emocao")
    if not d or len(d) < 3:
        await context.bot.send_message(update.effective_chat.id, "Poucos dados pra gerar conselho.")
        return
    prompt = "Com base nas emoções recentes:\n" + "\n".join(f"- {e['data'][:10]}: {e['valor']}" for e in list(d.values())[-7:]) + "\nMe dê um conselho prático e direto."
    try:
        r = chamar_gpt5_sync([{"role":"system","content":ESTILO_SOPHOS},{"role":"user","content":prompt}], temperature=0.2, max_tokens=400)
    except Exception:
        r = "⚠️ Erro ao gerar conselho."
    context.user_data["ultima_resposta"] = r
    await context.bot.send_message(update.effective_chat.id, "📜 " + r, reply_markup=marcadores_feedback("conselheiro"))

async def consultar_tema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args:
        await context.bot.send_message(update.effective_chat.id, "Ex: /consultar treino")
        return
    t = context.args[0].lower()
    msgs = buscar_por_tema(uid, t)
    if not msgs:
        await context.bot.send_message(update.effective_chat.id, f"Nenhum registro de '{t}'")
        return
    texto = "📂 Últimos sobre '%s':\n%s" % (t, "\n".join(msgs[-5:]))
    await context.bot.send_message(update.effective_chat.id, texto)

async def resumir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await context.bot.send_message(update.effective_chat.id, "Ex: /resumir <texto>")
        return
    orig = " ".join(context.args)
    try:
        r = chamar_gpt5_sync([{"role":"system","content":ESTILO_SOPHOS},{"role":"user","content":f"Resuma de forma prática e direta:\n\n{orig}"}], temperature=0.0, max_tokens=300)
    except Exception:
        r = "⚠️ Erro ao resumir."
    context.user_data["ultima_resposta"] = r
    await context.bot.send_message(update.effective_chat.id, "📝 " + r, reply_markup=marcadores_feedback("resumir"))

# ---------------- Voz (transcrição) ----------------
async def voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    f = await update.message.voice.get_file()
    path = f"voz_{uid}.ogg"
    await f.download_to_drive(path)
    with open(path, "rb") as af:
        tr = client.audio.transcriptions.create(model="whisper-1", file=af)
    texto = tr.text.lower()
    await context.bot.send_message(update.effective_chat.id, f"🗣️ Você disse: {texto}")
    await processar_texto(uid, texto, update, context)

# ---------------- Busca semântica ----------------
async def buscar_contexto_semantico(user_id: int, texto: str, top_k: int = 5) -> list:
    emb = client.embeddings.create(model="text-embedding-3-small", input=texto)
    res = vec_index.query(vector=emb.data[0].embedding, top_k=top_k, include_metadata=False)
    fragmentos = []
    for match in res.matches:
        if match.id.startswith(f"{user_id}:"):
            _, chave = match.id.split(":", 1)
            val = ref.child(str(user_id)).child("memoria").child(chave).get()
            if val:
                fragmentos.append(f"{chave}: {val}")
    return fragmentos

# ---------------- Processamento de texto principal ----------------
async def processar_texto(user_id, texto, update: Update, context: ContextTypes.DEFAULT_TYPE):
    await resumir_contexto_antigo(user_id)
    inicializar_usuario(user_id)
    fb = ref.child(str(user_id)).child("feedback_respostas").get() or {}
    likes = sum(1 for e in fb.values() if e.get("feedback") == "like")
    dislikes = sum(1 for e in fb.values() if e.get("feedback") == "dislike")
    if likes > dislikes + 5:
        estilo_dinamico = "Prefira respostas sucintas e diretas."
    elif dislikes > likes + 5:
        estilo_dinamico = "Adote um tom mais explicativo e didático."
    else:
        estilo_dinamico = None
    salvar_contexto(user_id, texto)
    memoria_nova = extrair_memoria_com_gpt(user_id, texto)
    for chave, valor in memoria_nova.items():
        atual = ref.child(str(user_id)).child("memoria").child(chave).get()
        if atual != valor:
            salvar_memoria_relativa(user_id, chave, valor)
            texto_para_emb = f"{chave}: {valor}"
            emb = client.embeddings.create(model="text-embedding-3-small", input=texto_para_emb)
            chave_ascii = remover_acentos(chave)
            vec_index.upsert([(f"{user_id}:{chave_ascii}", emb.data[0].embedding)])
    dhoje = detectar_data_hoje(texto)
    if dhoje:
        salvar_memoria_relativa(user_id, "data_atual", dhoje)
        await context.bot.send_message(update.effective_chat.id, f"📅 Data registrada: {dhoje}")
    for emo in EMOCOES:
        if emo in texto:
            salvar_dado(user_id, "emocao", emo)
            await context.bot.send_message(update.effective_chat.id, f"🧠 Emoção '{emo}' registrada.")
            for t in TEMAS:
                if t in texto:
                    salvar_emocao_por_tema(user_id, t, emo)
            break
    for t in TEMAS:
        if t in texto:
            salvar_por_tema(user_id, t, texto)
            break
    cont = recuperar_contexto(user_id)
    mem = recuperar_memoria(user_id)
    perfil = ref.child(str(user_id)).child("perfil").get() or {}
    perfil_tipo = perfil.get("tipo", "")
    base = cont
    if mem:
        base += "\n\nLembrar:\n" + "\n".join(f"- {k}: {v}" for k, v in mem.items())
    if perfil_tipo:
        base += f"\n\nPerfil: {perfil_tipo}"
    sem_ctx = await buscar_contexto_semantico(user_id, texto)
    if sem_ctx:
        base += "\n\n🔍 Contexto relevante:\n" + "\n".join(f"- {f}" for f in sem_ctx)
    prompt = f"{base}\n\nUsuário disse:\n{texto}"
    messages = [{"role":"system", "content": ESTILO_SOPHOS}]
    if estilo_dinamico:
        messages.append({"role":"system", "content": estilo_dinamico})
    messages.append({"role":"user", "content": prompt})
    try:
        r = chamar_gpt5_sync(messages, temperature=0.2, max_tokens=700)
    except Exception as e:
        print("❌ Erro na chamada OpenAI:", str(e))
        r = "⚠️ Erro ao gerar resposta. Tente novamente mais tarde."
    context.user_data["ultima_resposta"] = r
    await context.bot.send_message(update.effective_chat.id, r, reply_markup=marcadores_feedback("geral"))

async def mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text.lower()
    print("🔔 Chegou texto:", update.message.text)
    await processar_texto(uid, txt, update, context)

# ---------------- Estatísticas (corrigido) ----------------
async def estatisticas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    fb = ref.child(str(uid)).child("feedback_respostas").get() or {}
    resumo = {}
    for e in fb.values():
        if not all(k in e for k in ["resposta", "feedback"]):
            continue
        resumo.setdefault(e["resposta"], {"like":0,"dislike":0})[e["feedback"]] += 1
    linhas = ["📊 Suas estatísticas de feedback:"]
    if resumo:
        for txt, cnt in resumo.items():
            safe_txt = escapar_markdown_v2(txt)
            linhas.append(f"- {safe_txt} (👍 {cnt['like']} | 👎 {cnt['dislike']})")
    else:
        linhas.append("Nenhum feedback registrado ainda.")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(linhas), parse_mode="MarkdownV2")

# ---------------- Leitura de mídias (photos/docs) ----------------
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Trata fotos e documentos. Tenta extrair texto localmente.
    Suporta: PDF, DOCX, XLSX, PNG, JPG.
    Se extracao falhar, pede pro usuario explicar o que deseja.
    """
    uid = update.effective_user.id
    file_obj = None
    file_name = None
    temp_path = None
    try:
        # foto(s)
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
        # download para temp
        fd, temp_path = tempfile.mkstemp(suffix=os.path.splitext(file_name)[1] if file_name else "")
        os.close(fd)
        await file_obj.download_to_drive(temp_path)
        await context.bot.send_message(update.effective_chat.id, "📥 Arquivo recebido. Processando...")
        extracted_text = ""
        # PDF
        if temp_path.lower().endswith(".pdf") and PdfReader:
            try:
                reader = PdfReader(temp_path)
                pages = []
                for p in reader.pages:
                    try:
                        pages.append(p.extract_text() or "")
                    except:
                        continue
                extracted_text = "\n".join(pages).strip()
            except Exception as e:
                print("Erro extraindo PDF:", e)
        # DOCX
        elif temp_path.lower().endswith(".docx") and docx:
            try:
                doc = docx.Document(temp_path)
                extracted_text = "\n".join(p.text for p in doc.paragraphs).strip()
            except Exception as e:
                print("Erro extraindo DOCX:", e)
        # XLSX (simple: convert first sheet to text table)
        elif temp_path.lower().endswith((".xls", ".xlsx")):
            try:
                df = pd.read_excel(temp_path, dtype=str)
                extracted_text = df.fillna("").to_csv(sep="\t", index=False)
            except Exception as e:
                print("Erro extraindo XLSX:", e)
        # Imagens: OCR se pytesseract disponível
        elif temp_path.lower().endswith((".png", ".jpg", ".jpeg")) and pytesseract and Image:
            try:
                img = Image.open(temp_path)
                extracted_text = pytesseract.image_to_string(img)
            except Exception as e:
                print("Erro OCR:", e)
        else:
            # fallback: se for imagem mas sem OCR, ou formato não tratado
            extracted_text = ""
        # se não extraiu texto, tenta perguntar ao modelo pedindo descrição da imagem (modo multimodal NÃO garantido)
        if not extracted_text:
            # pedimos ao usuário confirmar o que quer que seja feito com o arquivo
            await context.bot.send_message(update.effective_chat.id,
                                           "Não consegui extrair texto automaticamente deste arquivo. Diga em uma frase o que você quer que eu faça com ele (resumir, analisar, checar dados, etc).")
            # salva o caminho temporário para uso posterior se o usuário pedir (padrão: apaga depois)
            context.user_data["ultimo_arquivo_temp"] = temp_path
            return
        # geramos análise via GPT-5
        prompt = (f"Recebi um arquivo enviado pelo usuário. Extraí o seguinte texto:\n\n{extracted_text[:3000]}\n\n"
                  "Faça uma análise prática e direta: resuma os pontos principais, identifique dados/valores relevantes, riscos/erros e proponha ações práticas.")
        try:
            resposta = chamar_gpt5_sync([{"role":"system","content":ESTILO_SOPHOS},{"role":"user","content":prompt}], temperature=0.0, max_tokens=800)
        except Exception:
            resposta = "⚠️ Erro ao analisar o documento via GPT-5."
        context.user_data["ultima_resposta"] = resposta
        await context.bot.send_message(update.effective_chat.id, "📄 Análise:\n" + resposta, reply_markup=marcadores_feedback("documento"))
    except Exception as e:
        print("Erro handle_media:", e)
        traceback.print_exc(file=sys.stdout)
        await context.bot.send_message(update.effective_chat.id, "⚠️ Falha ao processar o arquivo.")
    finally:
        # não apagar o temp se guardado para ação posterior; se guardado em user_data é intencional
        if temp_path and not context.user_data.get("ultimo_arquivo_temp") == temp_path:
            try:
                os.remove(temp_path)
            except:
                pass

# ---------------- Comando para processar último arquivo (caso o bot tenha pedido contexto) ----------------
async def processar_ultimo_arquivo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    temp_path = context.user_data.get("ultimo_arquivo_temp")
    if not temp_path or not os.path.exists(temp_path):
        await context.bot.send_message(update.effective_chat.id, "Nenhum arquivo pendente encontrado.")
        return
    # usuário deu instrução após upload, pegamos a mensagem textual dele
    instr = " ".join(context.args) if context.args else ""
    if not instr:
        await context.bot.send_message(update.effective_chat.id, "Diga o que quer que eu faça com o arquivo: resumir/analisar/validar/extrair dados.")
        return
    # tenta reusar handle_media extraction logic by reading file type
    extracted_text = ""
    try:
        if temp_path.lower().endswith(".pdf") and PdfReader:
            reader = PdfReader(temp_path)
            pages = [p.extract_text() or "" for p in reader.pages]
            extracted_text = "\n".join(pages).strip()
        elif temp_path.lower().endswith(".docx") and docx:
            doc = docx.Document(temp_path)
            extracted_text = "\n".join(p.text for p in doc.paragraphs).strip()
        elif temp_path.lower().endswith((".xls", ".xlsx")):
            df = pd.read_excel(temp_path, dtype=str)
            extracted_text = df.fillna("").to_csv(sep="\t", index=False)
        elif temp_path.lower().endswith((".png", ".jpg", ".jpeg")) and pytesseract and Image:
            img = Image.open(temp_path)
            extracted_text = pytesseract.image_to_string(img)
    except Exception as e:
        print("Erro re-extraindo:", e)
    if not extracted_text:
        await context.bot.send_message(update.effective_chat.id, "Não consegui extrair texto automaticamente deste arquivo mesmo agora.")
        return
    prompt = (f"Recebi um arquivo e extraí este texto:\n\n{extracted_text[:3000]}\n\n"
              f"Instrução do usuário: {instr}\n\nResponda de forma prática e direta.")
    try:
        resposta = chamar_gpt5_sync([{"role":"system","content":ESTILO_SOPHOS},{"role":"user","content":prompt}], temperature=0.0, max_tokens=800)
    except Exception:
        resposta = "⚠️ Erro ao analisar o documento via GPT-5."
    await context.bot.send_message(update.effective_chat.id, "📄 Resultado:\n" + resposta, reply_markup=marcadores_feedback("documento"))
    # cleanup
    try:
        os.remove(temp_path)
    except:
        pass
    context.user_data.pop("ultimo_arquivo_temp", None)

# ---------------- Handlers registration e main ----------------
def main():
    BOT_URL = os.environ.get("BOT_URL")
    WEBHOOK_PATH = f"/{TOKEN}"
    WEBHOOK_URL = f"{BOT_URL}{WEBHOOK_PATH}"
    app = ApplicationBuilder().token(TOKEN).build()
    # job queue
    app.job_queue.run_repeating(analisar_padroes, interval=timedelta(days=7), first=0)
    # comandos
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
    app.add_handler(CommandHandler("processar_arquivo", processar_ultimo_arquivo_cmd))  # /processar_arquivo <acao>
    app.add_handler(CallbackQueryHandler(feedback_handler))
    app.add_handler(MessageHandler(filters.VOICE, voz))
    # mensagens textuais (normais)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), mensagem))
    # mídia: fotos e docs
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.ALL) & (~filters.COMMAND), handle_media))
    # inicia webhook (Render-style)
    app.run_webhook(listen="0.0.0.0",
                    port=int(os.environ.get("PORT", 3000)),
                    url_path=TOKEN,
                    webhook_url=WEBHOOK_URL)

if __name__ == "__main__":
    main()
