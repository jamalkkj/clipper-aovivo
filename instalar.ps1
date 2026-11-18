# Instala (ou atualiza) o Clipper AO VIVO no Windows com um comando só (PowerShell):
#   irm https://raw.githubusercontent.com/jamalkkj/clipper-aovivo/main/instalar.ps1 | iex
$ErrorActionPreference = "Stop"
$py = "$HOME\clipper-gta6\ambiente\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "Falta o Clipper do GTA 6 (a base do modo ao vivo). Instale ele primeiro com:"
  Write-Host "  irm https://raw.githubusercontent.com/davixavier-coder/skill-clips/main/instalar.ps1 | iex"
  Write-Host "Quando aparecer TUDO PRONTO, rode este comando de novo."
  return
}
$dest = "$HOME\.claude\skills\clipper-aovivo"
$zip = "$env:TEMP\clipper-aovivo.zip"
$tmp = "$env:TEMP\clipper-aovivo-tmp"
Write-Host "Baixando o Clipper AO VIVO pra $dest..."
Invoke-WebRequest https://github.com/jamalkkj/clipper-aovivo/archive/refs/heads/main.zip -OutFile $zip
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $zip $tmp -Force
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item "$tmp\clipper-aovivo-main\*" $dest -Recurse -Force
& $py "$dest\scripts\aovivo.py" instalar
