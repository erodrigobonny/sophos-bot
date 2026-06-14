# Sophos V23.2 – main.py
#
# Mudanças vs V23.1 (tudo anterior mantido):
# 24. (V23.2) Três ajustes de coerência no /prontidao:
#     - TSB negativo deixa de ser listado como "a favor": entra como
#       observação neutra (entre -10 e +5) e só vira ponto a favor quando
#       genuinamente fresco (>+5).
#     - Leitura do strain casa com a faixa: quando strain ≥120 (alto) E
#       monotonia ≥2.0, a frase não minimiza mais com "não está explosiva";
#       pede contraste real (leve de verdade ou descanso ativo).
#     - Ação contextual por motivo: quando o amarelo/vermelho vem por carga
#       (treino pesado ontem, monotonia, strain), a ação é específica
#       ("absorver o pedal de ontem"). Fallback para a ação genérica se o
#       motivo não casar — sem risco de regressão.
#
# Mudanças vs V23:
# 23. (V23.1) Correções de coerência da carga efetiva:
#     - treino_linha (/metricas) mostra a carga efetiva e, se corrigida,
#       exibe "[corrigida; original X]" — antes a lista mostrava a bruta
#       enquanto o topo já avisava da correção (contradição visual).
#     - estado salvo da prontidão carrega "cargas_corrigidas", para a
#       conversa de decisão saber que houve correção por sensor.
#
# ALCANCE DA CORREÇÃO DE CARGA (importante, não criar falsa sensação):
#   A V23 corrige os indicadores que o PRÓPRIO Sophos calcula a partir da
#   carga dos treinos: carga_total, carga_por_dia/sessão, monotonia, strain,
#   distribuição por modalidade, maior treino, resumo semanal, outliers e
#   carga de ontem na prontidão.
#   NÃO reescreve CTL, ATL, TSB, ramp_rate e ACWR — esses vêm PRONTOS do
#   wellness do Intervals e podem refletir a potência quebrada até o
#   Intervals recalcular. Logo, ver "carga corrigida alta hoje" + "TSB +3"
#   no mesmo relatório não é contradição: é correção local vs fitness ainda
#   não recalculado na origem.
#
# Mudanças vs V22.2:
# 22. (V23) Carga efetiva + correção de sensor inconsistente (SÓ BIKE):
#     quando a potência da bike falha (bateria/calibração) o Intervals
#     calcula icu_training_load a partir de potência fantasma, gerando
#     carga absurdamente baixa para um pedal cardiovascularmente pesado.
#     carga_efetiva_treino() detecta a aberração (carga < 0.5*hr_load,
#     com guardas grossas: bike + duração ≥30min + hr_load ≥50 + potência
#     ausente/baixa) e usa hr_load como carga real, preservando o dado
#     bruto. TODOS os cálculos (carga_total, indicadores, cargas_diárias,
#     agregação, distribuição, maior treino) passam a ler carga_efetiva.
#     Correção é automática mas SINALIZADA: aviso visível em /metricas,
#     /analise, /relatorio e /prontidao. Limiar grosseiro: só aberração
#     dispara — variação fisiológica normal (calor, cafeína) não corrige.
#
# Mudanças vs V22.1:
# 19. (V22.2) Estado operacional reutilizável: /prontidao e /relatorio
#     salvam estado estruturado em Firebase estado_atual/{tipo} (chave que
#     se SOBRESCREVE, não lista) + uma linha curta no contexto linear.
# 20. (V22.2) Em mensagem comum, o estado de prontidão é injetado no
#     prompt APENAS quando há intenção de decisão de treino (gatilhos
#     fechados: "sigo o plano", "posso treinar", "algum risco"...), com
#     aviso de desatualização se o estado não for de hoje. Fallback para
#     o último relatório se não houver prontidão.
# 21. (V22.2) /decidir fica para depois que o estado provar valor em uso.
#
# Mudanças vs V22:
# 18. (V22.1) Strain classificado no /prontidao: <80 baixo | 80-120
#     moderado | 120-180 alto | >180 muito alto, mais linha "Leitura"
#     que cruza strain com monotonia (carga ok + variação baixa é o
#     combo mais traiçoeiro). Faixas genéricas; personalizar por
#     baseline individual fica para versão futura se o volume mudar.
#
# Mudanças vs V21.2:
# 17. (V22) RAMPA (rampRate da API do Intervals, variação de CTL/semana)
#     integrada em todo o sistema:
#     - /prontidao: regras de pontuação (>8 = +2 subida agressiva;
#       4-8 com HRV abaixo do baseline = +1 construindo sem absorver;
#       negativa = ponto a favor, descarregando) + linha no painel.
#     - /relatorio (operacional e histórico): ramp_rate no condicionamento,
#       interpretação fixa no prompt e rampa média semanal no resumo_semanal
#       do modo histórico.
#     - /analise: ramp_rate no contexto_carga de toda análise focada.
#     - /metricas: linha "Rampa (CTL/sem)".
#     - /comparar: herda via condicionamento (rampa A vs B).
#
# Mudanças vs V21.1:
# 16. (V21.2) /prontidao exibe CTL, ATL e Strain no painel de contexto.
#     Os três já estavam calculados; agora são surfaceados na saída.
#     inclui_fim_periodo por métrica. O /prontidao avisa quando HRV/RHR/sono
#     de hoje ainda não sincronizaram, mostra "dados até dd/mm" e soma 1
#     ponto de cautela apenas se o sono de hoje estiver ausente APÓS dia de
#     carga acima da média (sem punir atraso de sincronização à toa).
#     O /metricas exibe "até dd" em cada métrica do status wellness.
# 15. (V21.1) Timezone local (America/Recife): "hoje" e "ontem" deixam de
#     seguir o relógio UTC do servidor. Corrige /prontidao e relatórios
#     rodados entre 21h e meia-noite, que deslocavam a janela em 1 dia.
#
# Mudanças vs V20:
# 12. (V21) /prontidao — semáforo diário de prontidão 🟢🟡🔴 calculado
#     100% em Python (custo zero de GPT): status HRV/RHR/sono vs baseline,
#     ACWR, TSB, monotonia e treino de ontem viram pontuação de risco com
#     ação recomendada. Fallback para cortes genéricos sem baseline.
# 13. (V21) /prontidao ia — opcional: anexa comentário curto do MODEL_FAST
#     sobre o semáforo (payload mínimo, custa centavos).
#
# Mudanças vs V19.1:
# 8. (V20) FIX off-by-one: "/relatorio 7" agora cobre exatamente 7 dias
#    (antes pegava 8). Afeta relatorio, analise, metricas e comparar.
# 9. (V20) Relatório híbrido por janela:
#    - até 30 dias: modo OPERACIONAL (idêntico ao atual, byte a byte)
#    - acima de 30: modo HISTÓRICO — agregação semanal (carga, volume por
#      modalidade, HRV/RHR/sono/stress por semana), top 5 outliers por
#      carga, destaques de melhor/pior semana. Treino individual sai do
#      payload; trajetória entra. Corte de 30-60% no input de períodos
#      longos com prompt próprio (PROMPT_RELATORIO_HISTORICO).
# 10. (V20) /comparar usa MODEL_FAST para períodos < 14 dias.
# 11. (V20) coletar_intervals retém série diária compacta de wellness
#     (wellness_diario) — matéria-prima da agregação semanal; nunca é
#     enviada crua ao modelo.
#
# Mudanças vs V18.1:
# 1. /analise <pedido livre> — motor de análise sob demanda:
#    parser local extrai período + focos (corrida, bike, natação, força,
#    sono, recuperação, peso — combináveis) e envia ao modelo só o
#    subconjunto de dados relevante.
# 2. Baseline individual — coletar_intervals busca os 28 dias anteriores
#    ao período e calcula baseline pessoal de HRV/RHR/sono. O alerta de
#    recuperação compara contra o SEU baseline; fallback para cortes
#    genéricos se indisponível.
# 3. /comparar <dias> — período atual vs período anterior, lado a lado.
# 4. Contexto bidirecional — respostas do Sophos também entram no
#    histórico (truncadas), melhorando coerência de diálogos longos.
# 5. (V19.1) Baseline virou STATUS estilo Garmin: média 7d vs baseline 28d
#    com faixa de ±1 desvio padrão e classificação por métrica
#    (baixo/desequilibrado/equilibrado/alto) para HRV, RHR e sono,
#    ancorado no FIM do período analisado.
# 6. (V19.1) Pace de natação em dois formatos: "1:55" (exibição) e
#    decimal (comparação matemática).
# 7. (V19.1) CONTEXTO_BIDIRECIONAL como chave de configuração — desligue
#    com False se o histórico do Sophos inflar custo ou poluir respostas.

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

from PIL import Image

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
# V19: trigger subiu de 20 para 30 porque o contexto agora guarda também
# as respostas do Sophos (dobra o ritmo de entradas).
SUMMARY_TRIGGER = 30
SUMMARY_KEY = "resumo_anterior"

# V19.1: respostas do Sophos no histórico de contexto. Custo máximo:
# HISTORY_LIMIT=6 -> até 3 respostas x 400 chars = ~300 tokens extras por
# mensagem de chat. Comandos (/relatorio, /analise...) não são afetados.
# Mude para False para desligar sem mexer no resto do código.
CONTEXTO_BIDIRECIONAL = True

MODEL_MAIN = os.environ.get("OPENAI_MODEL_MAIN")
MODEL_FAST = os.environ.get("OPENAI_MODEL_FAST")
MODEL_INT = os.environ.get("OPENAI_MODEL_INT")
MODEL_TOP = os.environ.get("OPENAI_MODEL_TOP")
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

