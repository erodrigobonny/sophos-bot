# V13 – Etapa 4
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
from telegram import InputFile, InlineKeyboardButton, InlineKeyboardMarkup
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
from flask import Flask, request

# ── CONFIGURAÇÕES ────────────────────────────────────────────────────────────────

# quantas mensagens do histórico manter “cruas”
HISTORY_LIMIT = 10

# campo no Firebase onde guardamos o resumo das mensagens mais antigas
SUMMARY_KEY = "resumo_anterior"

# estilo padrão do bot
ESTILO_SOPHOS = "Você é um filósofo estoico, visão tradicional, sagaz, firme, humor rápido, proativo, direto e analítico, mas com alma de engenheiro. Nada de papo furado."
# 2) Instruções de “role system” para lembrar perfil e contexto:
#ROLE_PROMPT = (
    #"Siga estritamente o perfil do usuário ao formular respostas, "
    #"referenciando sempre as emoções e temas já registrados no histórico."

#TOKEN
TOKEN = os.environ.get("TOKEN_TELEGRAM")
#import openai
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)
#firebase
FIREBASE_URL = "https://sophos-ddbed-default-rtdb.firebaseio.com"
cred_dict = json.loads(os.environ["FIREBASE_CRED_JSON"])
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred, {
    'databaseURL': FIREBASE_URL
})
ref = db.reference("/usuarios")
#webhook
flask_app = Flask(__name__)
BOT_URL = os.environ.get("BOT_URL")
WEBHOOK_PATH = f"/{TOKEN}"
WEBHOOK_URL = f"{BOT_URL}{WEBHOOK_PATH}"


EMOCOES = ["ansioso", "animado", "cansado", "focado", "triste", "feliz", "nervoso", "motivado"]
TEMAS   = ["investimento", "treino", "relacionamento", "espiritualidade", "saúde", "trabalho"]

#____ ETAPA 4: FUNÇÃO DE ANÁLISE SEMANAL__________________________
async def analisar_padroes(context: ContextTypes.DEFAULT_TYPE):
    """
    Será executado a cada 7 dias pelo JobQueue.
    Calcula, para cada usuário, quais temas e emoções foram mais/menos frequentes
    na última semana e grava em /padroes_semanais no Firebase.
    """
    hoje = datetime.utcnow().date()
    semana_atras = hoje - timedelta(days=7)

    usuarios = ref.get() or {}
    for uid_str, dados in usuarios.items():
        #uid = int(uid_str)
        # 1) emoções na última semana
        emoc_entries = ref.child(uid_str).child("emocao").get() or {}
        cont_emoc = {}
        for e in emoc_entries.values():
            data = datetime.fromisoformat(e["data"]).date()
            if data >= semana_atras:
                cont_emoc[e["valor"]] = cont_emoc.get(e["valor"], 0) + 1
            # escolhe a emoção com maior frequência
        if cont_emoc:
            humor_predominante = max(cont_emoc, key=cont_emoc.get)
        else:
            humor_predominante = None
                
        # 2) temas na última semana
        tema_entries = ref.child(uid_str).child("temas").get() or {}
        cont_tema = {}
        for tema, msgs in tema_entries.items():
            for m in msgs.values():
                data = datetime.fromisoformat(m["data"]).date()
                if data >= semana_atras:
                    cont_tema[tema] = cont_tema.get(tema, 0) + 1

        pad = {
            "de": semana_atras.isoformat(),
            "ate": hoje.isoformat(),
            "emocoes": cont_emoc,
            "temas": cont_tema,
            "humor_predominante": humor_predominante
        }
        # grava no Firebase
        ref.child(uid_str).child("padroes_semanais").set(pad)
        
# ── UTILITÁRIOS DE BANCO ─────────────────────────────────────────────────────────

def inicializar_usuario(user_id):
    user_ref = ref.child(str(user_id))
    if not user_ref.get():
        user_ref.set({"init": {"timestamp": datetime.now().isoformat()}})
    for sub in ["contexto","memoria","emocao","temas","score_emocional","feedback_respostas","perfil"]:
        if not user_ref.child(sub).get():
            user_ref.child(sub).set({})

def salvar_dado(user_id, tipo, valor):
    ref.child(str(user_id)).child(tipo).push({
        "valor": valor,
        "data": datetime.now().isoformat()
    })

def salvar_por_tema(user_id, tema, texto):
    ref.child(str(user_id)).child("temas").child(tema).push({
        "texto": texto, "data": datetime.now().isoformat()
    })

def salvar_emocao_por_tema(user_id, tema, emocao):
    ref.child(str(user_id)).child("score_emocional").child(tema).push({
        "emocao": emocao, "data": datetime.now().isoformat()
    })

