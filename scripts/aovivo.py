#!/usr/bin/env python3
"""Clipper AO VIVO: corta uma live ENQUANTO ela acontece.

Usa as peças do Clipper do GTA 6 (skill clipper-gta6), que precisa estar instalado antes.

Como funciona (tudo em segundo plano, num trabalhador que fica rodando):
  1. grava a live no disco em pedacinhos de 30 s (sem converter: quase não pesa)
  2. a cada 5 min gravados, escuta esse pedaço, marca gritos [ALTO] e chat acelerado [CHAT]
  3. a IA lê as novidades e escreve os momentos (ou, no modo --auto, ele escolhe sozinho)
  4. monta os cortes direto do que já foi gravado (não baixa nada de novo)

Comandos (depois do instalar, use o atalho ~/clipper-gta6/aovivo):
  aovivo instalar                    cria o atalho (precisa do clipper-gta6 instalado)
  aovivo iniciar LINK [--auto]       começa a gravar e escutar a live que está no ar
  aovivo esperar LIVE                espera ter novidade (até ~9 min) e mostra o que a IA deve ler
  aovivo novidades LIVE              mostra na hora o que ainda não foi lido
  aovivo cortar LIVE                 manda pra fila os momentos que a IA escreveu em momentos/
  aovivo status [LIVE]               mostra em que ponto está (com barra de progresso)
  aovivo parar LIVE                  para de gravar, termina o que falta e encerra
  aovivo limpar LIVE                 apaga a gravação bruta (depois de parar) pra liberar disco
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------- achar o clipper-gta6
CASA = Path(os.environ.get("CLIPPER_GTA6_HOME", Path.home() / "clipper-gta6"))
VENV = CASA / "ambiente"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
AQUI = Path(__file__).resolve()


def _scripts_originais():
    for p in (os.environ.get("CLIPPER_GTA6_SCRIPTS"),
              AQUI.parent.parent.parent / "clipper-gta6" / "scripts",
              Path.home() / ".claude" / "skills" / "clipper-gta6" / "scripts"):
        if p and (Path(p) / "cortar.py").exists():
            return Path(p)
    return None


ORIG = _scripts_originais()
if ORIG is None:
    sys.exit("\n  ✗ O CLIPPER DO GTA 6 NÃO ESTÁ INSTALADO.\n    Instale ele antes (é a base do modo ao vivo):\n"
             "    Mac/Linux: curl -fsSL https://raw.githubusercontent.com/davixavier-coder/skill-clips/main/instalar.sh | bash\n"
             "    Windows:   irm https://raw.githubusercontent.com/davixavier-coder/skill-clips/main/instalar.ps1 | iex")
sys.path.insert(0, str(ORIG))

from comum import (CORTES, TRABALHO, gravar_json, hms, ler_json, motivo_trancada, pasta_da_live,  # noqa: E402
                   segundos, slug, ytdlp)

PEDACO = int(os.environ.get("AOVIVO_PEDACO", "300"))   # escuta 5 min por vez
SEG = 30                                              # a gravação sai em arquivos de 30 s
ESPERA = int(os.environ.get("AOVIVO_ESPERA", "540"))  # 'esperar' devolve antes dos 10 min do Claude Code
FORMATO = "b[height<=1080][protocol*=m3u8]/b[height<=1080]/bv*[height<=1080]+ba/b"


# ---------------------------------------------------------------- ambiente
def no_ambiente():
    if VENV_PY.exists() and Path(sys.prefix).resolve() != VENV.resolve():
        os.execv(str(VENV_PY), [str(VENV_PY), str(AQUI), *sys.argv[1:]])


def preparar_ffmpeg():
    """Precisa de um ffmpeg com o filtro de legenda (ass). O de alguns Linux não tem: aí usa o que vem no clipper."""
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
        ok = " ass " in r.stdout
    except FileNotFoundError:
        ok = False
    if not ok:
        try:
            import static_ffmpeg
            static_ffmpeg.add_paths(weak=False)
        except Exception:
            pass


def utf8():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass


def vivo(pid):
    if not pid:
        return False
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def matar(pid):
    if not vivo(pid):
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            os.kill(pid, 15)
    except Exception:
        pass


def destacado(argv, log):
    kw = {"start_new_session": True}
    if os.name == "nt":
        kw = {"creationflags": 0x00000008 | 0x00000200 | 0x08000000}
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", OPENCV_LOG_LEVEL="ERROR")
    return subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, **kw)


def barra(frac, largura=20):
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * largura))
    return "[" + "█" * n + "░" * (largura - n) + f"] {100 * frac:3.0f}%"


# ---------------------------------------------------------------- estado da live
def estado(pasta):
    return ler_json(pasta / "aovivo.json", {})


def salvar(pasta, st):
    gravar_json(pasta / "aovivo.json", st)


def mexer(pasta, **mud):
    st = estado(pasta)
    st.update(mud)
    salvar(pasta, st)
    return st


def ler_meta(url):
    r = subprocess.run(ytdlp() + ["-J", "--no-playlist", "--no-warnings", url], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr
    return json.loads(r.stdout), ""


def situacao(url):
    meta, erro = ler_meta(url)
    if meta is None:
        return "fora" if "not currently live" in erro.lower() or "offline" in erro.lower() else "erro"
    return meta.get("live_status") or ("is_live" if meta.get("is_live") else "fora")


# ---------------------------------------------------------------- gravação
def link_do_stream(url):
    r = subprocess.run(ytdlp() + ["-f", FORMATO, "-g", "--no-playlist", "--no-warnings", url],
                       capture_output=True, text=True)
    return [l for l in r.stdout.split() if l.startswith("http")][:2]


def gravar(pasta, st):
    """Começa uma 'sessão' de gravação (se o ffmpeg cair, abre outra; o relógio da live continua o mesmo)."""
    links = link_do_stream(st["url"])
    if not links:
        return None
    n = len(st.get("sessoes", [])) + 1
    gdir = pasta / "gravacao"
    gdir.mkdir(exist_ok=True)
    entrada = []
    for l in links:
        entrada += ["-i", l]
    mapa = ["-map", "0:v:0", "-map", ("1:a:0" if len(links) > 1 else "0:a:0?")]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *entrada, *mapa, "-c", "copy",
           "-f", "segment", "-segment_time", str(SEG), "-segment_format", "mpegts",
           "-segment_list", f"s{n:02d}.csv", "-segment_list_type", "csv", f"s{n:02d}_%05d.ts"]
    proc = subprocess.Popen(cmd, cwd=gdir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=open(gdir / f"s{n:02d}.log", "w"))
    st.setdefault("sessoes", []).append({"n": n, "inicio": time.time() - st["t0"], "pid": proc.pid})
    salvar(pasta, st)
    print(f"      gravando (sessão {n})…", flush=True)
    return proc


def indice(pasta, st):
    """Lista [arquivo, sessão, início, fim] de cada pedacinho já fechado, no relógio da live."""
    gdir = pasta / "gravacao"
    out = []
    for s in st.get("sessoes", []):
        csv = gdir / f"s{s['n']:02d}.csv"
        if not csv.exists():
            continue
        linhas = [l.split(",") for l in csv.read_text(errors="ignore").splitlines() if l.count(",") >= 2]
        if not linhas:
            continue
        base = float(linhas[0][1])
        for nome, a, b in (l[:3] for l in linhas):
            try:
                out.append([nome, s["n"], s["inicio"] + float(a) - base, s["inicio"] + float(b) - base])
            except ValueError:
                continue
    return out


def _pedacos(idx, a, b):
    """Arquivos que cobrem [a, b], da sessão que mais cobre esse intervalo."""
    sob = [x for x in idx if x[3] > a and x[2] < b]
    if not sob:
        return [], 0.0
    por = {}
    for x in sob:
        por[x[1]] = por.get(x[1], 0) + min(x[3], b) - max(x[2], a)
    sess = max(por, key=por.get)
    arqs = [x for x in sob if x[1] == sess]
    return [x[0] for x in arqs], arqs[0][2]


def extrair(pasta, idx, a, b, destino=None):
    """Sem destino: devolve o áudio 16 kHz (numpy). Com destino: grava o vídeo do trecho em mp4."""
    arqs, g0 = _pedacos(idx, a, b)
    if not arqs:
        return (None, a) if destino is None else None
    a = max(a, g0)  # a gravação começou depois de 'a': o trecho começa onde tem gravação
    ini = a - g0
    entrada = "concat:" + "|".join(arqs)
    if destino is None:
        import numpy as np
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", entrada, "-ss", f"{ini:.2f}", "-t", f"{b - a:.2f}",
                            "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                           cwd=pasta / "gravacao", capture_output=True)
        return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768, a
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", entrada, "-ss", f"{ini:.2f}", "-t", f"{b - a:.2f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-c:a", "aac", "-b:a", "192k",
                    str(Path(destino).resolve())], cwd=pasta / "gravacao", check=True)
    return destino


# ---------------------------------------------------------------- chat ao vivo
def chat_twitch(pasta, canal, t0, parar):
    arq = pasta / "chat_tempos.txt"
    while not parar.is_set():
        try:
            s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=30)
            s.sendall(f"NICK justinfan{int(time.time()) % 90000 + 10000}\r\nJOIN #{canal.lower()}\r\n".encode())
            buf = b""
            with open(arq, "a") as f:
                while not parar.is_set():
                    try:
                        dados = s.recv(4096)
                    except socket.timeout:
                        continue
                    if not dados:
                        break
                    buf += dados
                    *linhas, buf = buf.split(b"\r\n")
                    for l in linhas:
                        if l.startswith(b"PING"):
                            s.sendall(b"PONG" + l[4:] + b"\r\n")
                        elif b" PRIVMSG " in l:
                            f.write(f"{time.time() - t0:.1f}\n")
                    f.flush()
        except OSError:
            time.sleep(15)


def chat_youtube(pasta, url, t0, parar):
    """O yt-dlp acompanha o chat ao vivo do YouTube; aqui só lemos a hora de cada mensagem."""
    cdir = pasta / "chat_yt"
    cdir.mkdir(exist_ok=True)
    proc = subprocess.Popen(ytdlp() + ["--skip-download", "--write-subs", "--sub-langs", "live_chat",
                                       "--no-warnings", "-q", "-o", str(cdir / "chat"), url],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    lido, saida = {}, open(pasta / "chat_tempos.txt", "a")
    while not parar.is_set():
        time.sleep(5)
        for arq in cdir.glob("chat*live_chat*"):
            pos = lido.get(arq.name, 0)
            try:
                with open(arq, encoding="utf-8", errors="ignore") as f:
                    f.seek(pos)
                    novo = f.read()
                    lido[arq.name] = f.tell()
            except OSError:
                continue
            for us in re.findall(r'"timestampUsec":\s*"(\d+)"', novo):
                saida.write(f"{int(us) / 1e6 - t0:.1f}\n")
            saida.flush()
        if proc.poll() is not None:
            break
    if proc.poll() is None:
        proc.terminate()


def iniciar_chat(pasta, st, parar):
    url = st["url"]
    m = re.search(r"twitch\.tv/([A-Za-z0-9_]+)", url)
    if m and m.group(1).lower() not in ("videos", "directory"):
        alvo = (chat_twitch, (pasta, m.group(1), st["t0"], parar))
    elif "youtu" in url:
        alvo = (chat_youtube, (pasta, url, st["t0"], parar))
    else:
        print("      (chat ao vivo só é lido no YouTube e na Twitch: aqui vai só pelo volume e pela fala)")
        return
    threading.Thread(target=alvo[0], args=alvo[1], daemon=True).start()


def picos_chat(pasta, a, b):
    import numpy as np
    arq = pasta / "chat_tempos.txt"
    if not arq.exists():
        return []
    tempos = []
    for l in arq.read_text(errors="ignore").split():
        try:
            t = float(l)
        except ValueError:
            continue
        if a - 300 <= t < b:
            tempos.append(t - (a - 300))
    if len(tempos) < 30:
        return []
    caixas = np.bincount((np.array(tempos) // 10).astype(int), minlength=int((b - a + 300) // 10) + 1)
    normal = max(1.0, float(np.median(caixas[caixas > 0]))) if (caixas > 0).any() else 1.0
    out = []
    for i, c in enumerate(caixas):
        t = i * 10 + (a - 300)
        if a <= t < b and c >= 8 and c / normal >= 2.5:
            out.append([t, round(c / normal, 1)])
    return out


# ---------------------------------------------------------------- escutar um pedaço
_MODELOS = {}


def modelo(nome):
    from faster_whisper import WhisperModel
    if nome not in _MODELOS:
        _MODELOS[nome] = WhisperModel(nome, device="cpu", compute_type="int8")
    return _MODELOS[nome]


def volume_db(audio):
    import numpy as np
    sr = 16000
    seg = len(audio) // sr
    if seg == 0:
        return []
    rms = np.sqrt(np.mean((audio[: seg * sr] * 32768).reshape(seg, sr) ** 2, axis=1) + 1e-6)
    return [round(float(x), 2) for x in 20 * np.log10(rms / 32768 + 1e-9)]


def picos_volume(pasta, k):
    """Segundos deste pedaço em que o streamer ficou bem mais alto que o normal dos últimos minutos."""
    import numpy as np
    atual = ler_json(pasta / "escuta" / f"vol_{k:04d}.json", [])
    antes = ler_json(pasta / "escuta" / f"vol_{k - 1:04d}.json", [])[1:] if k > 0 else []
    if len(atual) < 2:
        return []
    desloc, atual = int(atual[0]), atual[1:]
    db = np.array(antes + atual)
    fala = db[db > np.percentile(db, 20)]
    base = float(np.median(fala)) if len(fala) else float(np.median(db))
    exc = np.array(atual) - base
    corte = max(8.0, float(np.percentile(exc, 98)))
    return [[k * PEDACO + desloc + int(i), round(float(exc[i]), 1)] for i in np.where(exc >= corte)[0]]


def escutar(pasta, st, k, idx):
    from ouvir import REACAO, _linha
    a = k * PEDACO
    gravado = idx[-1][3] if idx else 0
    b = min(a + PEDACO, gravado)
    audio, inicio = extrair(pasta, idx, a, b)
    edir = pasta / "escuta"
    edir.mkdir(exist_ok=True)
    if audio is None or len(audio) < 16000 * 5:
        gravar_json(edir / f"{k:04d}.json", {"idioma": None, "segmentos": []})
        return 0
    lingua = st.get("idioma") or st.get("idioma_detectado")
    segs, inf = modelo(st.get("modelo") or ("base" if (os.cpu_count() or 4) >= 6 else "tiny")).transcribe(
        audio, language=lingua, vad_filter=True, beam_size=1, condition_on_previous_text=False)
    out = [[round(s.start + inicio, 2), round(s.end + inicio, 2), s.text.strip()] for s in segs if s.text.strip()]
    if not lingua and out and (inf.language_probability or 0) > 0.8:
        mexer(pasta, idioma_detectado=inf.language)
    gravar_json(edir / f"{k:04d}.json", {"idioma": inf.language, "segmentos": out})
    gravar_json(edir / f"vol_{k:04d}.json", [round(inicio - a)] + volume_db(audio))
    # transcrição inteira (os títulos automáticos do clipper leem daqui)
    tr = ler_json(pasta / "transcricao.json", {"idioma": None, "segmentos": []})
    tr["segmentos"] = [s for s in tr["segmentos"] if s[0] < a] + out
    tr["idioma"] = lingua or inf.language
    gravar_json(pasta / "transcricao.json", tr)
    vol = picos_volume(pasta, k)
    chat = picos_chat(pasta, a, b)
    vd = dict((s, e) for s, e in vol)
    reac = sum(len(REACAO.findall(t)) for _, _, t in out)
    calor = round(sum(e for _, e in vol) + sum(r * 3 for _, r in chat) + 5 * reac)
    linhas = [_linha(s, e, t, vd, chat) for s, e, t in out]
    ndir = pasta / "novos"
    ndir.mkdir(exist_ok=True)
    (ndir / f"pedaco_{k:04d}.txt").write_text(
        f"## PEDAÇO {k + 1} — de {hms(a)} a {hms(b)} (calor {calor}: {len(vol)} s de grito, "
        f"{len(chat)} picos de chat, {reac} reações)\n" + ("\n".join(linhas) or "(ninguém falou nada)") + "\n",
        encoding="utf-8")
    gravar_json(ndir / f"pedaco_{k:04d}.json", {"calor": calor, "vol": vol, "chat": chat, "reac": reac})
    print(f"      escutei {hms(a)}–{hms(b)}: {len(out)} falas, calor {calor}", flush=True)
    return calor


def momento_auto(pasta, k):
    """Modo --auto: pega o trecho mais quente do pedaço, se tiver grito, chat acelerado ou reação de verdade."""
    import numpy as np
    from cortar import _titulo_auto
    d = ler_json(pasta / "novos" / f"pedaco_{k:04d}.json", {})
    if not d or (not d["vol"] and not d["chat"] and d["reac"] < 2):
        return None
    a = k * PEDACO
    calor = np.zeros(PEDACO + 60)
    for s, e in d["vol"]:
        calor[int(s - a)] += e
    for c, r in d["chat"]:
        calor[int(c - a):int(c - a) + 10] += r * 3
    pico = a + int(np.argmax(np.convolve(calor, np.ones(15), "same")))
    s, e = max(0, pico - 15), pico + 30
    info = ler_json(pasta / "info.json", {})
    nome = info.get("uploader") or ""
    return {"inicio": s, "fim": e, "nota": 70, "titulo": _titulo_auto(pasta, s, e),
            "post": f"Olha isso na live {('do ' + nome) if nome else ''} 😳 #cortes #live #aovivo", "_auto": True}


# ---------------------------------------------------------------- fila de cortes
def na_fila(pasta, momentos):
    """Põe momentos na fila (sem repetir os que se sobrepõem a um já na fila). Devolve os que entraram."""
    fila = ler_json(pasta / "fila.json", [])
    entrou = []
    for m in sorted(momentos, key=lambda m: -float(m.get("nota") or 70)):
        from cortar import _campo
        try:
            s, e = segundos(_campo(m, "inicio")), segundos(_campo(m, "fim"))
        except (TypeError, ValueError, AttributeError):
            continue
        if e < s:
            s, e = e, s
        s = max(0.0, s)
        e = min(max(e, s + 20), s + 60)
        try:
            nota = float(str(_campo(m, "nota") or 70).split("/")[0])
        except ValueError:
            nota = 70.0
        if nota < 60 or any(s < f["_e"] and f["_s"] < e for f in fila):
            continue
        item = {**m, "_s": s, "_e": e, "nota": nota, "n": len(fila) + 1, "estado": "esperando",
                "titulo": str(_campo(m, "titulo") or "").strip(),
                "post": str(_campo(m, "post") or "").strip() or "#cortes #live"}
        fila.append(item)
        entrou.append(item)
    gravar_json(pasta / "fila.json", fila)
    return entrou


def montar(pasta, m, idx):
    import shutil
    from cortar import FONTES, _titulo_auto, achar_camera, escrever_ass, filtro, palavras_do_trecho
    info = ler_json(pasta / "info.json", {})
    st = estado(pasta)
    destino = CORTES / pasta.name
    destino.mkdir(parents=True, exist_ok=True)
    n, s, e = m["n"], m["_s"], m["_e"]
    titulo = m.get("titulo") or _titulo_auto(pasta, s, e)
    print(f"\n[corte {n}] {titulo}  ({hms(s)}–{hms(e)})", flush=True)
    tdir = pasta / f"corte_{n:02d}"
    tdir.mkdir(exist_ok=True)
    trecho = tdir / "trecho.mp4"
    extrair(pasta, idx, s, e, trecho)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(trecho)], capture_output=True, text=True).stdout.strip() or e - s)
    W, H, rosto = achar_camera(trecho)
    print("      câmera do streamer achada" if rosto is not None else "      sem câmera: imagem inteira com fundo desfocado",
          flush=True)
    idioma = st.get("idioma") or st.get("idioma_detectado")
    palavras = palavras_do_trecho(trecho, idioma, st.get("modelo_legenda") or "small")
    escrever_ass(tdir / "legenda.ass", titulo, palavras, dur, rosto is not None)
    (tdir / "fontes").mkdir(exist_ok=True)
    for fonte in FONTES.glob("*.ttf"):
        shutil.copy(fonte, tdir / "fontes" / fonte.name)
    saida = destino / f"corte_{n:02d}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", "trecho.mp4", "-filter_complex", filtro(W, H, rosto),
                    "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-r", "30",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(saida.resolve())],
                   cwd=tdir, check=True)
    saida.with_suffix(".txt").write_text(
        f"{titulo}\n\n{m.get('post', '').strip()}\n\nCorte da live de {info.get('uploader') or info.get('channel')}: "
        f"{info.get('webpage_url') or info.get('url')}\n", encoding="utf-8")
    print(f"      PRONTO: {saida}", flush=True)
    return saida


def mudar_fila(pasta, n, **mud):
    fila = ler_json(pasta / "fila.json", [])
    for f in fila:
        if f["n"] == n:
            f.update(mud)
    gravar_json(pasta / "fila.json", fila)


# ---------------------------------------------------------------- o trabalhador (segundo plano)
def trabalhar(pasta):
    st = estado(pasta)
    parar_chat = threading.Event()
    iniciar_chat(pasta, st, parar_chat)
    rec, falhas = None, 0
    print(f"Trabalhador ao vivo começou: {st.get('titulo')}", flush=True)
    while True:
        st = estado(pasta)
        pedido_parar = (pasta / ".parar").exists()
        # 1. gravação: mantém o ffmpeg rodando enquanto a live estiver no ar
        if pedido_parar and rec is not None and rec.poll() is None:
            rec.terminate()
            rec.wait(timeout=30)
        if pedido_parar and not st.get("encerrada"):
            st = mexer(pasta, encerrada=True, motivo="parado")
            print("Pediram pra parar: parei de gravar, terminando o que falta…", flush=True)
        if not st.get("encerrada") and (rec is None or rec.poll() is not None):
            if rec is not None:
                print("      a gravação caiu, conferindo se a live acabou…", flush=True)
                if situacao(st["url"]) != "is_live":
                    st = mexer(pasta, encerrada=True, motivo="live acabou")
                    print("A LIVE ACABOU: terminando o que falta…", flush=True)
            if not st.get("encerrada"):
                rec = gravar(pasta, st)
                if rec is None:
                    falhas += 1
                    if falhas >= 5:
                        st = mexer(pasta, encerrada=True, motivo="não consegui gravar")
                        print("Não consegui gravar depois de 5 tentativas: encerrando.", flush=True)
                    time.sleep(20)
                    continue
                falhas = 0
                time.sleep(5)
        idx = indice(pasta, st)
        gravado = idx[-1][3] if idx else 0
        mexer(pasta, gravado=gravado)
        # 2. cortes que já dá pra montar (prioridade: é o que a pessoa vai postar)
        fila = ler_json(pasta / "fila.json", [])
        pronto = next((f for f in fila if f["estado"] == "esperando" and (f["_e"] <= gravado or st.get("encerrada"))),
                      None)
        if pronto:
            try:
                montar(pasta, pronto, idx)
                mudar_fila(pasta, pronto["n"], estado="pronto")
            except Exception as ex:
                print(f"      ✗ não consegui montar o corte {pronto['n']}: {ex}", flush=True)
                mudar_fila(pasta, pronto["n"], estado="erro", erro=str(ex)[:300])
            continue
        # 3. escutar o próximo pedaço de 5 min
        k = st.get("pedacos", 0)
        if gravado >= (k + 1) * PEDACO + 2 or (st.get("encerrada") and gravado > k * PEDACO + 20):
            escutar(pasta, st, k, idx)
            mexer(pasta, pedacos=k + 1)
            if st.get("auto"):
                m = momento_auto(pasta, k)
                if m:
                    for item in na_fila(pasta, [m]):
                        print(f"      (auto) momento na fila: {item['titulo']}", flush=True)
            continue
        if st.get("encerrada"):
            break
        time.sleep(5)
    parar_chat.set()
    mexer(pasta, terminou=True)
    print("\nTRABALHO AO VIVO ENCERRADO.", flush=True)


# ---------------------------------------------------------------- comandos
def cmd_instalar(_):
    sh = CASA / "aovivo"
    sh.write_text(f'#!/bin/sh\nexec "{VENV_PY.as_posix()}" "{AQUI.as_posix()}" "$@"\n', encoding="utf-8")
    try:
        sh.chmod(0o755)
    except OSError:
        pass
    if os.name == "nt":
        (CASA / "aovivo.cmd").write_text(f'@"{VENV_PY}" "{AQUI}" %*\r\n', encoding="utf-8")
    preparar_ffmpeg()
    print(f"  ✓ usando o clipper em {ORIG}")
    print(f"  ✓ atalho: {sh}" + (f"  (PowerShell: {CASA / 'aovivo.cmd'})" if os.name == "nt" else ""))
    print("\nTUDO PRONTO. Mande o link de uma live que está NO AR agora.")


def _trabalhador_rodando(pasta):
    pid = int((pasta / ".aovivo.pid").read_text() or 0) if (pasta / ".aovivo.pid").exists() else 0
    return pid if vivo(pid) else 0


def cmd_iniciar(a):
    url = a.link
    print(f"Lendo a live: {url}", flush=True)
    meta, erro = ler_meta(url)
    if meta is None:
        motivo = motivo_trancada(erro)
        if motivo:
            sys.exit(f"\n  ✗ NÃO DÁ PRA BAIXAR: {motivo}.")
        if "not currently live" in erro.lower() or "offline" in erro.lower():
            sys.exit("\n  ✗ ESSA LIVE NÃO ESTÁ NO AR AGORA. Se ela já acabou, use o clipper normal (clipper-gta6).")
        print(erro[-800:])
        sys.exit("\n  ✗ Não consegui ler essa live. Confira o link e rode 'instalar' do clipper-gta6 (atualiza o baixador).")
    if meta.get("live_status") != "is_live" and not meta.get("is_live"):
        sys.exit("\n  ✗ ESSA LIVE NÃO ESTÁ NO AR AGORA (já acabou ou nem começou).\n"
                 "    Se já acabou, use o clipper normal: 'corta essa live: LINK'.")
    nome = "aovivo-" + slug(f"{meta.get('uploader') or meta.get('channel') or 'live'}-{meta.get('title', '')}", 52)
    pasta = TRABALHO / nome
    pasta.mkdir(parents=True, exist_ok=True)
    if _trabalhador_rodando(pasta):
        print(f"\nJÁ ESTAVA GRAVANDO essa live: {nome}")
        return cmd_status(argparse.Namespace(live=nome))
    info = {k: meta.get(k) for k in ("id", "title", "uploader", "channel", "webpage_url", "extractor_key")}
    info.update(url=url, live_status="is_live")
    gravar_json(pasta / "info.json", info)
    st = estado(pasta)
    if not st or st.get("terminou"):
        st = {"url": url, "titulo": meta.get("title"), "t0": time.time(), "sessoes": [], "pedacos": 0}
    st.update(auto=a.auto, idioma=a.idioma, modelo=a.modelo, modelo_legenda=a.modelo_legenda,
              encerrada=False, terminou=False)
    (pasta / ".parar").unlink(missing_ok=True)
    for s in st.get("sessoes", []):  # gravação velha que ficou rodando sozinha
        matar(s.get("pid"))
    salvar(pasta, st)
    log = open(pasta / ".aovivo.log", "a", encoding="utf-8")
    proc = destacado([sys.executable, str(AQUI), "_trabalhar", str(pasta)], log)
    (pasta / ".aovivo.pid").write_text(str(proc.pid))
    print(f"\nGRAVANDO AO VIVO: {meta.get('title')}  |  {meta.get('uploader')}")
    print(f"  nome: {nome}")
    print(f"  a cada {PEDACO // 60} min gravados ele escuta o pedaço e avisa as novidades.")
    print("  modo: " + ("AUTOMÁTICO (escolhe e monta sozinho)" if a.auto else
                        f"a IA escolhe — rode: esperar {nome}"))


def _novos(pasta, marcar=True):
    st = estado(pasta)
    lido, feitos = st.get("lido", 0), st.get("pedacos", 0)
    textos = [(pasta / "novos" / f"pedaco_{k:04d}.txt").read_text(encoding="utf-8")
              for k in range(lido, feitos) if (pasta / "novos" / f"pedaco_{k:04d}.txt").exists()]
    if marcar and feitos > lido:
        mexer(pasta, lido=feitos)
    return textos


def _mostrar_novidades(pasta, textos):
    rodada = len(list((pasta / "momentos").glob("rodada_*.json"))) + 1 if (pasta / "momentos").exists() else 1
    print("\nNOVIDADES DA LIVE (tempo = desde que a gravação começou)\n")
    print("\n\n".join(textos))
    print(f"\nSe tiver momento bom, escreva em: {pasta / 'momentos' / f'rodada_{rodada:02d}.json'}")
    print(f"  (mesmo formato do clipper-gta6) e rode: cortar {pasta.name}")
    print(f"  Sem momento bom? Só rode: esperar {pasta.name}")
    (pasta / "momentos").mkdir(exist_ok=True)


def cmd_novidades(a):
    pasta = pasta_da_live(a.live)
    textos = _novos(pasta)
    if not textos:
        print("Nada novo ainda.")
        return cmd_status(a)
    _mostrar_novidades(pasta, textos)


def cmd_esperar(a):
    pasta = pasta_da_live(a.live)
    t0 = time.time()
    prontos_antes = {f["n"] for f in ler_json(pasta / "fila.json", []) if f["estado"] == "pronto"}
    while time.time() - t0 < a.esperar:
        st = estado(pasta)
        prontos = [f for f in ler_json(pasta / "fila.json", []) if f["estado"] == "pronto" and f["n"] not in prontos_antes]
        for f in prontos:
            print(f"CORTE PRONTO: {CORTES / pasta.name / ('corte_%02d.mp4' % f['n'])}  —  {f.get('titulo', '')}")
        if st.get("pedacos", 0) > st.get("lido", 0):
            _mostrar_novidades(pasta, _novos(pasta))
            return
        if st.get("terminou"):
            print("A live acabou e tudo que estava na fila foi montado.")
            return cmd_status(a)
        if not _trabalhador_rodando(pasta):
            sys.exit("O trabalhador parou sozinho. Veja o fim do log com: status " + pasta.name)
        if prontos:
            return
        time.sleep(10)
    print("AINDA ESPERANDO o próximo pedaço (é normal). Rode o MESMO comando de novo.")
    cmd_status(a)


def cmd_cortar(a):
    from cortar import ler_tolerante
    pasta = pasta_da_live(a.live)
    momentos = []
    for arq in sorted((pasta / "momentos").glob("*.json")):
        d = ler_tolerante(arq)
        if d is None:
            print(f"  ✗ {arq.name}: não é um JSON que dá pra ler, confira o formato")
            continue
        momentos += d
    entrou = na_fila(pasta, momentos)
    if not entrou:
        print("Nenhum momento novo entrou na fila (nota abaixo de 60 ou repetido).")
    for m in entrou:
        print(f"  na fila: corte {m['n']}  [{hms(m['_s'])}–{hms(m['_e'])}] nota {m['nota']:.0f}  {m['titulo']}")
    if entrou:
        print("\nO trabalhador monta assim que der. Continue com: esperar " + pasta.name)


def cmd_status(a):
    pastas = [pasta_da_live(a.live)] if getattr(a, "live", None) else sorted(TRABALHO.glob("aovivo-*"))
    if not pastas:
        print("Nenhuma live ao vivo ainda.")
        return
    for pasta in pastas:
        st = estado(pasta)
        fila = ler_json(pasta / "fila.json", [])
        gravado = st.get("gravado", 0)
        escutado = min(gravado, st.get("pedacos", 0) * PEDACO)
        prontos = sum(f["estado"] == "pronto" for f in fila)
        rodando = _trabalhador_rodando(pasta)
        situ = ("ENCERRADO" if st.get("terminou") else "terminando o que falta" if st.get("encerrada")
                else "GRAVANDO AO VIVO" if rodando else "PARADO (rode iniciar de novo)")
        print(f"\n{pasta.name}\n  {st.get('titulo', '')}\n  situação: {situ}")
        print(f"  gravado:   {hms(gravado)}")
        print(f"  escutado:  {barra(escutado / gravado if gravado else 0)}  até {hms(escutado)}"
              f" (atraso {int((gravado - escutado) // 60)} min)")
        if fila:
            print(f"  cortes:    {barra(prontos / len(fila))}  {prontos} de {len(fila)} prontos")
            for f in fila:
                marca = {"pronto": "✅", "esperando": "⏳", "erro": "❌"}.get(f["estado"], "•")
                print(f"     {marca} corte {f['n']:02d} [{hms(f['_s'])}] {f.get('titulo', '')}")
        gdir = pasta / "gravacao"
        if gdir.exists():
            mb = sum(p.stat().st_size for p in gdir.glob("*.ts")) / 1e6
            print(f"  disco:     {mb / 1000:.1f} GB de gravação")
        if prontos:
            print(f"  pasta:     {CORTES / pasta.name}")
        if not rodando and not st.get("terminou"):
            log = pasta / ".aovivo.log"
            if log.exists():
                print("  fim do log:\n    " + "\n    ".join(log.read_text(errors="ignore").splitlines()[-8:]))


def cmd_parar(a):
    pasta = pasta_da_live(a.live)
    if a.agora:  # para tudo já, sem escutar o que sobrou nem montar a fila
        pid = _trabalhador_rodando(pasta)
        if pid:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                try:
                    os.killpg(pid, 15)  # o trabalhador e tudo que ele abriu (gravação, chat)
                except OSError:
                    matar(pid)
        for s in estado(pasta).get("sessoes", []):
            matar(s.get("pid"))
        mexer(pasta, encerrada=True, terminou=True, motivo="parado na hora")
        print("PAREI TUDO. Os cortes que já estavam prontos continuam em " + str(CORTES / pasta.name))
        return
    (pasta / ".parar").write_text("ok")
    print("Pedi pra parar. Ele termina de escutar o que já gravou e monta os cortes da fila; acompanhe com: status "
          + pasta.name)


def cmd_limpar(a):
    import shutil
    pasta = pasta_da_live(a.live)
    if _trabalhador_rodando(pasta):
        sys.exit("Ainda está rodando. Rode 'parar' e espere encerrar antes de limpar.")
    gdir = pasta / "gravacao"
    if gdir.exists():
        mb = sum(p.stat().st_size for p in gdir.glob("*")) / 1e6
        shutil.rmtree(gdir)
        shutil.rmtree(pasta / "chat_yt", ignore_errors=True)
        print(f"Apaguei a gravação bruta ({mb / 1000:.1f} GB). Os cortes prontos continuam em {CORTES / pasta.name}")
    else:
        print("Não tinha gravação pra apagar.")


def main():
    utf8()
    no_ambiente()
    preparar_ffmpeg()
    ap = argparse.ArgumentParser(description="Clipper ao vivo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("instalar").set_defaults(f=cmd_instalar)
    i = sub.add_parser("iniciar")
    i.add_argument("link")
    i.add_argument("--auto", action="store_true", help="escolhe e monta sozinho, sem a IA")
    i.add_argument("--idioma", default=None)
    i.add_argument("--modelo", default=None, help="modelo de escuta (padrão: base; tiny em PC fraco)")
    i.add_argument("--modelo-legenda", dest="modelo_legenda", default="small")
    i.set_defaults(f=cmd_iniciar)
    for nome, func in (("esperar", cmd_esperar), ("novidades", cmd_novidades), ("cortar", cmd_cortar),
                       ("parar", cmd_parar), ("limpar", cmd_limpar)):
        p = sub.add_parser(nome)
        p.add_argument("live")
        if nome == "esperar":
            p.add_argument("--esperar", type=int, default=ESPERA)
        if nome == "parar":
            p.add_argument("--agora", action="store_true", help="para tudo já, sem terminar a fila")
        p.set_defaults(f=func)
    s = sub.add_parser("status")
    s.add_argument("live", nargs="?")
    s.set_defaults(f=cmd_status)
    w = sub.add_parser("_trabalhar")
    w.add_argument("pasta")
    w.set_defaults(f=lambda a: trabalhar(Path(a.pasta)))
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
