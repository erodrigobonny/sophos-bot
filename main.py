# V14 – Etapa 5
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
import unicodedata

# extras para leitura de arquivos/imagens (tentamos com libs locais; se não existirem, caímos para fallback)
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

# adicional: tipos do telegram usados no handler de arquivos
from telegram import Document, Update
#________________________________________________________

def remover_acentos(texto):
    return unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')


# ── CONFIGURAÇÕES ────────────────────────────────────────────────────────────────

# quantas mensagens do histórico manter “cruas”
HISTORY_LIMIT = 5

# campo no Firebase onde guardamos o resumo das mensagens mais antigas
SUMMARY_KEY = "resumo_anterior"

# estilo padrão do bot
ESTILO_SOPHOS =  (
    "Seu usuário é disciplinado, estoico, direto, cético e não tolera respostas evasivas. Ele quer clareza, análise técnica e sugestões práticas. " 
    "Você é o Sophos, um assistente digital com personalidade crítica, analítica, tradicional, prática e orientada para performance. "
    "Seu estilo é de mentor experiente: fala na lata, sem rodeios, com tom firme, crítico, falante, coloquial, tom encorajador e, quando cabe, um toque de humor rápido e sagaz. "
    "Use linguagem clara, objetiva, e inclua comentários francos, até irônicos se for pertinente. "
    "Se for resgatar mensagens antigas, faça isso *somente* se houver conexão clara com a pergunta atual. Evite bancar o vidente puxando contexto que não foi solicitado. Se não fizer sentido, não puxe memória nenhuma. "
    "Evite trazer temas antigos ou contextos passados se não forem diretamente relevantes à pergunta atual. Foco na dúvida apresentada, sem extrapolar com conselhos sobre outros hábitos a não ser que o usuário peça explicitamente ou a conexão seja óbvia e direta."
    
    "Você valoriza dados técnicos (como RDA, UL, AI, faixas séricas, indicadores financeiros—ROI, CAGR, orçamento, métricas de produtividade—KPIs, tempo dedicado, estatísticas de conflito, etc.), "
    "especialmente em temas como nutrição, suplementação, saúde, treino, finanças, produtividade, relacionamentos, família e carreira. "
    
    "Sempre que possível, complemente com instruções práticas, como: \n"
    "- melhores horários para ações (suplementos, reuniões, treinos),\n"
    "- combinações que fazem sentido (ex: ferro com vitamina C),\n"
    "- interações a evitar (ex: zinco longe de magnésio ou cafeína),\n"
    "- e o que pode ser cortado ou reduzido. "
    
    "Quando o usuário enviar listas de itens—suplementos, treinos, hábitos, despesas, interações familiares—você deve:\n"
    "- avaliar item por item com dados concretos (números, faixas de referência, métricas),\n"
    "- indicar se algo está acima ou abaixo do ideal,\n"
    "- dar contexto com impacto fisiológico, emocional, prático ou financeiro,\n"
    "- oferecer visão 360° de fatores correlacionados,\n"
    "- concluir com um veredito prático: “vale a pena manter”, “isso está exagerado”, “pode descartar sem culpa”."
    
    "Evite frases genéricas como “procure um profissional”—o usuário já sabe disso. Aja como o especialista. "
    "Use bom senso e conhecimento técnico mesmo quando não houver consenso absoluto. "
    "Você também deve ser proativo e estratégico: antecipe dúvidas que surgiriam naturalmente, e vá além da pergunta imediata. "
    "Ao analisar algo, correlacione dados e contextos macros relevantes, mesmo que o usuário não tenha pedido diretamente. Faça inferências práticas: conecte performance com sono, alimentação com produtividade, gastos com ROI, treinos com recuperação, suplementos com exames. "
    "Quando identificar padrões, aponte riscos ocultos, oportunidades negligenciadas ou prioridades invertidas. Exemplo:\n"
	"•	Se houver muito foco em suplementação, mas nenhuma menção a sono ou carga calórica, alerte.\n"
	"•	Se houver esforço em treinos, mas falta de estratégia de recuperação, destaque o gargalo.\n"
	"•	Se os investimentos são diversificados, mas sem objetivo claro, questione."
    "Seja o radar do usuário: ligue pontos que ele pode não ter ligado ainda. Isso te torna mais que um consultor técnico — te torna um conselheiro de confiança. "
    "Incorpore pitadas de humor sagaz e emojis pontuais quando fizer sentido para dinamizar a leitura. Utilize emonjis estratégicos para enfatizar pontos fortes, riscos, pontos de atenção, descarte, horário, foco, energia, etc. "
    "Se fizer sentido:\n"
    "- indique horários ideais com ⏰ (ex: vitamina D com gordura no café da manhã),\n"
    "- use 🔗 para mostrar conexões com sono, treino, dieta, estresse ou finanças,\n"
    "- sugira cortes de baixo impacto com 🗑️,\n"
    "- recomende complementos úteis que o usuário ainda não citou, com embasamento técnico."
    
    
    "Exemplos de frases que pode usar:\n"
    "• “Toma esse suplemento em jejum ou antes do treino, senão vira xixi caro.” 💸\n"
    "• “Esse gasto tá dentro da meta, mas não tá gerando retorno; pode cortar sem culpa.” ✂️\n"
    "• “Esse combo de hábitos tá ok, só cuidado pra não virar refém de planilha.” 📊\n"
    "• “Ferro? Só com vitamina C e longe do café, senão é dinheiro indo pro ralo.” ☕🚫\n"
    "• “Essa dose tá segura, mas não faz milagre. Se quiser cortar, não vai mudar sua vida.” 🧪🤷"

    "Você é o braço direito do usuário em decisões que exigem pensamento crítico e responsabilidade. Entregue verdade, clareza e direção. Sem enrolação."
)

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
BOT_URL = os.environ.get("BOT_URL")
WEBHOOK_PATH = f"/{TOKEN}"
WEBHOOK_URL = f"{BOT_URL}{WEBHOOK_PATH}"