def registrar_feedback(user_id, tipo_resposta, feedback, texto_resposta):
    ref.child(str(user_id)).child("feedback_respostas").push({
        "tipo": tipo_resposta,
        "feedback": feedback,
        "resposta": texto_resposta,
        "data": datetime.now().isoformat()
    })

def salvar_memoria_relativa(user_id, chave, valor):
    ref.child(str(user_id)).child("memoria").child(chave).set(valor)

def obter_dados(user_id, tipo):
    return ref.child(str(user_id)).child(tipo).get() or {}

def buscar_por_tema(user_id, tema):
    d = ref.child(str(user_id)).child("temas").child(tema).get()
    return [x["texto"] for x in d.values()] if d else []

def salvar_contexto(user_id, texto):
    ref.child(str(user_id)).child("contexto").push({
        "texto": texto, "data": datetime.now().isoformat()
    })

def recuperar_contexto(user_id, limite=HISTORY_LIMIT):
    # 1) Puxe o resumo salvo (se existir)
    resumo_node = ref.child(str(user_id)).child(SUMMARY_KEY).get() or {}
    partes = []
    if resumo_node.get("texto"):
        partes.append(f"**Resumo anterior:** {resumo_node['texto']}")

    # 2) Puxe as últimas mensagens “cruas”
    d = ref.child(str(user_id)).child("contexto").get() or {}
    ult = list(d.values())[-limite:]
    for x in ult:
        if 'texto' in x:
            partes.append(f"Usuário: {x['texto']}")

    return "\n".join(partes)

def recuperar_memoria(user_id):
    m = ref.child(str(user_id)).child("memoria")
    if not m.get(): m.set({})
    return m.get() or {}
#____ETAPA 5: MEMORIA GERAL_____________
async def extrair_memoria_com_gpt(user_id: int, texto: str) -> dict:
    """
    Usa o GPT para identificar fatos livres e “importantes” no texto,
    e devolve um dict onde cada chave seja um tópico e o valor a informação.
    """
    prompt = (
        "Extraia deste texto os fatos ou informações que sejam úteis "
        "para lembrar no futuro. Retorne apenas um JSON onde cada "
        "chave seja um tópico e o valor seja a informação. Exemplo:\n"
        '{ "profissão": "engenheiro", "filho": "Lucas" }\n\n'
        f"Texto: {texto}"
    )
    resp = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    content = resp.choices[0].message.content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}
#__________________________________

async def resumir_contexto_antigo(user_id):
    """
    Busca todo o contexto salvo, gera um resumo via OpenAI,
    armazena no Firebase em SUMMARY_KEY e limpa o histórico bruto.
    """
    caminho = ref.child(str(user_id)).child("contexto")
    todas = caminho.get() or {}
    textos = [x["texto"] for x in todas.values() if isinstance(x, dict)]

    if len(textos) <= HISTORY_LIMIT:
        return  # nada a resumir ainda

    # pega as mensagens “antigas” além do HISTORY_LIMIT
    antigas = textos[:-HISTORY_LIMIT]
    prompt = "Resuma brevemente o seguinte histórico de conversas:\n\n" + "\n".join(antigas)
    resp = client.chat.completions.create(
        model="gpt-4o",
        ###original messages=[{"role":"user","content":prompt}]
    ###original)
        messages=[
        {"role": "system","content": ESTILO_SOPHOS},
        {"role": "user","content":prompt}])
        
    resumo = resp.choices[0].message.content

    # salva no Firebase e remove histórico bruto antigo
    ref.child(str(user_id)).child(SUMMARY_KEY).set({"texto": resumo, "data": datetime.now().isoformat()})
    # limpa o “contexto” bruto
    for key in list(todas.keys())[:-HISTORY_LIMIT]:
        caminho.child(key).delete()
        
# ── DETECÇÃO DE DATA ─────────────────────────────────────────────────────────────

def detectar_data_hoje(texto):
    match = re.search(r"hoje\s+(é\s+dia\s+|é\s+)?(\d{1,2}/\d{1,2}/\d{2,4})", texto)
    if not match: return None
    data_str = match.group(2)
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(data_str, fmt).date().isoformat()
        except:
            continue
    return None

# ── PERFIL DE PERSONALIDADE (Etapa 3) ─────────────────────────────────────────────