PROMPT_RELATORIO = """Você é coach de endurance e cientista de dados de performance.

REGRAS:
- Texto puro. Sem Markdown (**, --, ##).
- Máximo 3700 caracteres.
- Use os indicadores já calculados. Não recalcule.
- Não invente dado ausente.
- Não faça diagnóstico médico; use "maior risco de recuperação comprometida".
- Se alerta_recuperacao vier moderado/alto, recomende reduzir intensidade e priorizar sono.
- Se houver "baseline" nos dados, ele traz por métrica (HRV, RHR, sono): status
  (baixo/desequilibrado/equilibrado/alto), media_7d, baseline_28d, limites e
  variacao_pct. Interprete: HRV baixo/desequilibrado e RHR alto = recuperação
  comprometida. Cite a variacao_pct.
- Priorize conclusão sobre descrição. Cada insight aparece uma vez.

ESTILO:
- Mantenha linguagem humana e agradável de ler.
- Use os emojis das seções (📊 🔗 🧠 📈 ⚠️ 🎯).
- Pode usar frases curtas de interpretação prática quando agregarem valor.

INTERPRETAÇÕES FIXAS:
ACWR < 0.8 = subestímulo | 0.8-1.3 = controlado | 1.3-1.5 = atenção | >1.5 = risco de lesão
TSB positivo = descansado | negativo = carregado
CTL subindo = ganho de base | caindo = perda de tração
Rampa (ramp_rate, CTL/semana): >8 = subida agressiva | 4-8 = acelerada | 0-4 = sustentável | <0 = descarga/absorção
Rampa alta só é problema quando HRV/sono não acompanham (construindo sem absorver)
Monotonia/strain altos = risco de fadiga acumulada

MÉTRICAS A CORRELACIONAR (use todas disponíveis):
CTL, ATL, TSB, ACWR, rampa (ramp_rate), monotonia, strain, carga_por_dia, carga_por_sessao, densidade_treino,
dias_ativos_pct, distribuição de carga, maior_treino_carga/duracao/distancia,
HRV/tendência HRV, RHR/tendência RHR, sono/tendência sono, readiness, body battery,
stress, VO2max, FTP/eFTP, razão carga corrida/bike, percentual sessões alta intensidade,
potência, cadência, TRIMP, pace_100m, DPS e SWOLF de natação.

ESTRUTURA:
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

PRIORIDADE: 1. ponto forte | 2. gargalo | 3. risco | 4. ação prática"""

PROMPT_RELATORIO_HISTORICO = """Você é coach de endurance e cientista de dados de performance.

Este é um RELATÓRIO HISTÓRICO (período acima de 30 dias). Não analise treinos
individuais, exceto os outliers fornecidos. Priorize trajetória: evolução do
condicionamento, recuperação, sinais vitais, consistência e sustentabilidade
da carga ao longo das semanas.

REGRAS:
- Texto puro. Sem Markdown (**, --, ##). Máximo 3700 caracteres.
- Use resumo_semanal como matéria-prima principal. Indicadores já estão
  calculados; não recalcule e não invente dado ausente.
- Não faça diagnóstico médico; use "maior risco de recuperação comprometida".
- Se houver "baseline" nos dados, ele traz por métrica: status
  (baixo/desequilibrado/equilibrado/alto), media_7d, baseline_28d e
  variacao_pct. HRV baixo/desequilibrado e RHR alto = recuperação comprometida.
- Cite semanas específicas (número e intervalo) ao apontar blocos fortes,
  fracos ou de fadiga acumulada.
- resumo_semanal inclui rampa média por semana (CTL/sem): >8 agressiva |
  4-8 acelerada | 0-4 sustentável | <0 descarga. Use para identificar
  blocos de construção, platô e descarga — e cruze com HRV/sono da mesma
  semana para julgar se a construção foi absorvida.
- Priorize conclusão sobre descrição. Cada insight aparece uma vez.

ESTRUTURA:
📊 VISÃO DO PERÍODO
Volume total, distribuição por modalidade e consistência (semanas cheias vs vazias).

📈 EVOLUÇÃO DO CONDICIONAMENTO
CTL/ATL/TSB, VO2max, FTP/eFTP: subiu, caiu ou sustentou? Com boa recuperação ou na marra?

🛌 RECUPERAÇÃO AO LONGO DAS SEMANAS
HRV, RHR, sono e stress semana a semana: acompanharam a carga?

🔗 SUSTENTABILIDADE DA CARGA
ACWR, monotonia, strain, blocos de fadiga acumulada e como a carga se distribuiu.

⚠️ RISCO E OPORTUNIDADE
Principal padrão preocupante ou destravado no período.

🎯 DIREÇÃO DO PRÓXIMO BLOCO
Leitura de periodização: o que priorizar nas próximas semanas.

PRIORIDADE: 1. trajetória | 2. sustentabilidade | 3. risco | 4. direção prática"""

PROMPT_ANALISE = """Você é coach de endurance e cientista de dados de performance.

O usuário pediu uma ANÁLISE FOCADA. Responda exatamente ao que foi pedido,
usando somente os dados fornecidos.

REGRAS:
- Texto puro. Sem Markdown (**, --, ##). Máximo 3000 caracteres.
- Use os indicadores já calculados. Não recalcule. Não invente dado ausente.
- Não faça diagnóstico médico; use "maior risco de recuperação comprometida".
- Se houver "baseline" nos dados, ele traz por métrica: status
  (baixo/desequilibrado/equilibrado/alto), media_7d, baseline_28d e
  variacao_pct. HRV baixo/desequilibrado e RHR alto = recuperação
  comprometida. Cite a variacao_pct.
- Se houver "cargas_diarias", correlacione com as métricas pedidas
  (ex: sono ruim após dias de carga alta).
- Priorize conclusão sobre descrição. Cada insight aparece uma vez.

ESTRUTURA:
📊 VISÃO GERAL — números-chave do foco pedido no período.
🔍 ANÁLISE FOCADA — aprofunde no(s) foco(s) solicitado(s).
🔗 CORRELAÇÕES — cruze com carga, recuperação e contexto disponível.
📈 TENDÊNCIA — melhorou, piorou ou estável; principal gargalo.
🎯 RECOMENDAÇÃO — ajuste prático e específico ao foco pedido."""

PROMPT_COMPARACAO = """Você é coach de endurance e cientista de dados de performance.

Compare o PERÍODO A (anterior) com o PERÍODO B (atual).

REGRAS:
- Texto puro. Sem Markdown (**, --, ##). Máximo 3000 caracteres.
- Use os indicadores já calculados. Não recalcule. Não invente dado ausente.
- Não faça diagnóstico médico.
- Cite variações em números (absolutos ou percentuais).

ESTRUTURA:
📊 NÚMEROS LADO A LADO — volume, carga, sessões, recuperação.
📈 O QUE MELHOROU — com os números.
📉 O QUE PIOROU — com os números.
🧠 LEITURA — o que essa evolução significa para condicionamento e risco.
🎯 RECOMENDAÇÃO — ajuste prático para o próximo período."""

# V19: dicionário de domínios para o parser do /analise
DOMINIOS_ANALISE = {
    "forca": ["forca", "musculacao", "academia", "strength"],
    "corrida": ["corrida", "correr", "rodagem", "run"],
    "bike": ["bike", "ciclismo", "pedal", "bicicleta", "ride"],
    "natacao": ["natacao", "nadar", "nado", "piscina", "swim"],
    "sono": ["sono", "dormir", "sleep"],
    "recuperacao": [
        "recuperacao", "hrv", "rhr", "readiness", "descanso",
        "fadiga", "stress", "body battery", "bateria corporal"
    ],
    "peso": ["peso", "emagrec", "composicao corporal"],
}

NOMES_DOMINIO = {
    "corrida": "Corrida", "bike": "Bike", "natacao": "Natação",
    "forca": "Força", "sono": "Sono", "recuperacao": "Recuperação",
    "peso": "Peso", "geral": "Geral",
}

MAPA_TIPO_DOMINIO = {
    "corrida": ["run"],
    "bike": ["ride", "bike"],
    "natacao": ["swim"],
    "forca": ["strength", "weight"],
}

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

# V21.1: timezone local. Servidores (Railway/Render) rodam em UTC; entre
# 21h e meia-noite em Recife (UTC-3), "hoje" do servidor já é amanhã —
# o que desloca /prontidao e relatórios em 1 dia. Fallback para offset
# fixo -3 se o banco de timezones não estiver disponível no container.
try:
    from zoneinfo import ZoneInfo
    TZ_LOCAL = ZoneInfo("America/Recife")
except Exception:
    from datetime import timezone as _tz
    TZ_LOCAL = _tz(timedelta(hours=-3))

def hoje_local():
    return datetime.now(TZ_LOCAL).date()

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
    t = remover_acentos(texto.lower().strip())

    if len(t) < 40:
        return False

    return any(remover_acentos(g) in t for g in GATILHOS_MEMORIA)

def marcadores_feedback(tipo):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👍", callback_data=f"{tipo}:like"),
            InlineKeyboardButton("👎", callback_data=f"{tipo}:dislike"),
        ]
    ])

def parse_periodo_args(args):
    """Retorna (dias, inicio, fim). Levanta ValueError se formato inválido."""
    dias, inicio, fim = 7, None, None

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
            inicio, fim = datas[0], datas[1]
        else:
            dias = int(args[0])  # ValueError sobe para o chamador

    return dias, inicio, fim

def interpretar_pedido_analise(texto):
    """V19: parser local do /analise. Zero custo de token.
    Extrai (dias, inicio, fim, dominios) de um pedido em texto livre.
    Ex: 'sono nos últimos 30 dias' -> (30, None, None, ['sono'])
        'corrida e natação último mês' -> (30, None, None, ['corrida','natacao'])
        'hrv 2 semanas' -> (14, None, None, ['recuperacao'])
        'sono 01/05/26 31/05/26' -> (30, '01/05/26', '31/05/26', ['sono'])"""
    t = remover_acentos((texto or "").lower())

    # 1) Datas explícitas
    datas = []
    bruto = (texto or "").replace(" até ", " ").replace(" a ", " ")
    for token in re.split(r"[\s,;]+", bruto):
        token = token.strip()
        if not token:
            continue
        try:
            normalizar_data_br(token)
            datas.append(token)
        except ValueError:
            pass

    dias, inicio, fim = 30, None, None

    if len(datas) >= 2:
        inicio, fim = datas[0], datas[1]
    else:
        m = re.search(r"(\d+)\s*dias?", t)
        if m:
            dias = int(m.group(1))
        else:
            m = re.search(r"(\d+)\s*semanas?", t)
            if m:
                dias = int(m.group(1)) * 7
            elif re.search(r"(\d+)\s*mes(es)?", t):
                dias = int(re.search(r"(\d+)\s*mes(es)?", t).group(1)) * 30
            elif "trimestre" in t:
                dias = 90
            elif re.search(r"\bmes\b", t):
                dias = 30
            elif "semana" in t:
                dias = 7

    dias = min(max(dias, 2), 120)  # proteção contra payloads gigantes

    # 2) Domínios (combináveis)
    dominios = []
    for dom, palavras in DOMINIOS_ANALISE.items():
        if any(p in t for p in palavras):
            dominios.append(dom)

    if not dominios:
        dominios = ["geral"]

    return dias, inicio, fim, dominios