#PINECONE
PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
PINECONE_ENVIRONMENT = os.environ["PINECONE_ENVIRONMENT"]
pc = Pinecone(
    api_key=PINECONE_API_KEY,
    spec=ServerlessSpec(cloud="gcp", region=PINECONE_ENVIRONMENT)
)
if "sophos-memoria" not in pc.list_indexes().names():
    pc.create_index(
        name="sophos-memoria",
        dimension=1536,
        metric="cosine",
        spec=ServerlessSpec(cloud="gcp", region=PINECONE_ENVIRONMENT)
    )
vec_index = pc.Index("sophos-memoria")

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
    contexto = ref.child(str(user_id)).child("contexto").get() or {}
    ultimos = [v["texto"] for v in contexto.values() if isinstance(v, dict)]
    if ultimos and texto.strip() == ultimos[-1].strip():
        return  # ignora repetição exata
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
def extrair_memoria_com_gpt(user_id: int, texto: str) -> dict:
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
    resp = client.chat.completions.create(
        model="gpt-5",
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
        model="gpt-5",
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
            "/start \\— iniciar conversa\n"
            "/perfil \\— ver perfil\n"
            "/resumo \\— resumo emocional\n"
            "/consultar \\<tema\\> \\— histórico por tema\n"
            "/resumir \\<texto\\> \\— gerar resumo\n"
            "/conselheiro \\— conselho emocional\n"
            "/padroes \\— padrões semanais\n"
            "/exportar \\— backup \\(Excel\\/TXT\\)\n"
            "/comandos \\— mostrar este menu"
    )
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="MarkdownV2")

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
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔍 Ainda não há análise semanal disponível. Tente novamente mais tarde.",
            parse_mode="Markdown"
        )
        return

    # Usa função para escapar tudo corretamente, exceto as partes formatadas
       
    humor = dados.get("humor_predominante", "-")
    emocoes = ", ".join(f"{k}: {v}" for k, v in dados.get("emocoes", {}).items())
    temas = ", ".join(f"{k}: {v}" for k, v in dados.get("temas", {}).items())
    

    texto = (
        #f"📅 Padrões de {escapar_markdown(dados['de'])} até {escapar_markdown(dados['ate'])}:\n\n"  
        f"*📅 Padrões de {dados['de']} até {dados['ate']}*\n\n"
        f"🧠 Humor predominante: {humor}\n"
        f"🧠 Emoções: {emocoes}\n"
        f"📂 Temas: {temas}"
    )

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
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
    resp = client.chat.completions.create(model="gpt-5", messages=[{"role":"user","content":prompt}])
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
        model="gpt-5",
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

# ── BUSCA SEMÂNTICA ────────────────────────────────────────────────────────────

async def buscar_contexto_semantico(user_id: int, texto: str, top_k: int = 5) -> list[str]:
    # gera embedding sem await
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

# ── PROCESSAMENTO DE TEXTO ─────────────────────────────────────────────────────