def definir_perfil_usuario(user_id):
    emo_data  = obter_dados(user_id, "emocao")
    tema_data = obter_dados(user_id, "score_emocional")
    freq = { e["valor"]:0 for e in emo_data.values() }
    for e in emo_data.values():
        freq[e["valor"]] = freq.get(e["valor"], 0) + 1
    tema_freq = { tema: len(entries) for tema, entries in tema_data.items() }
    perfil = "equilibrado"
    if freq.get("triste", 0) > freq.get("feliz", 0):
        perfil = "sensível empático"
    elif freq.get("focado", 0) > freq.get("cansado", 0):
        perfil = "estoico racional"
    elif tema_freq.get("espiritualidade", 0) > tema_freq.get("trabalho", 0):
        perfil = "visionário reflexivo"
    ref.child(str(user_id)).child("perfil").set({"tipo": perfil, "data": datetime.now().isoformat()})
    return perfil

async def perfil_command(update, context):
    user_id = update.effective_user.id
    perfil = ref.child(str(user_id)).child("perfil").get()
    if not perfil:
        perfil_tipo = definir_perfil_usuario(user_id)
    else:
        perfil_tipo = perfil.get("tipo", "desconhecido")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🧩 Seu perfil atual: *{perfil_tipo}*", parse_mode="Markdown"
    )

# ── EXPORTAÇÃO ───────────────────────────────────────────────────────────────────

async def exportar(update, context: ContextTypes.DEFAULT_TYPE):
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
    txt_path   = f"sophos_{user_id}.txt"
    df.to_excel(excel_path, index=False)
    df.to_csv(txt_path, index=False, sep="\t")

    import aiofiles
    from telegram import InputFile
    for path in (excel_path, txt_path):
        async with aiofiles.open(path, "rb") as f:
            data = await f.read()
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=InputFile(data, filename=os.path.basename(path))
            )

# ── FEEDBACK INLINE ──────────────────────────────────────────────────────────────

async def feedback_handler(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    #typ, fb, _ = q.data.split(":", 2)
        #novo
    try:
        typ, fb = q.data.split(":", 1)
    except ValueError:
        await q.message.reply_text("⚠️ Feedback mal formatado.")
        #novo
    uid = q.from_user.id
    tx  = context.user_data.get("ultima_resposta", "")
    registrar_feedback(uid, typ, fb, tx)
    await q.edit_message_reply_markup(None)
    await q.message.reply_text("✅ Feedback registrado. Obrigado!")

def marcadores_feedback(tipo):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👍", callback_data=f"{tipo}:like"),
        InlineKeyboardButton("👎", callback_data=f"{tipo}:dislike")
    ]])

# ── COMANDOS ────────────────────────────────────────────────────────────────────

async def start(update, context):
    uid = update.effective_user.id
    inicializar_usuario(uid)
    await context.bot.send_message(update.effective_chat.id,
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
        "/padroes - padroes semanais\n"
        "/exportar — backup (Excel/TXT)\n"
        "/comandos — mostrar este menu"
    )
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")

async def resumo(update, context):
    uid = update.effective_user.id
    d = obter_dados(uid, "emocao")
    if not d:
        await context.bot.send_message(update.effective_chat.id, "Nenhuma emoção registrada.")
        return
    cnt = {}
    for e in d.values():
        cnt[e["valor"]] = cnt.get(e["valor"], 0) + 1
    texto = "📊 Resumo emocional:\n" + "\n".join(f"- {k}: {v}x" for k,v in cnt.items())
    await context.bot.send_message(update.effective_chat.id, texto)

        # ____________ ETAPA 4_______________________
async def padroes_semanais_command(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    dados = ref.child(str(uid)).child("padroes_semanais").get() or {}
    if not dados:
        await context.bot.send_message(update.effective_chat.id,
            "🔍 Ainda não há análise semanal disponível. Tente novamente mais tarde.")
        return

    texto = (
        f"📅 Padrões de {dados['de']} até {dados['ate']}:\n\n"
        f"🧠 Humor predominante: *{dados.get('humor_predominante','-')}*/n"
        "🧠 Emoções: " +
        ", ".join(f"{k}({v})" for k,v in dados["emocoes"].items()) + "\n"
        "📂 Temas: " +
        ", ".join(f"{k}({v})" for k,v in dados["temas"].items())
    )
    await context.bot.send_message(
        update.effective_chat.id,
        texto,
        parse_mode="Markdown"
    )
#__________________________________________________________________

async def conselheiro(update, context):
    uid = update.effective_user.id
    d = obter_dados(uid, "emocao")
    if not d or len(d) < 3:
        await context.bot.send_message(update.effective_chat.id, "Poucos dados pra gerar conselho.")
        return
    prompt = "Com base nas emoções recentes:\n" + \
        "\n".join(f"- {e['data'][:10]}: {e['valor']}" for e in list(d.values())[-7:]) + \
        "\nMe dê um conselho baseado nisso."
    resp = client.chat.completions.create(model="gpt-4o", messages=[{"role":"user","content":prompt}])
    r = resp.choices[0].message.content
    context.user_data["ultima_resposta"] = r
    await context.bot.send_message(
        update.effective_chat.id,
        "📜 " + r,
        reply_markup=marcadores_feedback("conselheiro")
    )

async def consultar_tema(update, context):
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

async def resumir(update, context):
    if not context.args:
        await context.bot.send_message(update.effective_chat.id, "Ex: /resumir <texto>")
        return
    orig = " ".join(context.args)
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role":"user","content":f"Resuma de forma prática:\n\n{orig}"}]
    )
    r = resp.choices[0].message.content
    context.user_data["ultima_resposta"] = r
    await context.bot.send_message(
        update.effective_chat.id,
        "📝 " + r,
        reply_markup=marcadores_feedback("resumir")
    )

