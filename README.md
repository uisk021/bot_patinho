# Patinho Bot — Rádio Habbler

Bot Discord com portal web, economia, jogos, tickets, verificação, moderação e rádio/música.

## Hospedagem — configuração

1. Use a pasta deste projeto como raiz da hospedagem.
2. O `Dockerfile` incluído fixa Python 3.11 e instala o FFmpeg, evitando erros do instalador automático.
3. Em Railway, mantenha o **Build Command** vazio e o **Start Command** vazio: o Dockerfile executa `python bot.py`.
4. Em **Variables/Environment**, configure as variáveis secretas:
   - `DISCORD_TOKEN`
   - `MONGO_URI`

Não coloque essas credenciais no GitHub, `config.json` ou no código.

> Se os arquivos estiverem dentro de uma subpasta do GitHub, defina a **Root Directory** da hospedagem com o nome exato dessa subpasta.

## Discord Developer Portal

Na área **Bot > Privileged Gateway Intents**, habilite:

- Message Content Intent
- Server Members Intent

Sem esses intents, comandos por texto e recursos que usam membros podem não funcionar.

## O que foi corrigido nesta versão

- Removida a função de retry/backoff que não fazia parte do bot original.
- O bot inicia diretamente com `bot.run(TOKEN)`.
- Todos os 10 cogs do projeto são carregados e foram validados.
- Adicionadas ao bot as referências usadas pelos cogs: autorização de staff e estado do UNO.
- O portal web abre no mesmo processo do bot e responde à porta definida pelo Render.
- Leitura e gravação de `config.json` estão mais seguras.
- Os logs de falha ao iniciar mostram a causa de forma direta no Render.

## Observações

- Um HTTP 429 do Discord é uma limitação temporária do lado da API/rede; não é causado pelos arquivos HTML, CSS ou cogs.
- Para rádio e música, o bot precisa das permissões Discord de conectar e falar no canal de voz.
- O `config.json` desta entrega foi limpo por segurança. Reconfigure staff, cargo de verificado e demais preferências depois do primeiro início.
