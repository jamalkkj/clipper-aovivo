---
name: clipper-aovivo
description: Clipper AO VIVO — corta uma live ENQUANTO ela está acontecendo (YouTube, Twitch ou Kick). Grava a live, escuta a cada 5 minutos, marca gritos e chat acelerado e monta cortes verticais (câmera em cima, jogo embaixo, título, legenda palavra por palavra) minutos depois do momento acontecer. Use quando a pessoa disser "clipa ao vivo", "acompanha essa live", "corta essa live que tá rolando agora", "instala o clipper ao vivo", ou mandar o link de uma live que AINDA ESTÁ NO AR. Para live que já acabou, use a skill clipper-gta6.
---

# Clipper AO VIVO

Esta skill é um complemento do **Clipper do GTA 6** (skill `clipper-gta6`): usa o ambiente, o detector de câmera e
a montagem dele. Ela só serve pra live que **ainda está no ar**. Live que já acabou → use a `clipper-gta6`.

Fale com a pessoa em português simples, uma frase por vez, sem jargão. Ela não é programadora.
Toda vez que der notícia do andamento, mostre a **barra de progresso** que o `status` imprime.

## Regras que evitam travar

1. **Sempre o atalho.** Depois de instalado, todo comando é:
   - Mac / Linux: `~/clipper-gta6/aovivo COMANDO`
   - Windows PowerShell: `& "$HOME\clipper-gta6\aovivo.cmd" COMANDO`
   Se o atalho não existir, faça o passo 0.
2. O trabalho pesado roda sozinho em segundo plano (grava, escuta, monta). Os comandos só acompanham.
3. **"AINDA ESPERANDO" não é erro**: rode o mesmo comando de novo.
4. Não tente baixar vídeo, ler site ou escrever script por conta própria.
5. Mensagem com "NÃO DÁ PRA BAIXAR" ou "NÃO ESTÁ NO AR": repita pra pessoa com essas palavras.

## 0. Instalar / atualizar ("instala o clipper ao vivo")

Rode **um comando só** (se faltar o clipper-gta6 no Mac/Linux, ele instala antes):

- Mac/Linux: `curl -fsSL https://raw.githubusercontent.com/jamalkkj/clipper-aovivo/main/instalar.sh | bash`
- Windows (PowerShell): `irm https://raw.githubusercontent.com/jamalkkj/clipper-aovivo/main/instalar.ps1 | iex`
  (no Windows, se ele disser que falta o Clipper do GTA 6, instale ele primeiro pelo passo 0 da skill clipper-gta6)

Quando aparecer TUDO PRONTO, diga: "Pronto! Me manda o link de uma live que está no ar agora."

## 1. Começar

Pergunte (se a pessoa não disse) **qual modo**:
- **A IA escolhe** (melhor): você lê as novidades a cada 5 min e escolhe os momentos. Precisa que a conversa fique aberta.
- **Automático** (`--auto`): ele escolhe sozinho pelos gritos/chat; títulos mais simples. Bom se a pessoa vai sair
  ou se a IA é a de graça (Ollama).

`iniciar LINK` (ou `iniciar LINK --auto`). Ele mostra o **nome** da live: use esse nome nos outros comandos.
Live não for em português nem inglês: `--idioma es` (etc).

## 2. Acompanhar (modo "a IA escolhe")

Repita este ciclo enquanto a live durar:

1. `esperar NOME` — fica esperando até ter um pedaço novo escutado (até ~9 min) e mostra as **NOVIDADES**.
   Se o seu ambiente deixa rodar comando em segundo plano, rode o `esperar` em segundo plano e siga quando ele terminar.
2. Leia as novidades. Cada linha é `[hh:mm:ss] fala`, com o tempo contado **desde que a gravação começou**.
   - `[ALTO +12dB]`: o streamer ficou muito mais alto (grito, surto, susto).
   - `[CHAT 3.1x]`: o chat andou 3 vezes mais rápido que o normal.
   Marca sozinha não é momento: confirme pela fala.
3. Achou momento bom? Escreva no arquivo `momentos/rodada_NN.json` que o `esperar` indicou e rode `cortar NOME`.
   Não achou? Só volte pro passo 1. **Nem todo pedaço tem momento: não invente.**
4. Quando aparecer `CORTE PRONTO`, avise a pessoa na hora (com o caminho do vídeo): é o momento de postar.

**O que vale um corte:** primeira reação a algo do jogo, descoberta absurda, surto/grito/raiva/susto, falha
engraçada, bug, morte ridícula, opinião forte ou polêmica, piada que fecha sozinha.
**Jogue fora:** o que precisa de contexto, começa com enrolação, leitura de doação, propaganda, pausa, fala picada.
**Nota** 0–100 (abaixo de 60 nem escreva). **Duração** 20 a 60 s, começando 1–2 s antes da frase que prende.
Um momento pode atravessar dois pedaços: tudo bem, use os tempos certos.

Formato (igual ao clipper-gta6):

```json
[
  {
    "inicio": "01:12:03",
    "fim": "01:12:41",
    "nota": 88,
    "tipo": "primeira reação",
    "titulo": "ELE NÃO ACREDITOU NO TAMANHO DO MAPA",
    "porque": "grita ao ver o mapa; fecha sozinho",
    "post": "O mapa do GTA 6 deixou ele sem palavras 😳 #gta6 #gtavi #gta #cortes #aovivo"
  }
]
```

- `titulo`: até ~45 letras, MAIÚSCULAS, na língua da live, sem spoiler do final.
- `post`: 1–2 frases + 4 a 6 hashtags **do jogo da live** (GTA 6 → `#gta6`; outro jogo → as hashtags dele).

## 3. Modo automático

Depois do `iniciar ... --auto`, não precisa fazer nada: rode `status NOME` de vez em quando pra mostrar o andamento
e os cortes que ficaram prontos.

## 4. Terminar

- A live acabou: ele percebe sozinho, escuta o que faltou, monta a fila e encerra.
- A pessoa quer parar antes: `parar NOME` (termina o que já gravou) ou `parar NOME --agora` (para tudo na hora).
- Depois de encerrado, ofereça liberar espaço: `limpar NOME` apaga a gravação bruta (uns 2 a 5 GB por hora).
  Os cortes prontos não são apagados.

Saída: `~/clipper-gta6/cortes/NOME/corte_NN.mp4` + `corte_NN.txt` (legenda do post + crédito da live).

## Problemas comuns

- `status NOME` mostra tudo: tempo gravado, quanto já foi escutado (e o atraso), a fila de cortes e o fim do log
  se algo parou.
- **Atraso crescendo** (o escutado fica cada vez mais para trás): o computador está lento pra acompanhar. Feche
  outros programas e não rode o clipper normal ao mesmo tempo. Em PC fraco, use `--modelo tiny`.
- Gravação caiu: ele reconecta sozinho. Se a live acabou, encerra sozinho.
- "O trabalhador parou sozinho": mostre o fim do log do `status` e rode `iniciar LINK` de novo (continua de onde parou).
- Kick às vezes bloqueia: prefira o link do YouTube ou da Twitch do mesmo streamer.

## Respeito aos streamers

Corte só de quem permite cortes. O `.txt` de cada corte traz o crédito com o link da live: mantenha na postagem.