# ── VOZ & TEXTO ─────────────────────────────────────────────────────────────────

async def voz(update, context):
    uid = update.effective_user.id
    f = await update.message.voice.get_file()
    path = f"voz_{uid}.ogg"
    await f.download_to_drive(path)
    with open(path, "rb") as af:
        tr = client.audio.transcriptions.create(model="whisper-1", file=af)
    texto = tr.text.lower()
    await context.bot.send_message(update.effective_chat.id, f"🗣️ Você disse: {texto}")
    await processar_texto(uid, texto, update, context)

async def processar_texto(user_id, texto, update, context):
    await resumir_contexto_antigo(user_id)
    inicializar_usuario(user_id)
    salvar_contexto(user_id,texto)
    #__ extrai a "memória geral" via GPT e salva no Firebase
    memoria_nova = await extrair_memoria_com_gpt(user_id, texto)
    for chave, valor in memoria_nova.items():
        salvar_memoria_relativa(user_id, chave, valor)
    #____________________________________________
    # data
    dhoje = detectar_data_hoje(texto)
    if dhoje:
        salvar_memoria_relativa(user_id, "data_atual", dhoje)
        await context.bot.send_message(update.effective_chat.id, f"📅 Data registrada: {dhoje}")

    # emoções e temas
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

    # memória relativa
    if "meu filho é" in texto:
        nome = texto.split("meu filho é")[-1].strip().split()[0]
        salvar_memoria_relativa(user_id, "filho", nome)

    # monta prompt
    cont = recuperar_contexto(user_id)
    mem  = recuperar_memoria(user_id)
    perfil = ref.child(str(user_id)).child("perfil").get() or {}
    perfil_tipo = perfil.get("tipo")
    base = cont
    if mem:
        base += "\n\nLembrar:\n" + "\n".join(f"- {k}: {v}" for k,v in mem.items())
    if perfil_tipo:
        base += f"\n\nPerfil: {perfil_tipo}"
    prompt = f"{base}\n\nUsuário disse:\n{texto}"
    resp = client.chat.completions.create(model="gpt-4o", messages=[{"role":"user","content":prompt}])
    r = resp.choices[0].message.content
    context.user_data["ultima_resposta"] = r
    await context.bot.send_message(
        update.effective_chat.id,
        r,
        reply_markup=marcadores_feedback("geral")
    )

async def mensagem(update, context):
    uid = update.effective_user.id
    txt = update.message.text.lower()
    await processar_texto(uid, txt, update, context)

# ── INICIALIZAÇÃO ────────────────────────────────────────────────────────────────

def main():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )
    #_____ETAPA 4____________________
    # agenda a análise semanal
    # roda pela primeira vez assim que o bot subir e depois a cada 7 dias
    app.job_queue.run_repeating(
        analisar_padroes,
        interval=timedelta(days=7),
        first=0
    )

    # registra o comando /padroes
    app.add_handler(CommandHandler("padroes", padroes_semanais_command))
    #_______________________________
    
    #Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("comandos", comandos))
    app.add_handler(CommandHandler("perfil", perfil_command))
    app.add_handler(CommandHandler("resumo", resumo))
    app.add_handler(CommandHandler("consultar", consultar_tema))
    app.add_handler(CommandHandler("resumir", resumir))
    app.add_handler(CommandHandler("conselheiro", conselheiro))
    app.add_handler(CommandHandler("exportar", exportar))
    app.add_handler(CallbackQueryHandler(feedback_handler))
    app.add_handler(MessageHandler(filters.VOICE, voz))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), mensagem))

    #Inicia webhook
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 3000)),
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL,
    )

@flask_app.route('/')
def home():
    return "✅ Sophos Bot está rodando via webhook"

if __name__ == "__main__":
    
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=3000)).start()
    main()