def _carga(t):
    """V23: carga que o Sophos usa nos cálculos — efetiva se corrigida,
    senão a bruta do Intervals."""
    ce = t.get("carga_efetiva")
    return (ce if ce is not None else t.get("carga_treino")) or 0


def carga_efetiva_treino(t):
    """V23: decide a carga real de um treino quando o sensor de potência
    falha. SÓ se aplica a BIKE (única modalidade com medidor de potência
    no setup do usuário). Quando a potência da bike descarrega no meio do
    treino, o Intervals calcula icu_training_load sobre potência fantasma
    e devolve carga absurdamente baixa — mas hr_load (carga por FC) continua
    honesto. Regra grosseira e conservadora: só aberração dispara.
    Preserva o dado bruto; devolve campos auxiliares para o treino."""
    carga = t.get("carga_treino")
    hr_load = t.get("hr_load")
    potencia = t.get("potencia_w")
    dur = t.get("dur_min") or 0
    tipo = (t.get("tipo") or "").lower()

    eh_bike = "ride" in tipo or "bike" in tipo

    resultado = {
        "carga_efetiva": carga,
        "carga_corrigida": False,
        "motivo_carga_corrigida": None,
        "fonte_carga": "icu_training_load",
    }

    # Carga ausente mas hr_load presente (QUALQUER modalidade): usa hr_load.
    # Isto é fallback de dado faltante, NÃO correção de sensor de potência
    # (que é exclusiva de bike). Razoável usar FC quando não há carga alguma.
    if carga is None:
        if hr_load is not None:
            resultado.update({
                "carga_efetiva": hr_load,
                "carga_corrigida": True,
                "motivo_carga_corrigida": "carga original ausente; usando hr_load",
                "fonte_carga": "hr_load",
            })
        return resultado

    # Correção de sensor: SÓ bike, e só com guardas grossas satisfeitas
    if (
        eh_bike
        and hr_load is not None
        and dur >= 30
        and hr_load >= 50
        and carga < hr_load * 0.5
        and (potencia is None or potencia < 50)
    ):
        resultado.update({
            "carga_efetiva": hr_load,
            "carga_corrigida": True,
            "motivo_carga_corrigida": (
                f"potência inconsistente vs FC (carga {round(carga)} vs hr_load "
                f"{round(hr_load)}, potência {round(potencia) if potencia else 'ausente'} W); "
                "usando carga por FC"
            ),
            "fonte_carga": "hr_load",
        })

    return resultado


def avisos_carga_corrigida(treinos):
    """V23: monta a lista de avisos de correção para exibir ao usuário."""
    avisos = []
    for t in treinos:
        if t.get("carga_corrigida"):
            nome = t.get("nome") or t.get("tipo") or "treino"
            data = t.get("data") or "-"
            avisos.append(
                f"{data} {nome}: carga {round(t.get('carga_treino') or 0)} → "
                f"{round(t.get('carga_efetiva') or 0)} (via FC)"
            )
    return avisos


def cargas_diarias(treinos):
    """Soma de carga por dia — base para correlações tipo sono x carga."""
    cargas = {}
    for t in treinos:
        data = t.get("data")
        if not data:
            continue
        cargas[data] = round(cargas.get(data, 0) + _carga(t))
    return cargas

def formatar_pace(min_decimais):
    """V19: converte pace decimal em formato m:ss.
    Ex: 1.92 -> '1:55' | 2.5 -> '2:30'"""
    if min_decimais is None:
        return None

    try:
        minutos = int(min_decimais)
        segundos = int(round((min_decimais - minutos) * 60))

        if segundos == 60:
            minutos += 1
            segundos = 0

        return f"{minutos}:{segundos:02d}"
    except Exception:
        return None

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

def salvar_contexto(user_id, texto, papel="usuario"):
    """V19: aceita papel ('usuario' ou 'sophos') para contexto bidirecional."""
    contexto = ref.child(str(user_id)).child("contexto").get() or {}
    ultimos = [v.get("texto", "") for v in contexto.values() if isinstance(v, dict)]

    if ultimos and texto.strip() == ultimos[-1].strip():
        return

    ref.child(str(user_id)).child("contexto").push({
        "texto": texto,
        "papel": papel,
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
            # V19: rotula pelo papel; entradas antigas (sem papel) = usuário
            rotulo = "Sophos" if item.get("papel") == "sophos" else "Usuário"
            partes.append(f"{rotulo}: {item['texto']}")

    return "\n".join(partes)

def salvar_estado_atual(user_id, tipo, dados):
    """V22.2: estado operacional reutilizável. Chave que se SOBRESCREVE
    (não é lista crescente): /prontidao e /relatorio deixam rastro
    estruturado que mensagens comuns consultam quando a pergunta pede
    decisão de treino. Falha silenciosa: não quebra o comando."""
    try:
        ref.child(str(user_id)).child("estado_atual").child(tipo).set({
            "data_local": hoje_local().isoformat(),
            "atualizado_em": agora_iso(),
            "dados": dados,
        })
    except Exception as e:
        print(f"Erro ao salvar estado_atual/{tipo}:", e)


def recuperar_estado_atual(user_id, tipo):
    """V22.2: lê o estado operacional salvo. None se ausente ou erro."""
    try:
        return ref.child(str(user_id)).child("estado_atual").child(tipo).get()
    except Exception as e:
        print(f"Erro ao ler estado_atual/{tipo}:", e)
        return None


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

    # V19: preserva o papel (usuário/Sophos) no texto enviado ao resumo
    textos = []
    for x in todas.values():
        if isinstance(x, dict) and x.get("texto"):
            rotulo = "Sophos" if x.get("papel") == "sophos" else "Usuário"
            textos.append(f"{rotulo}: {x['texto']}")

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

def calcular_indicadores(d, baseline=None):
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

        carga_t = _carga(t)
        carga_por_modalidade[grupo] = carga_por_modalidade.get(grupo, 0) + carga_t

    distribuicao_carga_pct = {
        k: round((v / carga) * 100, 1) if carga else 0
        for k, v in carga_por_modalidade.items()
    }

    maior_carga = max(treinos, key=lambda t: _carga(t), default=None)
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
            "carga": _carga(t) if t.get("carga_efetiva") is not None else t.get("carga_treino"),
            "carga_corrigida": t.get("carga_corrigida") or None,
            "fc_med": t.get("fc_med"),
        }

    sono_medio = rec.get("sono_medio_h")
    hrv_medio = rec.get("hrv_medio")
    rhr_medio = rec.get("rhr_medio")

    carga_por_dia = round(carga / dias, 1) if dias else 0
    acwr = round(atl / ctl, 2) if ctl else None

    alerta_recuperacao = "baixo"
    sinais = []

    # V19.1: usa o status estilo Garmin (7d vs 28d ± 1 desvio) quando
    # disponível; senão cai nos cortes genéricos da V18.
    # Semântica por métrica: HRV baixo = ruim | RHR ALTO = ruim | sono baixo = ruim.
    bl = baseline or {}
    hrv_st = bl.get("hrv") or {}
    rhr_st = bl.get("rhr") or {}
    sono_st = bl.get("sono_h") or {}
    usa_baseline = bool(hrv_st or rhr_st or sono_st)

    if sono_st:
        if sono_st.get("status") in ("baixo", "desequilibrado"):
            sinais.append(
                f"sono {abs(sono_st.get('variacao_pct') or 0)}% abaixo do seu baseline "
                f"({sono_st.get('baseline_28d')}h)"
            )
    elif sono_medio is not None and sono_medio < 6.0:
        sinais.append("sono baixo")

    if hrv_st:
        if hrv_st.get("status") in ("baixo", "desequilibrado"):
            sinais.append(
                f"HRV {abs(hrv_st.get('variacao_pct') or 0)}% abaixo do seu baseline "
                f"({hrv_st.get('baseline_28d')})"
            )
    elif hrv_medio is not None and hrv_medio < 40:
        sinais.append("HRV baixo")

    if rhr_st:
        if rhr_st.get("status") == "alto":
            sinais.append(
                f"RHR {abs(rhr_st.get('variacao_pct') or 0)}% acima do seu baseline "
                f"({rhr_st.get('baseline_28d')} bpm)"
            )
    elif rhr_medio is not None and rhr_medio > 60:
        sinais.append("RHR elevado")

    if acwr is not None and acwr > 1.4:
        sinais.append("carga aguda elevada")

    if len(sinais) >= 3:
        alerta_recuperacao = "alto"
    elif len(sinais) == 2:
        alerta_recuperacao = "moderado"

    observacao_alerta = (
        "status 7d vs baseline 28d com faixa de ±1 desvio padrão (estilo Garmin)"
        if usa_baseline
        else "cortes genéricos (histórico de wellness insuficiente para baseline)"
    )

        # cargas diárias
    cargas_por_dia = {}

    for t in treinos:
        data = t.get("data")
        if not data:
            continue

        cargas_por_dia[data] = cargas_por_dia.get(data, 0) + _carga(t)

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
            "pace_100m": formatar_pace(pace_100m),   # V19.1: formato 1:55 min/100m
            "pace_100m_decimal": pace_100m,          # V19.1: decimal p/ comparação
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

        maior = max(treinos_grupo, key=lambda x: _carga(x), default=None)
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
            "observacao": observacao_alerta
        }
    }