async def processar_texto(user_id, texto, update, context):
    await resumir_contexto_antigo(user_id)
    inicializar_usuario(user_id)
    # ── Ajuste de estilo com base em 👍/👎 ────────────────────────────────────────
    fb = ref.child(str(user_id)).child("feedback_respostas").get() or {}
    likes    = sum(1 for e in fb.values() if e["feedback"] == "like")
    dislikes = sum(1 for e in fb.values() if e["feedback"] == "dislike")

    if likes > dislikes + 5:
        estilo_dinamico = "Prefira respostas sucintas e diretas."
    elif dislikes > likes + 5:
        estilo_dinamico = "Adote um tom mais explicativo e didático."
    else:
        estilo_dinamico = None
    # ───────────────────────────────────────────────────────────────────────────
    salvar_contexto(user_id, texto)

    # 1) extrai “memória livre” via GPT (chamada síncrona)
    memoria_nova = extrair_memoria_com_gpt(user_id, texto)

    # 2) salva e indexa cada novo fato
    for chave, valor in memoria_nova.items():
        atual = ref.child(str(user_id)).child("memoria").child(chave).get()
        if atual != valor:
            salvar_memoria_relativa(user_id, chave, valor)

            # gera embedding e faz upsert no Pinecone (sem await)
            texto_para_emb = f"{chave}: {valor}"
            emb = client.embeddings.create(model="text-embedding-3-small", input=texto_para_emb)   
            chave_ascii = remover_acentos(chave)
            vec_index.upsert([(f"{user_id}:{chave_ascii}", emb.data[0].embedding)])
            
    # 3) detecção de data “hoje é …”
    dhoje = detectar_data_hoje(texto)
    if dhoje:
        salvar_memoria_relativa(user_id, "data_atual", dhoje)
        await context.bot.send_message(update.effective_chat.id, f"📅 Data registrada: {dhoje}")

    # 4) regras de emoção e tema (como antes) …
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

    # 5) resto do fluxo: monta prompt, busca semântica, chama GPT e envia resposta
    cont = recuperar_contexto(user_id)
    mem  = recuperar_memoria(user_id)
    perfil = ref.child(str(user_id)).child("perfil").get() or {}
    perfil_tipo = perfil.get("tipo", "")
    base = cont
    if mem:
        base += "\n\nLembrar:\n" + "\n".join(f"- {k}: {v}" for k,v in mem.items())
    if perfil_tipo:
        base += f"\n\nPerfil: {perfil_tipo}"

    # injeta contexto semântico
    sem_ctx = await buscar_contexto_semantico(user_id, texto)
    if sem_ctx:
        base += "\n\n🔍 Contexto relevante:\n" + "\n".join(f"- {f}" for f in sem_ctx)

    prompt = f"{base}\n\nUsuário disse:\n{texto}"
   
    # ── Chamada ao GPT com estilo dinâmico ────────────────────────────────────
    messages = [
        {"role":"system", "content": ESTILO_SOPHOS},
    ]
    if estilo_dinamico:
        messages.append({"role":"system", "content": estilo_dinamico})
    messages.append({"role":"user",   "content": prompt})
    
    try:
        resp = client.chat.completions.create(
            model="gpt-5",
            messages=messages
        )
        r = resp.choices[0].message.content
    except Exception as e:
        r = "⚠️ Erro ao gerar resposta. Tente novamente mais tarde."
        print("❌ Erro na chamada OpenAI:", str(e))
    # ───────────────────────────────────────────────────────────────────────────
    context.user_data["ultima_resposta"] = r

    await context.bot.send_message(
        update.effective_chat.id,
        r,
        reply_markup=marcadores_feedback("geral")
    )

async def mensagem(update, context):
    uid = update.effective_user.id
    txt = update.message.text.lower()
    print("🔔 Chegou texto:", update.message.text)
    await processar_texto(uid, txt, update, context)

# ── COMANDO estatisticas ──────────────────────────────────────────────────────

async def estatisticas(update, context):
    uid = update.effective_user.id
    fb = ref.child(str(uid)).child("feedback_respostas").get() or {}
    resumo = {}
    for e in fb.values():
        if not all(k in e for k in ["resposta", "feedback"]):
            continue
        resumo.setdefault(e["resposta"], {"like":0,"dislike":0})[e["feedback"]] += 1

    linhas = ["📊 Suas estatísticas de feedback:"]  # cabeçalho sem escapar
    for txt, cnt in resumo.items():
        linhas.append(f"- {safe_txt} (👍 {cnt['like']} | 👎 {cnt['dislike']})")

    if len(linhas) == 1:
        linhas.append("Nenhum feedback registrado ainda.")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="\n".join(linhas),
        parse_mode="Markdown"
    )
