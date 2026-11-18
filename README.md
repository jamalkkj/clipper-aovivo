# Clipper AO VIVO

Complemento do **Clipper do GTA 6** (https://github.com/davixavier-coder/skill-clips) que corta lives **enquanto
elas estão acontecendo**. Os cortes ficam prontos poucos minutos depois do momento, então dá para postar antes de
todo mundo.

## Como funciona

1. **Grava a live** no seu computador em pedacinhos de 30 segundos, sem converter nada, então pesa pouco.
2. **A cada 5 minutos gravados, escuta aquele pedaço** e marca onde o streamer gritou e onde o chat acelerou
   (chat ao vivo do YouTube e da Twitch).
3. **A IA lê as novidades e escolhe os momentos.** No modo automático, ele escolhe sozinho.
4. **Monta o corte direto da gravação.** Vídeo vertical 1080×1920, com a câmera do streamer em cima, o jogo embaixo,
   título de gancho, legenda palavra por palavra e um `.txt` com a legenda do post e o crédito.

## Instalação

Você precisa do **Claude Code**. Abra o terminal e cole **um** comando:

- **Mac/Linux:** `curl -fsSL https://raw.githubusercontent.com/jamalkkj/clipper-aovivo/main/instalar.sh | bash`
- **Windows (PowerShell):** `irm https://raw.githubusercontent.com/jamalkkj/clipper-aovivo/main/instalar.ps1 | iex`

No Mac/Linux, se o **Clipper do GTA 6** ainda não estiver instalado, o comando instala ele antes. Ele é a base.
No Windows, instale o Clipper do GTA 6 primeiro
(`irm https://raw.githubusercontent.com/davixavier-coder/skill-clips/main/instalar.ps1 | iex`).
Espere aparecer **TUDO PRONTO**. O mesmo comando serve para **atualizar**.

Ou cole no Claude Code:
> instala essa skill: https://github.com/jamalkkj/clipper-aovivo

## Usando

- "clipa ao vivo essa live: LINK"
- "acompanha essa live no modo automático: LINK"
- "como tá a live?" (mostra o andamento com barra de progresso)
- "para de clipar a live"

A live precisa estar **no ar**. Para live que já acabou, use o clipper normal.

## Precisa ter

- O Clipper do GTA 6 instalado (ele é a base)
- O computador ligado durante a live inteira
- Espaço em disco: uns **2 a 5 GB por hora de live**. Depois de terminar, o comando `limpar` apaga a gravação bruta
  e mantém os cortes.
- Um computador razoável. Ele precisa escutar 5 minutos de live em menos de 5 minutos. Em PC antigo (4 núcleos ou
  menos), feche outros programas e não rode o clipper normal ao mesmo tempo. Mac M1 ou mais novo, ou PC com 8 núcleos
  ou mais, acompanha com folga.

## Respeite os streamers

Corte só quem libera cortes e mantenha o crédito que vem no `.txt` de cada corte.