def status_baseline(pontos, fim=None, janela_curta=7, janela_base=28):
    """V21.1: status estilo Garmin — média dos últimos 7 registros vs
    baseline de 28, com faixa de ±1 desvio padrão.
    'pontos' = [{"data": "2026-06-10", "valor": 55.0}, ...]
    Agora retorna também ultimo_dia e inclui_fim_periodo (frescura do dado),
    para o /prontidao avisar quando o registro de hoje ainda não sincronizou.
    Retorna None com menos de 14 registros (status não confiável)."""
    pontos = [p for p in (pontos or []) if p.get("valor") is not None]
    pontos.sort(key=lambda p: p.get("data") or "")

    if len(pontos) < janela_curta + 7:
        return None

    vals = [p["valor"] for p in pontos]

    recentes = vals[-janela_curta:]
    base = vals[-janela_base:] if len(vals) >= janela_base else vals

    media_recente = sum(recentes) / len(recentes)
    media_base = sum(base) / len(base)

    variancia = sum((x - media_base) ** 2 for x in base) / len(base)
    desvio = variancia ** 0.5

    limite_inferior = media_base - desvio
    limite_superior = media_base + desvio

    variacao_pct = ((media_recente - media_base) / media_base) * 100 if media_base else None

    if media_recente < media_base - (2 * desvio):
        status = "baixo"
    elif media_recente < limite_inferior:
        status = "desequilibrado"
    elif media_recente > limite_superior:
        status = "alto"
    else:
        status = "equilibrado"

    ultimo_dia = pontos[-1].get("data")
    fim_str = fim.isoformat() if hasattr(fim, "isoformat") else (str(fim) if fim else None)

    return {
        "status": status,
        "media_7d": round(media_recente, 1),
        "baseline_28d": round(media_base, 1),
        "limite_inferior": round(limite_inferior, 1),
        "limite_superior": round(limite_superior, 1),
        "variacao_pct": round(variacao_pct, 1) if variacao_pct is not None else None,
        "ultimo_dia": ultimo_dia,
        "inclui_fim_periodo": (ultimo_dia == fim_str) if fim_str else None,
    }

def coletar_baseline_wellness(base, auth, fim, janela_dias=35):
    """V19.1: status de wellness estilo Garmin. Busca dedicada dos últimos
    'janela_dias' até o FIM do período analisado (não o wellness do período,
    que pode ter só 7 dias e inviabilizaria o cálculo). Ordena cronologicamente
    e calcula, por métrica, média 7d vs baseline 28d com faixa de ±1 desvio.
    Falha silenciosa: retorna None e o sistema cai nos cortes genéricos."""
    try:
        base_old = fim - timedelta(days=janela_dias)

        resp = requests.get(
            f"{base}/wellness",
            params={
                "oldest": base_old.isoformat(),
                "newest": (fim + timedelta(days=1)).isoformat()
            },
            auth=auth,
            timeout=30
        )
        resp.raise_for_status()
        wel = resp.json()

        if isinstance(wel, dict):
            wel = list(wel.values())

        # Ordem cronológica é obrigatória: média 7d usa o FIM da série
        wel.sort(key=lambda w: str(w.get("id") or w.get("date") or w.get("day") or ""))

        # V21.1: cada ponto carrega a data — base da checagem de frescura
        def serie(campo, transform=lambda x: x):
            pontos = []
            for w in wel:
                data_w = str(w.get("id") or w.get("date") or w.get("day") or "")[:10]
                v = w.get(campo)
                if data_w and v is not None:
                    try:
                        pontos.append({"data": data_w, "valor": transform(v)})
                    except Exception:
                        pass
            return pontos

        baseline = {
            "janela": f"{base_old.isoformat()} a {fim.isoformat()}",
            "metodo": "media 7d vs baseline 28d, faixa de +/-1 desvio padrao",
            "hrv": status_baseline(serie("hrv"), fim),
            "rhr": status_baseline(serie("restingHR"), fim),
            "sono_h": status_baseline(serie("sleepSecs", lambda s: s / 3600), fim),
        }

        # Se nenhuma métrica gerou status, baseline é inútil
        if not any(baseline.get(k) for k in ("hrv", "rhr", "sono_h")):
            return None

        return baseline

    except Exception as e:
        print("Baseline indisponível:", e)
        return None

def coletar_intervals(dias=7, inicio=None, fim=None):
    hoje = hoje_local()  # V21.1: data local, não UTC do servidor

    if inicio and fim:
        inicio = normalizar_data_br(inicio) if isinstance(inicio, str) else inicio
        fim = normalizar_data_br(fim) if isinstance(fim, str) else fim
    else:
        # V20: fix off-by-one — "/relatorio 7" agora cobre exatamente 7 dias.
        # Antes: inicio = hoje - 7 com as duas pontas inclusivas = 8 dias.
        dias = max(1, dias)
        fim = hoje
        inicio = hoje - timedelta(days=dias - 1)

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

    # V23: aplica correção de carga (só bike) a cada treino. A partir daqui
    # carga_efetiva existe em todos os treinos e os cálculos leem dela.
    for t in treinos:
        t.update(carga_efetiva_treino(t))

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
        "carga_total": round(sum((t.get("carga_efetiva") if t.get("carga_efetiva") is not None else t.get("carga_treino")) or 0 for t in treinos)),
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
        "ramp_rate": round(ultimo.get("rampRate"), 1) if ultimo.get("rampRate") is not None else None,
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

    # V20: série diária compacta de wellness — matéria-prima da agregação
    # semanal do modo histórico (>30 dias). Nunca é enviada crua ao modelo:
    # os payloads escolhem suas chaves explicitamente.
    wellness_diario = []
    for w in wel:
        data_w = str(w.get("id") or w.get("date") or w.get("day") or "")[:10]
        if not data_w:
            continue
        wellness_diario.append({
            "data": data_w,
            "hrv": w.get("hrv"),
            "rhr": w.get("restingHR"),
            "sono_h": round(w.get("sleepSecs") / 3600, 1) if w.get("sleepSecs") else None,
            "stress": w.get("avgStress"),
            "body_battery": w.get("bodyBattery"),
            "ramp": w.get("rampRate"),
        })

    # V19.1: status de wellness (7d vs 28d) ancorado no FIM do período
    baseline = coletar_baseline_wellness(base, auth, fim)

    resultado = {
        "periodo": f"{inicio.isoformat()} a {fim.isoformat()}",
        "dias": (fim - inicio).days + 1,
        "totais": totais,
        "treinos": treinos,
        "condicionamento": condicionamento,
        "recuperacao": recuperacao,
        "baseline": baseline,
        "wellness_diario": wellness_diario,
    }

    resultado["indicadores"] = calcular_indicadores(resultado, baseline)

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

    if t.get("carga_efetiva") is not None:
        if t.get("carga_corrigida"):
            partes.append(
                f"carga {round(t.get('carga_efetiva'))} "
                f"[corrigida; original {round(t.get('carga_treino') or 0)}]"
            )
        else:
            partes.append(f"carga {t.get('carga_efetiva')}")
    elif t.get("carga_treino") is not None:
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


def formatar_baseline(bl):
    """V19.1: exibe o status de wellness (7d vs baseline 28d) no /metricas."""
    if not bl:
        return "sem dado (histórico de wellness insuficiente)"

    linhas = [f"Janela: {bl.get('janela', '-')}"]

    def linha(nome, st, sufixo=""):
        if not st:
            return None
        texto = (
            f"{nome}: {st.get('media_7d')}{sufixo} (7d) vs "
            f"{st.get('baseline_28d')}{sufixo} (28d) | "
            f"variação {st.get('variacao_pct')}% | status: {st.get('status')}"
        )
        if st.get("ultimo_dia"):
            texto += f" | até {st['ultimo_dia']}"
        return texto

    for nome, chave, suf in [("HRV", "hrv", ""), ("RHR", "rhr", " bpm"), ("Sono", "sono_h", " h")]:
        l = linha(nome, bl.get(chave), suf)
        if l:
            linhas.append(l)

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

    # V23: aviso de correção de carga (sensor de potência inconsistente)
    avisos_carga = avisos_carga_corrigida(treinos)
    if avisos_carga:
        linhas.append("")
        linhas.append("⚠️ Carga corrigida via FC (potência inconsistente):")
        for a in avisos_carga:
            linhas.append(f"• {a}")

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
    linhas.append(f"Rampa (CTL/sem): {valor(cond.get('ramp_rate'))}")
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

    linhas.append("3.1 STATUS WELLNESS (média 7d vs baseline 28d)")
    linhas.append(formatar_baseline(d.get("baseline")))
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


def treino_para_payload(t):
    """V19: monta o dict de um treino para envio ao modelo.
    Compartilhado entre /relatorio e /analise."""
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
        "carga_efetiva": t.get("carga_efetiva") if t.get("carga_corrigida") else None,
        "carga_corrigida": t.get("carga_corrigida") or None,
        "intensidade": t.get("intensidade"),
        "trimp": t.get("trimp"),
        "ftp": t.get("ftp"),
        "lthr": t.get("lthr"),
        "hr_load": t.get("hr_load"),
        "power_load": t.get("power_load"),
        "comprimentos": t.get("comprimentos"),
        "comprimento_piscina": t.get("comprimento_piscina"),
    }

    return limpar_vazios(item)


def preparar_dados_relatorio(d):
    """V20: roteador por janela.
    Até 30 dias -> modo operacional (idêntico ao comportamento anterior).
    Acima de 30 -> modo histórico (agregação semanal, sem treinos individuais)."""
    if (d.get("dias") or 0) > 30:
        return preparar_dados_relatorio_historico(d)

    return preparar_dados_relatorio_operacional(d)


def preparar_dados_relatorio_operacional(d):
    """Modo operacional (≤30 dias): payload completo com treinos individuais.
    Comportamento idêntico ao da versão anterior — nada mudou aqui."""
    treinos = d.get("treinos", [])
    treinos_limpos = [treino_para_payload(t) for t in treinos]

    # Remove apenas a nota interna do alerta enviado ao modelo.
    # O /metricas continua exibindo a observacao normalmente.
    indicadores = dict(d.get("indicadores") or {})
    alerta = dict(indicadores.get("alerta_recuperacao") or {})
    alerta.pop("observacao", None)
    indicadores["alerta_recuperacao"] = alerta

    dados = {
        "periodo": d.get("periodo"),
        "dias": d.get("dias"),
        "totais": d.get("totais"),
        "condicionamento": d.get("condicionamento"),
        "recuperacao": d.get("recuperacao"),
        "baseline": d.get("baseline"),
        "indicadores": indicadores,
        "treinos": treinos_limpos,
    }

    return limpar_vazios(dados)