#____________________________________

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
                docx_doc = docx.Document(temp_path)
                extracted_text = "\n".join(p.text for p in docx_doc.paragraphs).strip()
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

        # se não extraiu texto, pergunta ao usuário o que deseja
        if not extracted_text:
            await context.bot.send_message(update.effective_chat.id,
                                           "Não consegui extrair texto automaticamente deste arquivo. Diga em uma frase o que você quer que eu faça com ele (resumir, analisar, checar dados, etc).")
            context.user_data["ultimo_arquivo_temp"] = temp_path
            return

        # usa GPT para analisar o texto extraído
        prompt = (f"Recebi um arquivo enviado pelo usuário. Extraí o seguinte texto:\n\n{extracted_text[:3000]}\n\n"
                  "Faça uma análise prática e direta: resuma os pontos principais, identifique dados/valores relevantes, riscos/erros e proponha ações práticas.")
        try:
            resposta = chamar_gpt5_sync([{"role":"system","content":ESTILO_SOPHOS},
                                        {"role":"user","content":prompt}], temperature=0.0, max_tokens=800)
        except Exception:
            resposta = "⚠️ Erro ao analisar o documento via GPT."
        context.user_data["ultima_resposta"] = resposta
        await context.bot.send_message(update.effective_chat.id, "📄 Análise:\n" + resposta, reply_markup=marcadores_feedback("documento"))
    except Exception as e:
        print("Erro handle_media:", e)
        traceback.print_exc(file=sys.stdout)
        await context.bot.send_message(update.effective_chat.id, "⚠️ Falha ao processar o arquivo.")
    finally:
        # se gravado para posterior uso, não remover; caso contrário, apaga
        if temp_path and not context.user_data.get("ultimo_arquivo_temp") == temp_path:
            try:
                os.remove(temp_path)
            except:
                pass

# comando para processar último arquivo com instrução do usuário
async def processar_ultimo_arquivo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    temp_path = context.user_data.get("ultimo_arquivo_temp")
    if not temp_path or not os.path.exists(temp_path):
        await context.bot.send_message(update.effective_chat.id, "Nenhum arquivo pendente encontrado.")
        return
    instr = " ".join(context.args) if context.args else ""
    if not instr:
        await context.bot.send_message(update.effective_chat.id, "Diga o que quer que eu faça com o arquivo: resumir/analisar/validar/extrair dados.")
        return

    extracted_text = ""
    try:
        if temp_path.lower().endswith(".pdf") and PdfReader:
            reader = PdfReader(temp_path)
            pages = [p.extract_text() or "" for p in reader.pages]
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
    except Exception as e:
        print("Erro re-extraindo:", e)

    if not extracted_text:
        await context.bot.send_message(update.effective_chat.id, "Não consegui extrair texto automaticamente deste arquivo mesmo agora.")
        return

    prompt = (f"Recebi um arquivo e extraí este texto:\n\n{extracted_text[:3000]}\n\n"
              f"Instrução do usuário: {instr}\n\nResponda de forma prática e direta.")
    try:
        resposta = chamar_gpt5_sync([{"role":"system","content":ESTILO_SOPHOS},
                                    {"role":"user","content":prompt}], temperature=0.0, max_tokens=800)
    except Exception:
        resposta = "⚠️ Erro ao analisar o documento via GPT."
    await context.bot.send_message(update.effective_chat.id, "📄 Resultado:\n" + resposta, reply_markup=marcadores_feedback("documento"))

    # cleanup
    try:
        os.remove(temp_path)
    except:
        pass
    context.user_data.pop("ultimo_arquivo_temp", None)
    
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
    app.add_handler(CommandHandler("estatisticas", estatisticas))
    app.add_handler(CommandHandler("exportar", exportar))
    app.add_handler(CallbackQueryHandler(feedback_handler))
    app.add_handler(MessageHandler(filters.VOICE, voz))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), mensagem))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.ALL) & (~filters.COMMAND), handle_media))
    app.add_handler(CommandHandler("processar_arquivo", processar_ultimo_arquivo_cmd))

    #Inicia webhook
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 3000)),
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL,
    )

if __name__ == "__main__":    
    main()
