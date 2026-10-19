"""Patinho Bot — bot Discord e painel web da Rádio Habbler.

Credenciais devem ser configuradas pela hospedagem, nunca neste arquivo:
- DISCORD_TOKEN
- MONGO_URI
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import certifi
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from pymongo import MongoClient

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

load_dotenv(BASE_DIR / ".env")
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
MONGO_URI = os.getenv("MONGO_URI", "").strip()
PORT = int(os.getenv("PORT", "10000"))

CANAL_NOTICIAS_ID = 1554620684208963645

COGS = (
    "cogs.geral",
    "cogs.musica",
    "cogs.moderacao",
    "cogs.jogos",
    "cogs.economia",
    "cogs.verificacao",
    "cogs.tickets",
    "cogs.interacoes",
    "cogs.site",
    "cogs.decoracao",
)

CONFIG_LOCK = threading.RLock()


def config_padrao() -> dict[str, Any]:
    """Retorna a estrutura mínima que todos os módulos esperam."""
    return {
        "staff": {},
        "palavras_proibidas": [],
        "links_proibidos": [],
        "log_channel": None,
        "warns": {},
        "radio_favorites": {},
        "ultima_noticia_url": None,
        "cargo_verificado": None,
        "verificados": {},
        "tickets": {},
        "xp": {},
        "aniversarios": {},
        "economia": {},
        "daily_cooldown": {},
        "fazenda": {},
    }


def carregar_config() -> dict[str, Any]:
    config = config_padrao()
    if not CONFIG_FILE.exists():
        return config

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        if isinstance(dados, dict):
            config.update(dados)
        else:
            print("⚠️ config.json não é um objeto JSON; usando valores padrão.", flush=True)
    except (OSError, json.JSONDecodeError) as erro:
        print(f"⚠️ Não foi possível ler config.json: {erro}", flush=True)

    # Evita que uma edição manual incompleta quebre os cogs em tempo de execução.
    padrao = config_padrao()
    for chave, valor in padrao.items():
        if chave not in config or not isinstance(config[chave], type(valor)):
            config[chave] = valor
    return config


config = carregar_config()


def salvar_config() -> None:
    """Salva com troca atômica para não corromper o JSON numa interrupção."""
    try:
        with CONFIG_LOCK:
            fd, caminho_temporario = tempfile.mkstemp(
                prefix="config-", suffix=".json", dir=BASE_DIR, text=True
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
                    json.dump(config, arquivo, indent=2, ensure_ascii=False)
                    arquivo.write("\n")
                os.replace(caminho_temporario, CONFIG_FILE)
            except Exception:
                try:
                    os.unlink(caminho_temporario)
                except OSError:
                    pass
                raise
    except Exception as erro:
        print(f"⚠️ Erro ao salvar config.json: {type(erro).__name__}: {erro}", flush=True)


# ---------------------------------------------------------------------------
# MongoDB — o bot continua com os dados locais se o Atlas estiver indisponível.
# ---------------------------------------------------------------------------
mongo_client: MongoClient | None = None
db = None
col_usuarios = None
col_status = None
col_logs = None
col_site_cmds = None

if not MONGO_URI:
    print("⚠️ MONGO_URI não configurada; usando apenas config.json.", flush=True)
else:
    try:
        mongo_client = MongoClient(
            MONGO_URI,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=5_000,
            connectTimeoutMS=5_000,
            socketTimeoutMS=5_000,
        )
        mongo_client.admin.command("ping")
        db = mongo_client["radio_habbler"]
        col_usuarios = db["usuarios"]
        col_status = db["bot_status"]
        col_logs = db["comandos_log"]
        col_site_cmds = db["mensagens_site"]
        print("🍃 Conectado com sucesso ao MongoDB Atlas!", flush=True)
    except Exception as erro:
        print(f"⚠️ MongoDB indisponível: {type(erro).__name__}: {erro}", flush=True)
        if mongo_client is not None:
            mongo_client.close()
        mongo_client = None
        db = None


def _usuario_id(user_id: int | str) -> str:
    return str(user_id)


def get_saldo(user_id: int | str) -> int:
    uid = _usuario_id(user_id)
    if col_usuarios is not None:
        try:
            documento = col_usuarios.find_one({"user_id": uid}, {"saldo": 1})
            if documento and isinstance(documento.get("saldo"), (int, float)):
                return int(documento["saldo"])
        except Exception as erro:
            print(f"⚠️ Erro ao obter saldo no MongoDB: {erro}", flush=True)
    return int(config.get("economia", {}).get(uid, 0))


def add_saldo(user_id: int | str, valor: int, user_name: str | None = None) -> None:
    uid = _usuario_id(user_id)
    valor = int(valor)
    with CONFIG_LOCK:
        economia = config.setdefault("economia", {})
        economia[uid] = max(0, int(economia.get(uid, 0)) + valor)
    salvar_config()

    if col_usuarios is not None:
        try:
            dados_set = {"ultima_atualizacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
            if user_name:
                dados_set["user_name"] = user_name
            col_usuarios.update_one(
                {"user_id": uid},
                {"$inc": {"saldo": valor}, "$set": dados_set},
                upsert=True,
            )
        except Exception as erro:
            print(f"⚠️ Erro ao atualizar saldo no MongoDB: {erro}", flush=True)


async def add_xp_jogo(user_id: int | str, amount: int, user_name: str | None = None) -> None:
    uid = _usuario_id(user_id)
    amount = int(amount)
    with CONFIG_LOCK:
        xp = config.setdefault("xp", {})
        xp[uid] = max(0, int(xp.get(uid, 0)) + amount)
    salvar_config()

    if col_usuarios is not None:
        try:
            dados_set = {"ultima_atualizacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
            if user_name:
                dados_set["user_name"] = user_name
            col_usuarios.update_one(
                {"user_id": uid},
                {"$inc": {"xp": amount}, "$set": dados_set},
                upsert=True,
            )
        except Exception as erro:
            print(f"⚠️ Erro ao atualizar XP no MongoDB: {erro}", flush=True)


def migrar_dados_iniciais() -> None:
    """Move dados antigos do JSON para o Atlas sem sobrescrever dados atuais."""
    if col_usuarios is None:
        return
    try:
        xp_data = config.get("xp", {})
        economia = config.get("economia", {})
        verificados = config.get("verificados", {})
        for uid in set(xp_data) | set(economia):
            col_usuarios.update_one(
                {"user_id": uid},
                {
                    "$setOnInsert": {
                        "xp": int(xp_data.get(uid, 0)),
                        "saldo": int(economia.get(uid, 0)),
                        "user_name": verificados.get(uid, f"Habbler #{uid[-4:]}"),
                        "ultima_atualizacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                    }
                },
                upsert=True,
            )
    except Exception as erro:
        print(f"⚠️ Erro na migração inicial: {erro}", flush=True)


# ---------------------------------------------------------------------------
# Portal web
# ---------------------------------------------------------------------------
app_flask = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))


@app_flask.get("/")
def index():
    return render_template("index.html")


@app_flask.get("/api/status")
def api_status():
    if col_status is None:
        return jsonify({"online": int(bot.is_ready()), "servidores": len(bot.guilds) if bot.is_ready() else 0})
    try:
        documento = col_status.find_one({"_id": "status"}, {"_id": 0})
        return jsonify(documento or {"online": 0})
    except Exception as erro:
        return jsonify({"online": 0, "erro": "Banco indisponível"}), 503


@app_flask.get("/api/ranking/xp")
def api_ranking_xp():
    if col_usuarios is not None:
        try:
            dados = list(
                col_usuarios.find({}, {"_id": 0, "user_name": 1, "xp": 1, "saldo": 1})
                .sort("xp", -1)
                .limit(20)
            )
            return jsonify(dados)
        except Exception:
            pass
    ranking = sorted(config.get("xp", {}).items(), key=lambda item: item[1], reverse=True)[:20]
    return jsonify([
        {"user_name": config.get("verificados", {}).get(uid, f"Usuário {uid[-4:]}"), "xp": xp}
        for uid, xp in ranking
    ])


@app_flask.get("/api/ranking/saldo")
def api_ranking_saldo():
    if col_usuarios is not None:
        try:
            dados = list(
                col_usuarios.find({}, {"_id": 0, "user_name": 1, "xp": 1, "saldo": 1})
                .sort("saldo", -1)
                .limit(20)
            )
            return jsonify(dados)
        except Exception:
            pass
    ranking = sorted(config.get("economia", {}).items(), key=lambda item: item[1], reverse=True)[:20]
    return jsonify([
        {"user_name": config.get("verificados", {}).get(uid, f"Usuário {uid[-4:]}"), "saldo": saldo}
        for uid, saldo in ranking
    ])


@app_flask.get("/api/logs")
def api_logs():
    if col_logs is None:
        return jsonify([])
    try:
        dados = list(col_logs.find({}, {"_id": 0}).sort("timestamp", -1).limit(15))
        for item in dados:
            if isinstance(item.get("timestamp"), datetime):
                item["timestamp"] = item["timestamp"].isoformat()
        return jsonify(dados)
    except Exception:
        return jsonify([])


@app_flask.post("/api/comando")
def api_comando():
    """Registra um pedido do site para o bot processar no loop seguinte."""
    dados = request.get_json(silent=True) or {}
    tipo = str(dados.get("tipo", "anuncio"))[:30]
    conteudo = str(dados.get("conteudo", "")).strip()[:1_500]
    if not conteudo:
        return jsonify({"sucesso": False, "erro": "Mensagem vazia!"}), 400
    if col_site_cmds is None:
        return jsonify({"sucesso": False, "erro": "Banco offline"}), 503
    try:
        col_site_cmds.insert_one(
            {
                "tipo": tipo,
                "conteudo": conteudo,
                "lido": False,
                "data": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            }
        )
        return jsonify({"sucesso": True, "mensagem": "Comando enviado para o Patinho! 🐥"})
    except Exception:
        return jsonify({"sucesso": False, "erro": "Não foi possível salvar o comando."}), 503


def rodar_servidor_web() -> None:
    print(f"🌐 Portal web ouvindo na porta {PORT}.", flush=True)
    app_flask.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


# ---------------------------------------------------------------------------
# Bot Discord
# ---------------------------------------------------------------------------
class PatinhoBot(commands.Bot):
    async def setup_hook(self) -> None:
        print("📦 Carregando cogs…", flush=True)
        for nome_cog in COGS:
            try:
                await self.load_extension(nome_cog)
                print(f"  ✅ {nome_cog}", flush=True)
            except Exception as erro:
                # Um cog com defeito não impede os demais de continuar carregando.
                print(f"  ❌ {nome_cog}: {type(erro).__name__}: {erro}", flush=True)

    def verificar_autorizacao(self, ctx: commands.Context, senha: str | None = None) -> bool:
        """Autoriza o dono ou um staff cadastrado com a senha dele no config.json."""
        if ctx.guild is None:
            return False
        if ctx.author.id == ctx.guild.owner_id:
            return True
        esperada = self.config.get("staff", {}).get(str(ctx.author.id))
        if not isinstance(esperada, str) or not esperada:
            return False
        return isinstance(senha, str) and hmac.compare_digest(senha, esperada)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = PatinhoBot(
    command_prefix=("hbl ", "Hbl ", "HBL ", "hbl", "Hbl", "HBL"),
    intents=intents,
    case_insensitive=True,
    help_command=None,
)
bot.config = config
bot.salvar_config = salvar_config
bot.get_saldo = get_saldo
bot.add_saldo = add_saldo
bot.add_xp_jogo = add_xp_jogo
bot.db = db
bot.music_queues = {}
bot.player_tasks = {}
bot.uno_jogos = {}


@tasks.loop(seconds=15)
async def atualizar_status_no_banco() -> None:
    if not bot.is_ready() or col_status is None:
        return
    try:
        servidores = len(bot.guilds)
        usuarios = sum(guild.member_count or 0 for guild in bot.guilds)
        col_status.update_one(
            {"_id": "status"},
            {
                "$set": {
                    "online": 1,
                    "servidores": servidores,
                    "usuarios": usuarios,
                    "ultimo_ping": round(bot.latency * 1_000),
                    "last_seen": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                },
                "$setOnInsert": {"comandos_total": 0, "comandos_hoje": 0},
            },
            upsert=True,
        )
    except Exception as erro:
        print(f"⚠️ Erro ao salvar status no MongoDB: {erro}", flush=True)


@tasks.loop(seconds=5)
async def checar_comandos_do_site() -> None:
    if not bot.is_ready() or col_site_cmds is None:
        return
    try:
        mensagens = list(col_site_cmds.find({"lido": False}).limit(20))
        for mensagem in mensagens:
            enviado = False
            if mensagem.get("tipo") == "anuncio":
                canal = bot.get_channel(CANAL_NOTICIAS_ID)
                if isinstance(canal, discord.abc.Messageable):
                    embed = discord.Embed(
                        title="📢 Comunicado da Rádio Habbler",
                        description=str(mensagem.get("conteudo", "")),
                        color=discord.Color.gold(),
                        timestamp=discord.utils.utcnow(),
                    )
                    embed.set_footer(text="Enviado via Painel Web")
                    await canal.send(embed=embed)
                    enviado = True
            if enviado or mensagem.get("tipo") != "anuncio":
                col_site_cmds.update_one({"_id": mensagem["_id"]}, {"$set": {"lido": True}})
    except Exception as erro:
        print(f"⚠️ Erro ao processar comandos do site: {erro}", flush=True)


@bot.event
async def on_ready() -> None:
    print(f"✅ Patinho online como {bot.user} ({bot.user.id if bot.user else '?'})", flush=True)
    migrar_dados_iniciais()
    if not atualizar_status_no_banco.is_running():
        atualizar_status_no_banco.start()
    if not checar_comandos_do_site.is_running():
        checar_comandos_do_site.start()


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    if message.guild is None:
        await bot.process_commands(message)
        return

    uid = str(message.author.id)
    agora = asyncio.get_running_loop().time()
    xp_cooldown = getattr(bot, "xp_cooldown", {})
    bot.xp_cooldown = xp_cooldown
    if agora - xp_cooldown.get(uid, 0) > 60:
        xp_cooldown[uid] = agora
        nick = config.get("verificados", {}).get(uid, message.author.display_name)
        await add_xp_jogo(message.author.id, 15, user_name=nick)

    conteudo = message.content.strip().lower()
    if conteudo == "hbl":
        await message.channel.send(f"👋 {message.author.mention} Prefixo: `hbl ` | Ajuda: `hbl ajuda`")
        return

    # Staff e proprietário não sofrem os filtros automáticos.
    if message.author.id == message.guild.owner_id or uid in config.get("staff", {}):
        await bot.process_commands(message)
        return

    if any(palavra.lower() in conteudo for palavra in config.get("palavras_proibidas", []) if palavra):
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        return

    tem_link = any(link in conteudo for link in ("http://", "https://", "www.", "discord.gg"))
    filtros_link = config.get("links_proibidos", [])
    link_bloqueado = tem_link and (not filtros_link or any(item.lower() in conteudo for item in filtros_link if item))
    if link_bloqueado or len(message.mentions) >= 5 or "@everyone" in message.content:
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        return

    await bot.process_commands(message)


@bot.event
async def on_command(ctx: commands.Context) -> None:
    if col_logs is None:
        return
    try:
        col_logs.insert_one(
            {
                "comando": ctx.command.qualified_name if ctx.command else "desconhecido",
                "usuario": str(ctx.author),
                "servidor": str(ctx.guild) if ctx.guild else "DM",
                "data": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "timestamp": datetime.now(timezone.utc),
            }
        )
        if col_status is not None:
            col_status.update_one(
                {"_id": "status"},
                {"$inc": {"comandos_total": 1, "comandos_hoje": 1}},
                upsert=True,
            )
    except Exception as erro:
        print(f"⚠️ Erro ao registrar comando: {erro}", flush=True)


@bot.event
async def on_command_error(ctx: commands.Context, erro: commands.CommandError) -> None:
    if isinstance(erro, commands.CommandNotFound):
        partes = ctx.message.content.split(maxsplit=1)
        digitado = partes[1].split()[0].lower() if len(partes) > 1 else ""
        await ctx.send(f"❓ `hbl {digitado}` não existe. Use `hbl ajuda`.")
    elif isinstance(erro, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Uso: `hbl {ctx.command.qualified_name} {erro.param.name}`")
    elif isinstance(erro, commands.MemberNotFound):
        await ctx.send("⚠️ Não encontrei esse membro no servidor.")
    elif isinstance(erro, commands.BadArgument):
        await ctx.send("⚠️ Um dos argumentos é inválido. Confira `hbl ajuda`.")
    elif isinstance(erro, commands.NoPrivateMessage):
        await ctx.send("⚠️ Este comando só pode ser usado no servidor.")
    else:
        print(f"⚠️ Erro no comando: {type(erro).__name__}: {erro}", flush=True)


@bot.event
async def on_disconnect() -> None:
    if col_status is not None:
        try:
            col_status.update_one({"_id": "status"}, {"$set": {"online": 0}})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Inicialização simples: sem função de retry/backoff.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    threading.Thread(target=rodar_servidor_web, name="portal-web", daemon=True).start()

    if not TOKEN:
        print("❌ DISCORD_TOKEN não encontrado. Configure a variável no Render.", flush=True)
        raise SystemExit(1)

    try:
        print("🔐 Conectando ao Discord…", flush=True)
        bot.run(TOKEN, log_handler=None)
    except discord.LoginFailure:
        print("❌ DISCORD_TOKEN rejeitado pelo Discord. Revise a variável no Render.", flush=True)
        raise
    except discord.HTTPException as erro:
        print(f"❌ Discord recusou a conexão: HTTP {erro.status}. {erro}", flush=True)
        raise
    except Exception as erro:
        print(f"❌ Falha inesperada ao iniciar: {type(erro).__name__}: {erro}", flush=True)
        raise