def _semana_vazia():
    return {
        "sessoes": 0, "carga": 0, "dur_min": 0,
        "corrida_km": 0, "bike_km": 0, "natacao_m": 0, "forca_sessoes": 0,
        "_hrv": [], "_rhr": [], "_sono": [], "_stress": [], "_ramp": [],
    }


def agregar_semanal(d):
    """V20: agrega treinos e wellness em blocos de 7 dias a partir do início
    do período. O detalhe fica no Python; a IA só interpreta a trajetória."""
    try:
        inicio = datetime.fromisoformat(d.get("periodo", "").split(" a ")[0]).date()
    except Exception:
        return None

    def bloco(data_str):
        try:
            delta = (datetime.fromisoformat(data_str).date() - inicio).days
            return delta // 7 if delta >= 0 else None
        except Exception:
            return None

    semanas = {}

    for t in d.get("treinos", []):
        b = bloco(t.get("data") or "")
        if b is None:
            continue

        s = semanas.setdefault(b, _semana_vazia())
        s["sessoes"] += 1
        s["carga"] += _carga(t)
        s["dur_min"] += t.get("dur_min") or 0

        tipo = (t.get("tipo") or "").lower()
        if "run" in tipo:
            s["corrida_km"] += t.get("dist_km") or 0
        elif "ride" in tipo or "bike" in tipo:
            s["bike_km"] += t.get("dist_km") or 0
        elif "swim" in tipo:
            s["natacao_m"] += (t.get("dist_km") or 0) * 1000
        elif "strength" in tipo or "weight" in tipo:
            s["forca_sessoes"] += 1

    for w in d.get("wellness_diario", []):
        b = bloco(w.get("data") or "")
        if b is None:
            continue

        s = semanas.setdefault(b, _semana_vazia())
        if w.get("hrv") is not None:
            s["_hrv"].append(w["hrv"])
        if w.get("rhr") is not None:
            s["_rhr"].append(w["rhr"])
        if w.get("sono_h") is not None:
            s["_sono"].append(w["sono_h"])
        if w.get("stress") is not None:
            s["_stress"].append(w["stress"])
        if w.get("ramp") is not None:
            s["_ramp"].append(w["ramp"])

    if not semanas:
        return None

    def media_lista(lista):
        return round(sum(lista) / len(lista), 1) if lista else None

    resumo = []

    for b in sorted(semanas):
        s = semanas[b]
        ini_b = inicio + timedelta(days=b * 7)
        fim_b = ini_b + timedelta(days=6)

        resumo.append(limpar_vazios({
            "semana": b + 1,
            "intervalo": f"{ini_b.strftime('%d/%m')}-{fim_b.strftime('%d/%m')}",
            "sessoes": s["sessoes"],
            "carga": round(s["carga"]),
            "dur_min": round(s["dur_min"]),
            "corrida_km": round(s["corrida_km"], 1) or None,
            "bike_km": round(s["bike_km"], 1) or None,
            "natacao_m": round(s["natacao_m"]) or None,
            "forca_sessoes": s["forca_sessoes"] or None,
            "hrv": media_lista(s["_hrv"]),
            "rhr": media_lista(s["_rhr"]),
            "sono_h": media_lista(s["_sono"]),
            "stress": media_lista(s["_stress"]),
            "rampa": media_lista(s["_ramp"]),
        }))

    return resumo


def destaques_semanais(resumo):
    """V20: melhor/pior semana — calculado em Python, custo zero de token."""
    if not resumo:
        return None

    def ref(s):
        return f"semana {s['semana']} ({s.get('intervalo')})" if s else None

    com_carga = [s for s in resumo if s.get("carga")]
    maior_carga = max(com_carga, key=lambda s: s["carga"], default=None)
    menor_carga = min(com_carga, key=lambda s: s["carga"], default=None)

    com_hrv = [s for s in resumo if s.get("hrv") is not None]
    pior_rec = min(com_hrv, key=lambda s: s["hrv"], default=None)
    melhor_rec = max(com_hrv, key=lambda s: s["hrv"], default=None)

    return limpar_vazios({
        "semana_maior_carga": ref(maior_carga),
        "semana_menor_carga": ref(menor_carga),
        "semana_pior_recuperacao_hrv": ref(pior_rec),
        "semana_melhor_recuperacao_hrv": ref(melhor_rec),
    })


def preparar_dados_relatorio_historico(d):
    """V20: modo histórico (>30 dias). Treino individual sai do payload;
    entra agregação semanal + top 5 outliers por carga. Corte de 30-60%
    no input sem perder a leitura de trajetória."""
    indicadores = dict(d.get("indicadores") or {})
    alerta = dict(indicadores.get("alerta_recuperacao") or {})
    alerta.pop("observacao", None)
    indicadores["alerta_recuperacao"] = alerta

    # Detalhe por treino sai do modo histórico; trajetória entra.
    for k in (
        "maior_treino_carga", "maior_treino_duracao", "maior_treino_distancia",
        "maior_carga_por_modalidade", "metricas_natacao",
    ):
        indicadores.pop(k, None)

    resumo = agregar_semanal(d)

    treinos = d.get("treinos", [])
    outliers = sorted(
        treinos,
        key=lambda t: _carga(t),
        reverse=True
    )[:5]

    dados = {
        "modo": "historico",
        "periodo": d.get("periodo"),
        "dias": d.get("dias"),
        "totais": d.get("totais"),
        "condicionamento": d.get("condicionamento"),
        "recuperacao": d.get("recuperacao"),
        "baseline": d.get("baseline"),
        "indicadores": indicadores,
        "resumo_semanal": resumo,
        "destaques_semanais": destaques_semanais(resumo),
        "outliers_treinos_top5_carga": [treino_para_payload(t) for t in outliers],
    }

    return limpar_vazios(dados)


def filtrar_dados_para_analise(d, dominios):
    """V19: monta o payload focado do /analise. Envia ao modelo só o
    subconjunto relevante ao(s) domínio(s) pedido(s) — mais barato e
    mais focado que o relatório completo."""
    if "geral" in dominios:
        return preparar_dados_relatorio(d)

    rec = d.get("recuperacao") or {}
    ind = d.get("indicadores") or {}
    cond = d.get("condicionamento") or {}
    totais = d.get("totais") or {}
    treinos = d.get("treinos") or []

    payload = {
        "periodo": d.get("periodo"),
        "dias": d.get("dias"),
        "baseline": d.get("baseline"),
        # Contexto de carga sempre presente: viabiliza correlações
        "contexto_carga": {
            "fitness_ctl": cond.get("fitness_ctl"),
            "fadiga_atl": cond.get("fadiga_atl"),
            "forma_tsb": cond.get("forma_tsb"),
            "ramp_rate": cond.get("ramp_rate"),
            "acwr": ind.get("acwr"),
            "carga_total": totais.get("carga_total"),
            "total_sessoes": totais.get("total_sessoes"),
            "monotonia": ind.get("monotonia_carga"),
            "strain": ind.get("strain"),
        },
    }

    esportes = [x for x in dominios if x in MAPA_TIPO_DOMINIO]

    if esportes:
        tipos = []
        for e in esportes:
            tipos.extend(MAPA_TIPO_DOMINIO[e])

        treinos_filtrados = [
            t for t in treinos
            if any(k in (t.get("tipo") or "").lower() for k in tipos)
        ]

        payload["treinos"] = [treino_para_payload(t) for t in treinos_filtrados]
        payload["distribuicao_carga_pct"] = ind.get("distribuicao_carga_pct")

        if "natacao" in esportes:
            payload["metricas_natacao"] = ind.get("metricas_natacao")

        if "bike" in esportes:
            payload["potencia_bike"] = {
                "ftp_detectado": ind.get("ftp_bike_detectado"),
                "eftp": ind.get("eftp_intervals"),
                "diferenca_ftp_eftp": ind.get("diferenca_ftp_eftp"),
                "vo2max": cond.get("vo2max"),
                "wprime": cond.get("wprime"),
                "pmax": cond.get("pmax"),
            }

        if "corrida" in esportes and "bike" in esportes:
            payload["razao_carga_corrida_bike"] = ind.get("razao_carga_corrida_bike")

    if "sono" in dominios:
        payload["sono"] = {
            "sono_medio_h": rec.get("sono_medio_h"),
            "sono_score_medio": rec.get("sono_score_medio"),
            "tendencia_sono_h": rec.get("tendencia_sono_h"),
        }
        payload["cargas_diarias"] = cargas_diarias(treinos)

    if "recuperacao" in dominios:
        alerta = dict(ind.get("alerta_recuperacao") or {})
        alerta.pop("observacao", None)

        payload["recuperacao"] = {
            "hrv_medio": rec.get("hrv_medio"),
            "rhr_medio": rec.get("rhr_medio"),
            "readiness_medio": rec.get("readiness_medio"),
            "stress_medio": rec.get("stress_medio"),
            "body_battery_medio": rec.get("body_battery_medio"),
            "spo2_medio": rec.get("spo2_medio"),
            "tendencia_hrv": rec.get("tendencia_hrv"),
            "tendencia_rhr": rec.get("tendencia_rhr"),
            "tendencia_sono_h": rec.get("tendencia_sono_h"),
            "sono_medio_h": rec.get("sono_medio_h"),
            "alerta": alerta,
        }
        payload["cargas_diarias"] = cargas_diarias(treinos)

    if "peso" in dominios:
        payload["peso"] = {
            "peso_medio_kg": rec.get("peso_medio"),
            "calorias_periodo": totais.get("calorias"),
        }

    return limpar_vazios(payload)
#------------------------------------------------------------------

# =============================================================================
# V21: PRONTIDÃO DIÁRIA (semáforo 100% Python, custo zero de GPT)
# =============================================================================

def calcular_prontidao(d):
    """V21: semáforo de prontidão por pontuação de risco.
    0-1 ponto = 🟢 verde | 2-4 = 🟡 amarelo | 5+ = 🔴 vermelho.
    Usa status vs baseline quando disponível; senão cortes genéricos."""
    ind = d.get("indicadores") or {}
    cond = d.get("condicionamento") or {}
    rec = d.get("recuperacao") or {}
    bl = d.get("baseline") or {}
    treinos = d.get("treinos") or []

    pontos = 0
    motivos = []
    positivos = []

    hrv_st = bl.get("hrv") or {}
    rhr_st = bl.get("rhr") or {}
    sono_st = bl.get("sono_h") or {}

    # --- HRV (peso maior: melhor preditor isolado de recuperação) ---
    st = hrv_st.get("status")
    if st == "baixo":
        pontos += 3
        motivos.append(f"HRV bem abaixo do baseline ({hrv_st.get('variacao_pct')}%)")
    elif st == "desequilibrado":
        pontos += 2
        motivos.append(f"HRV desequilibrado ({hrv_st.get('variacao_pct')}% vs baseline)")
    elif st in ("equilibrado", "alto"):
        positivos.append("HRV em dia")
    elif rec.get("hrv_medio") is not None and rec["hrv_medio"] < 40:
        pontos += 2
        motivos.append("HRV baixo (corte genérico, sem baseline)")

    # --- RHR (alto = ruim) ---
    st = rhr_st.get("status")
    if st == "alto":
        pontos += 2
        motivos.append(f"RHR {rhr_st.get('variacao_pct')}% acima do baseline")
    elif st in ("equilibrado", "baixo"):
        positivos.append("RHR estável")
    elif rec.get("rhr_medio") is not None and rec["rhr_medio"] > 60:
        pontos += 1
        motivos.append("RHR elevado (corte genérico, sem baseline)")

    # --- Sono ---
    st = sono_st.get("status")
    if st in ("baixo", "desequilibrado"):
        pontos += 2
        motivos.append(f"sono {abs(sono_st.get('variacao_pct') or 0)}% abaixo do baseline")
    elif st in ("equilibrado", "alto"):
        positivos.append("sono em dia")
    elif rec.get("sono_medio_h") is not None and rec["sono_medio_h"] < 6.0:
        pontos += 2
        motivos.append("sono curto (corte genérico, sem baseline)")

    # --- ACWR ---
    acwr = ind.get("acwr")
    if acwr is not None:
        if acwr > 1.5:
            pontos += 3
            motivos.append(f"ACWR {acwr} (risco de lesão)")
        elif acwr > 1.3:
            pontos += 2
            motivos.append(f"ACWR {acwr} (carga aguda em zona de atenção)")
        elif acwr < 0.8:
            positivos.append(f"ACWR {acwr} (carga aguda baixa, janela para progredir)")
        else:
            positivos.append(f"ACWR {acwr} (carga controlada)")

    # --- TSB / Forma ---
    tsb = cond.get("forma_tsb")
    if tsb is not None:
        if tsb < -20:
            pontos += 2
            motivos.append(f"TSB {tsb} (fadiga acumulada relevante)")
        elif tsb < -10:
            pontos += 1
            motivos.append(f"TSB {tsb} (carregado)")
        elif tsb > 5:
            positivos.append(f"TSB {tsb} (fresco)")
        # V23.2: entre -10 e +5 é neutro — não conta a favor nem contra.
        # Não entra em positivos para não dar falsa sensação de vantagem.

    # --- V22: Rampa (variação de CTL/semana, direto da API) ---
    # Regra de ouro: rampa alta só é problema quando o corpo não acompanha.
    ramp = cond.get("ramp_rate")
    hrv_ruim = hrv_st.get("status") in ("baixo", "desequilibrado")

    if ramp is not None:
        if ramp > 8:
            pontos += 2
            motivos.append(f"rampa {ramp}/sem (subida agressiva de carga)")
        elif ramp > 4:
            if hrv_ruim:
                pontos += 1
                motivos.append(f"rampa {ramp}/sem com HRV abaixo do baseline (construindo sem absorver)")
            else:
                positivos.append(f"rampa {ramp}/sem (construção acelerada, recuperação acompanhando)")
        elif ramp >= 0:
            positivos.append(f"rampa {ramp}/sem (progressão sustentável)")
        else:
            positivos.append(f"rampa {ramp}/sem (descarregando — bom para absorver)")

    # --- Monotonia ---
    mono = ind.get("monotonia_carga")
    if mono is not None and mono > 2.0:
        pontos += 1
        motivos.append(f"monotonia {mono} (carga sem variação)")

    # --- Treino de ontem ---
    ontem = (hoje_local() - timedelta(days=1)).isoformat()  # V21.1: data local
    carga_ontem = round(sum(
        _carga(t) for t in treinos if t.get("data") == ontem
    ))
    carga_dia = ind.get("carga_por_dia") or 0

    if carga_dia and carga_ontem > carga_dia * 1.8:
        pontos += 1
        motivos.append(f"treino pesado ontem (carga {carga_ontem} vs média diária {carga_dia})")
    elif carga_ontem == 0:
        positivos.append("descanso ontem")

    # --- V21.1: frescura do dado ---
    # Semáforo confiante com dado defasado é pior que semáforo ausente.
    avisos = []

    def desatualizado(st):
        return bool(st) and st.get("inclui_fim_periodo") is False

    for nome, st in (("HRV", hrv_st), ("RHR", rhr_st), ("sono", sono_st)):
        if desatualizado(st):
            avisos.append(f"{nome} de hoje ainda não sincronizou (último registro: {st.get('ultimo_dia')})")

    # Cautela: sono de hoje ausente APÓS dia de carga acima da média.
    # Só nesse cruzamento — atraso de sincronização sozinho não pune.
    if desatualizado(sono_st) and carga_dia and carga_ontem > carga_dia:
        pontos += 1
        motivos.append("sono de hoje ausente após dia de carga acima da média (cautela)")

    ultimos_dias = [
        st.get("ultimo_dia") for st in (hrv_st, rhr_st, sono_st) if st.get("ultimo_dia")
    ]
    dados_ate = max(ultimos_dias) if ultimos_dias else None

    # --- Classificação ---
    # V23.2: identifica se o alerta vem de CARGA ou de RECUPERAÇÃO, para
    # dar ação específica. Inspeciona os motivos já decididos (não recalcula),
    # então no pior caso cai na ação genérica — sem risco de regressão.
    motivos_txt = " ".join(motivos).lower()
    alerta_por_carga = any(
        chave in motivos_txt
        for chave in ("treino pesado ontem", "monotonia", "strain", "acwr", "rampa")
    )
    alerta_por_recuperacao = any(
        chave in motivos_txt
        for chave in ("hrv", "rhr", "sono")
    )

    if pontos >= 5:
        nivel, emoji, rotulo = "vermelho", "🔴", "Reduzir"
        if alerta_por_recuperacao:
            acao = "Reduzir intensidade hoje. Sinais de recuperação comprometida: descanso ativo ou off, e prioridade número um é dormir bem."
        else:
            acao = "Reduzir intensidade hoje. Descanso ativo, mobilidade ou off. Prioridade número um: dormir bem."
    elif pontos >= 2:
        nivel, emoji, rotulo = "amarelo", "🟡", "Atenção"
        if alerta_por_carga and not alerta_por_recuperacao:
            acao = "Treinar leve. Hoje o objetivo é absorver a carga recente: Z1/Z2 baixo, sem tiros, sem força pesada e sem volume longo."
        elif alerta_por_recuperacao:
            acao = "Treinar leve e priorizar recuperação. Z2 baixo, evitar tiros e volume longo; cuidar do sono hoje."
        else:
            acao = "Treinar leve. Manter Z2, evitar tiros, séries pesadas e volume longo."
    else:
        nivel, emoji, rotulo = "verde", "🟢", "Treinar normal"
        acao = "Sinal verde. Siga o plano; se houver intensidade programada, hoje é dia."

    if not bl:
        motivos.append("baseline indisponível — leitura com confiabilidade reduzida")

    return {
        "nivel": nivel,
        "emoji": emoji,
        "rotulo": rotulo,
        "pontos": pontos,
        "motivos": motivos,
        "positivos": positivos,
        "acao": acao,
        "avisos": avisos,
        "dados_ate": dados_ate,
        "contexto": limpar_vazios({
            "ctl": cond.get("fitness_ctl"),
            "atl": cond.get("fadiga_atl"),
            "tsb": tsb,
            "rampa": ramp,
            "acwr": acwr,
            "monotonia": mono,
            "strain": ind.get("strain"),
            "carga_ontem": carga_ontem or None,
            "carga_media_dia": carga_dia or None,
        }),
    }


def formatar_prontidao(p):
    """V21: saída em texto puro do semáforo."""
    linhas = []
    linhas.append(f"{p['emoji']} PRONTIDÃO DE HOJE — {p['rotulo']} ({p['pontos']} pts)")
    linhas.append("")

    if p["motivos"]:
        linhas.append("Sinais de alerta:")
        for m in p["motivos"]:
            linhas.append(f"• {m}")
        linhas.append("")

    if p["positivos"]:
        linhas.append("A favor:")
        for m in p["positivos"]:
            linhas.append(f"• {m}")
        linhas.append("")

    linhas.append("Ação:")
    linhas.append(p["acao"])

    # V21.2: painel de carga estruturado
    ctx = p.get("contexto") or {}
    if ctx:
        linhas.append("")
        linhas.append("Painel de carga:")

        ctl = ctx.get("ctl")
        atl = ctx.get("atl")
        tsb = ctx.get("tsb")
        if ctl is not None:
            linhas.append(f"  Aptidão (CTL): {ctl}")
        if atl is not None:
            linhas.append(f"  Fadiga   (ATL): {atl}")
        if tsb is not None:
            estado_tsb = "fresco" if tsb > 5 else ("carregado" if tsb < -10 else "neutro")
            linhas.append(f"  Forma    (TSB): {tsb}  [{estado_tsb}]")
        ramp = ctx.get("rampa")
        if ramp is not None:
            zona_ramp = (
                "agressiva" if ramp > 8
                else "acelerada" if ramp > 4
                else "sustentável" if ramp >= 0
                else "descarregando"
            )
            linhas.append(f"  Rampa: {ramp}/sem  [{zona_ramp}]")
        if ctx.get("acwr") is not None:
            linhas.append(f"  ACWR: {ctx['acwr']}")

        strain = ctx.get("strain")
        mono = ctx.get("monotonia")
        if strain is not None or mono is not None:
            linhas.append("")
            linhas.append("Qualidade da carga:")
        if mono is not None:
            zona_mono = "boa variação" if mono < 1.5 else ("atenção" if mono <= 2.0 else "uniforme demais")
            linhas.append(f"  Monotonia: {mono}  [{zona_mono}]")

        # V22.1: strain classificado + leitura combinada com monotonia.
        # Faixas genéricas calibradas para carga/dia ~40-60; revisitar se
        # o volume mudar muito (ideal futuro: baseline individual).
        if strain is not None:
            if strain < 80:
                zona_strain, comentario_strain = "baixo", "carga acumulada tranquila"
            elif strain < 120:
                zona_strain, comentario_strain = "moderado", "carga acumulada controlada"
            elif strain < 180:
                zona_strain, comentario_strain = "alto", "atenção à fadiga acumulada"
            else:
                zona_strain, comentario_strain = "muito alto", "risco maior de fadiga acumulada"

            linhas.append(f"  Strain: {strain}  [{zona_strain}]")

            # Leitura: o combo mais traiçoeiro é carga ok + variação baixa.
            # V23.2: quando o strain já está alto (>=120), a frase não
            # minimiza mais com "não está explosiva" — pede contraste real.
            if mono is not None and mono >= 2.0 and strain >= 120:
                linhas.append(
                    "  Leitura: carga acumulada já está alta e a variação está baixa; "
                    "hoje pede contraste real — leve de verdade ou descanso ativo."
                )
            elif mono is not None and mono >= 2.0 and strain >= 80:
                linhas.append(
                    "  Leitura: carga não está explosiva, mas a variação está baixa; "
                    "alterne melhor dias leves e fortes."
                )
            elif strain >= 120:
                linhas.append(
                    "  Leitura: carga acumulada alta; monitore sono, HRV e sensação de pernas."
                )
            else:
                linhas.append(f"  Leitura: {comentario_strain}.")

        if ctx.get("carga_ontem") is not None:
            ref = f" (média/dia: {ctx['carga_media_dia']})" if ctx.get("carga_media_dia") else ""
            linhas.append(f"  Carga ontem: {ctx['carga_ontem']}{ref}")

    # V21.1: transparência sobre frescura do dado
    if p.get("avisos"):
        linhas.append("")
        linhas.append(f"⏳ Atenção — prontidão calculada com dados até {p.get('dados_ate')}:")
        for a in p["avisos"]:
            linhas.append(f"• {a}")

    return "\n".join(linhas)


async def prontidao_command(update, context):
    """V21: /prontidao — semáforo do dia, zero GPT.
    /prontidao ia — anexa comentário curto do MODEL_FAST (payload mínimo)."""
    uid = update.effective_user.id
    quer_ia = bool(context.args) and "ia" in [a.lower() for a in context.args]

    await context.bot.send_message(
        update.effective_chat.id,
        "🚦 Calculando prontidão de hoje..."
    )

    try:
        d = coletar_intervals(dias=7)
    except Exception as e:
        print("Erro prontidao:", e)
        await context.bot.send_message(
            update.effective_chat.id,
            "⚠️ Falha ao coletar dados do Intervals.icu."
        )
        return

    p = calcular_prontidao(d)
    texto = formatar_prontidao(p)

    # V23: se a carga de algum treino foi corrigida no período, sinaliza
    _avisos_c = avisos_carga_corrigida(d.get("treinos", []))
    if _avisos_c:
        texto += "\n\n⚠️ Carga corrigida via FC (potência inconsistente):\n" + "\n".join(
            f"• {a}" for a in _avisos_c
        )
        # V23.1: leva a transparência para o estado salvo, então a conversa
        # de decisão ("sigo o plano?") também sabe que houve correção.
        p["cargas_corrigidas"] = _avisos_c

    # V22.2: rastro reutilizável — estado estruturado + UMA linha no contexto
    pctx = p.get("contexto") or {}
    salvar_estado_atual(uid, "prontidao", p)
    try:
        salvar_contexto(
            uid,
            (
                f"Prontidão de hoje: {p.get('emoji')} {p.get('rotulo')} ({p.get('pontos')} pts). "
                f"TSB {pctx.get('tsb')}, ACWR {pctx.get('acwr')}, rampa {pctx.get('rampa')}, "
                f"monotonia {pctx.get('monotonia')}, strain {pctx.get('strain')}."
            ),
            papel="sophos"
        )
    except Exception as e:
        print("Erro ao salvar linha de prontidão no contexto:", e)

    if quer_ia:
        try:
            resumo_json = json.dumps(p, ensure_ascii=False, separators=(",", ":"), default=str)
            comentario = chamar_gpt_sync(
                [
                    {"role": "system", "content": ESTILO_SOPHOS},
                    {
                        "role": "user",
                        "content": (
                            "Semáforo de prontidão de hoje (já calculado, não recalcule):\n"
                            f"{resumo_json}\n\n"
                            "Comente em no máximo 3 frases, em texto puro, com tom de coach: "
                            "o que esse quadro significa na prática e o que priorizar hoje."
                        )
                    },
                ],
                model=MODEL_FAST,
                max_tokens=400,
                user_id=uid
            )
            texto += "\n\n🧠 Sophos: " + comentario.strip()
        except Exception as e:
            print("Erro comentário IA prontidao:", e)

    context.user_data["ultima_resposta"] = texto

    await enviar_texto_longo(
        context,
        update.effective_chat.id,
        texto,
        reply_markup=marcadores_feedback("prontidao")
    )


async def relatorio_command(update, context):
    uid = update.effective_user.id

    try:
        dias, inicio, fim = parse_periodo_args(context.args)
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

        dias_relatorio = d.get("dias", dias)
        modo_historico = dias_relatorio > 30
        modelo_relatorio = MODEL_FAST if dias_relatorio < 7 else MODEL_MAIN
        limite_saida = 2500 if dias_relatorio < 7 else 3500

    except Exception as e:
        print("Erro relatorio:", e)
        await context.bot.send_message(
            update.effective_chat.id,
            "⚠️ Falha ao coletar dados do Intervals.icu. Verifique API Key e Athlete ID."
        )
        return

    dados_json = json.dumps(
        preparar_dados_relatorio(d),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str
    )

    # V20: prompt por janela — operacional (≤30d) ou histórico (>30d)
    prompt_sistema = PROMPT_RELATORIO_HISTORICO if modo_historico else PROMPT_RELATORIO

    resposta = chamar_gpt_sync(
        [
            {"role": "system", "content": ESTILO_SOPHOS + "\n\n" + prompt_sistema},
            {"role": "user", "content": f"Analise os dados do período {d['periodo']}.\n\nDADOS:\n{dados_json}"},
        ],
        model=modelo_relatorio,
        max_tokens=limite_saida,
        user_id=uid
    )

    context.user_data["ultima_resposta"] = resposta

    # V22.2: estado reutilizável do relatório — COMPACTO de propósito
    # (condicionamento + alerta + baseline + 600 chars de resumo; nada de
    # indicadores inteiros, que inflariam a injeção no chat).
    cond_rel = d.get("condicionamento") or {}
    alerta_rel = ((d.get("indicadores") or {}).get("alerta_recuperacao") or {})
    salvar_estado_atual(uid, "ultimo_relatorio", {
        "periodo": d.get("periodo"),
        "dias": d.get("dias"),
        "condicionamento": cond_rel,
        "alerta_recuperacao": {
            "nivel": alerta_rel.get("nivel"),
            "sinais": alerta_rel.get("sinais"),
        },
        "baseline": d.get("baseline"),
        "resumo_texto": resposta[:600],
    })
    try:
        salvar_contexto(
            uid,
            (
                f"Relatório {d.get('periodo')} gerado: CTL {cond_rel.get('fitness_ctl')}, "
                f"TSB {cond_rel.get('forma_tsb')}, rampa {cond_rel.get('ramp_rate')}, "
                f"alerta de recuperação {alerta_rel.get('nivel')}."
            ),
            papel="sophos"
        )
    except Exception as e:
        print("Erro ao salvar linha do relatório no contexto:", e)

    # V23: prefixo de aviso se houve correção de carga no período
    _avisos_c = avisos_carga_corrigida(d.get("treinos", []))
    prefixo_aviso = ""
    if _avisos_c:
        prefixo_aviso = (
            "⚠️ Carga corrigida via FC (potência inconsistente): "
            + "; ".join(_avisos_c) + "\n\n"
        )

    await enviar_texto_longo(
        context,
        update.effective_chat.id,
        "📊 Relatório de Performance:\n\n" + prefixo_aviso + resposta,
        reply_markup=marcadores_feedback("relatorio")
    )

async def analise_command(update, context):
    """V19: /analise <pedido livre>
    Ex: /analise sono nos últimos 30 dias
        /analise corrida e natação último mês
        /analise hrv e sono 2 semanas
        /analise bike 01/05/26 31/05/26"""
    uid = update.effective_user.id

    pedido = " ".join(context.args) if context.args else ""

    if not pedido.strip():
        await context.bot.send_message(
            update.effective_chat.id,
            "Diga o que quer analisar. Exemplos:\n"
            "/analise sono nos últimos 30 dias\n"
            "/analise corrida e natação último mês\n"
            "/analise hrv e sono 2 semanas\n"
            "/analise bike 01/05/26 31/05/26\n"
            "Focos: corrida, bike, natação, força, sono, recuperação (HRV/RHR), peso."
        )
        return

    dias, inicio, fim, dominios = interpretar_pedido_analise(pedido)

    nomes = ", ".join(NOMES_DOMINIO.get(x, x) for x in dominios)

    msg_status = (
        f"🔍 Analisando {nomes} de {inicio} a {fim}..."
        if inicio and fim
        else f"🔍 Analisando {nomes} dos últimos {dias} dias..."
    )

    await context.bot.send_message(update.effective_chat.id, msg_status)

    try:
        d = coletar_intervals(dias=dias, inicio=inicio, fim=fim)
    except Exception as e:
        print("Erro analise:", e)
        await context.bot.send_message(
            update.effective_chat.id,
            "⚠️ Falha ao coletar dados do Intervals.icu."
        )
        return

    payload = filtrar_dados_para_analise(d, dominios)

    dados_json = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str
    )

    dias_efetivos = d.get("dias", dias)
    multi_dominio = len(dominios) >= 2 or "geral" in dominios
    modelo = MODEL_MAIN if (dias_efetivos >= 21 or multi_dominio) else MODEL_FAST

    resposta = chamar_gpt_sync(
        [
            {"role": "system", "content": ESTILO_SOPHOS + "\n\n" + PROMPT_ANALISE},
            {
                "role": "user",
                "content": (
                    f"Pedido original do usuário: {pedido}\n"
                    f"Foco(s) identificado(s): {nomes}\n"
                    f"Período: {d.get('periodo')}\n\n"
                    f"DADOS:\n{dados_json}"
                )
            },
        ],
        model=modelo,
        max_tokens=2500,
        user_id=uid
    )

    context.user_data["ultima_resposta"] = resposta

    # V23: aviso de correção de carga, se houver
    _avisos_c = avisos_carga_corrigida(d.get("treinos", []))
    prefixo_aviso = ""
    if _avisos_c:
        prefixo_aviso = (
            "⚠️ Carga corrigida via FC (potência inconsistente): "
            + "; ".join(_avisos_c) + "\n\n"
        )

    await enviar_texto_longo(
        context,
        update.effective_chat.id,
        f"🔍 Análise focada ({nomes}):\n\n" + prefixo_aviso + resposta,
        reply_markup=marcadores_feedback("analise")
    )

async def comparar_command(update, context):
    """V19: /comparar <dias> — período atual vs período imediatamente anterior.
    Ex: /comparar 7 → últimos 7 dias vs os 7 dias antes deles."""
    uid = update.effective_user.id

    try:
        dias = int(context.args[0]) if context.args else 7
    except (ValueError, IndexError):
        await context.bot.send_message(
            update.effective_chat.id,
            "Formato inválido. Use: /comparar 7"
        )
        return

    dias = max(2, min(dias, 60))

    hoje = hoje_local()  # V21.1: data local, não UTC do servidor
    fim_atual = hoje
    inicio_atual = hoje - timedelta(days=dias - 1)
    fim_anterior = inicio_atual - timedelta(days=1)
    inicio_anterior = fim_anterior - timedelta(days=dias - 1)

    await context.bot.send_message(
        update.effective_chat.id,
        f"⚖️ Comparando últimos {dias} dias vs os {dias} dias anteriores..."
    )

    try:
        d_atual = coletar_intervals(inicio=inicio_atual, fim=fim_atual)
        d_anterior = coletar_intervals(inicio=inicio_anterior, fim=fim_anterior)
    except Exception as e:
        print("Erro comparar:", e)
        await context.bot.send_message(
            update.effective_chat.id,
            "⚠️ Falha ao coletar dados do Intervals.icu."
        )
        return

    def resumo_para_comparacao(d):
        # Indicadores + totais + condicionamento + recuperação, sem a lista
        # de treinos — suficiente para comparar e metade do custo.
        p = preparar_dados_relatorio(d)
        p.pop("treinos", None)
        p.pop("baseline", None)
        return p

    dados_json = json.dumps(
        {
            "periodo_A_anterior": resumo_para_comparacao(d_anterior),
            "periodo_B_atual": resumo_para_comparacao(d_atual),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        default=str
    )

    resposta = chamar_gpt_sync(
        [
            {"role": "system", "content": ESTILO_SOPHOS + "\n\n" + PROMPT_COMPARACAO},
            {"role": "user", "content": f"DADOS:\n{dados_json}"},
        ],
        model=MODEL_FAST if dias < 14 else MODEL_MAIN,  # V20: mini dá conta de comparação curta
        max_tokens=2500,
        user_id=uid
    )

    context.user_data["ultima_resposta"] = resposta

    await enviar_texto_longo(
        context,
        update.effective_chat.id,
        f"⚖️ Comparação ({dias}d vs {dias}d anteriores):\n\n" + resposta,
        reply_markup=marcadores_feedback("comparacao")
    )

async def metricas_command(update, context):
    try:
        dias, inicio, fim = parse_periodo_args(context.args)
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
        "👋 Sophos online. Envie uma mensagem, áudio, arquivo ou use /relatorio, /analise e /comparar."
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
        "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
        "gpt-5.5": {"input": 5.0, "output": 30.00}
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
        "/prontidao — semáforo do dia 🟢🟡🔴 (custo zero)\n"
        "/prontidao ia — semáforo + comentário curto do Sophos\n"
        "/relatorio <dias> — relatório completo de performance\n"
        "/relatorio <xx/xx/xx xx/xx/xx> — relatório por período\n"
        "/analise <pedido livre> — análise focada\n"
        "   ex: /analise sono 30 dias\n"
        "   ex: /analise corrida e natação último mês\n"
        "/comparar <dias> — período atual vs anterior\n"
        "/metricas <dias ou período> — métricas brutas, sem análise\n"
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
    t = remover_acentos(texto.lower().strip())

    gatilhos_complexos = [
        "analise", "analisa", "avaliar", "avalie",
        "compare", "comparar",
        "estrategia", "decisao", "risco",
        "investimento", "contrato", "carreira",
        "relatorio", "suplemento",
        "codigo", "corrija", "erro", "bug",
        "projeto", "planejamento",
        "juridico", "financeiro",
    ]

    if any(g in t for g in gatilhos_complexos):
        return MODEL_MAIN

    if len(t) < 300:
        return MODEL_FAST

    return MODEL_MAIN

def deve_buscar_memoria(texto: str) -> bool:
    t = remover_acentos(texto.lower().strip())

    if len(t) < 80:
        return False

    gatilhos = [
        "lembra", "lembrar", "com base",
        "historico", "antes", "ja falei",
        "minha rotina", "meu treino", "meus dados",
        "minha carteira", "meu filho", "sophos",
        "meu trabalho", "minha dieta"
    ]

    return any(g in t for g in gatilhos)

# V22.2: gatilhos FECHADOS de intenção de decisão — não tema. Palavras como
# "treino", "bike", "z2" disparariam em quase toda mensagem de um triatleta.
# O que importa é a pergunta pedir um veredito sobre treinar ou não.
# Ressalva conhecida: "vale a pena" pode dar falso positivo em pergunta de
# compra; custo é ~300 tokens de bloco irrelevante — remova se incomodar.
GATILHOS_DECISAO_TREINO = [
    "sigo o plano", "faco mesmo", "devo fazer", "vale a pena",
    "algum risco", "posso treinar", "to pronto", "estou pronto",
    "reduzo", "corto", "cancelo", "mantenho", "ajusto",
    "amanha tenho", "hoje tenho", "consigo fazer", "aguento",
    "devo treinar", "treino ou descanso",
]


def pergunta_de_decisao_treino(texto):
    t = remover_acentos((texto or "").lower())
    return any(g in t for g in GATILHOS_DECISAO_TREINO)


async def processar_texto(user_id, texto, update, context):
    inicializar_usuario(user_id)

    texto_original = texto.strip()

    await resumir_contexto_antigo(user_id)

    salvar_contexto(user_id, texto_original, papel="usuario")

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

    # V22.2: estado operacional só quando a pergunta pede DECISÃO de treino.
    # Prontidão tem prioridade (dados operacionais do dia); relatório é fallback.
    if pergunta_de_decisao_treino(texto_original):
        estado = recuperar_estado_atual(user_id, "prontidao")
        origem = "prontidão"

        if not estado:
            estado = recuperar_estado_atual(user_id, "ultimo_relatorio")
            origem = "último relatório"

        if estado and estado.get("dados"):
            aviso_data = ""
            if estado.get("data_local") != hoje_local().isoformat():
                aviso_data = (
                    f" (ATENÇÃO: calculado em {estado.get('data_local')}, "
                    "pode estar desatualizado — diga isso ao usuário se for relevante)"
                )

            base += (
                f"\n\nEstado atual ({origem}) para decisões de treino{aviso_data}:\n"
                + json.dumps(
                    estado.get("dados"),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str
                )[:2500]
            )

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

    # V19.1: contexto bidirecional com chave de desligamento. Guarda a
    # resposta do Sophos (truncada) para coerência; erros não entram.
    if CONTEXTO_BIDIRECIONAL and not r.startswith("⚠️"):
        try:
            salvar_contexto(user_id, r[:400], papel="sophos")
        except Exception as e:
            print("Erro ao salvar contexto do Sophos:", e)

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

def comprimir_imagem(temp_path, max_dim=1024, qualidade=80):
    """Reduz resolução e peso da imagem antes do base64.
    Corte de 50-70% nos tokens de visão mantendo legibilidade."""
    try:
        img = Image.open(temp_path)
        img = img.convert("RGB")
        img.thumbnail((max_dim, max_dim))
        novo_path = temp_path + "_min.jpg"
        img.save(novo_path, "JPEG", quality=qualidade, optimize=True)
        return novo_path
    except Exception as e:
        print("Erro ao comprimir imagem:", e)
        return temp_path

def analisar_imagem_com_ia(temp_path, instrucao="Analise esta imagem."):
    modelo = MODEL_MAIN if "modo avançado" in (instrucao or "").lower() else MODEL_FAST

    path_min = comprimir_imagem(temp_path)

    with open(path_min, "rb") as img:
        base64_image = base64.b64encode(img.read()).decode("utf-8")

    if path_min != temp_path:
        try:
            os.remove(path_min)
        except Exception:
            pass

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
    app.add_handler(CommandHandler("prontidao", prontidao_command))
    app.add_handler(CommandHandler("analise", analise_command))
    app.add_handler(CommandHandler("comparar", comparar_command))
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
