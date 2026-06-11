# Vodič za pokretanje Scribe-a na Windows-u preko WSL-a sa Ollama-om

Ovaj vodič objašnjava kako da uspešno instalirate Scribe unutar **WSL-a (Windows Subsystem for Linux)** i povežete ga sa **Ollama** modelima na lokalnoj mašini.

---

## 🛠️ Preduslovi za WSL

Sveže instaliran WSL (npr. Ubuntu) obično ne dolazi sa preinstaliranim Python paket menadžerom (`pip`) i modulom za virtuelna okruženja. Pre pokretanja instalacije Scribe-a, pokrenite sledeću komandu u svom WSL terminalu:

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv
```

---

## Scenario A: Instalacija Ollama-e direktno unutar WSL-a (Preporučeno i najlakše)

Pokretanje Ollama-e unutar WSL-a je najjednostavniji način jer omogućava korišćenje `127.0.0.1` (localhost) za komunikaciju i automatski koristi grafičku karticu (GPU) ako imate instalirane drajvere na Windows-u.

### 1. Instalacija Ollama-e u WSL-u
Otvorite vaš WSL terminal (npr. Ubuntu) i pokrenite zvaničnu instalacionu skriptu:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Pokretanje modela
Učitajte željeni model u Ollama-u:
```bash
ollama run gemma2
```

### 3. Konfigurisanje Scribe-a
U WSL-u kreirajte ili uredite konfiguracioni fajl `~/.config/scribe/config.toml`:
```toml
[scribe]
base_url = "http://127.0.0.1:11434/v1"
model = "gemma2"
```
Nakon toga pokrenite Scribe sa:
```bash
scribe chat
```

---

## Scenario B: Ollama radi na Windows-u (Host), a Scribe u WSL-u

Ako imate instaliranu Ollama aplikaciju direktno na Windows-u, WSL ne može podrazumevano da pristupi adresi `127.0.0.1` jer WSL ima sopstvenu virtuelnu mrežu. Primenite sledeće korake:

### 1. Konfigurisanje Ollama-e na Windows-u
Morate naterati Ollama-u da sluša na svim mrežnim interfejsima (ne samo na localhost-u):
1. Pritisnite **Win + R**, ukucajte `sysdm.cpl` i pritisnite Enter.
2. Idite na karticu **Advanced** i kliknite na **Environment Variables**.
3. Pod *User variables* ili *System variables* kliknite na **New...** i dodajte:
   * **Variable name:** `OLLAMA_HOST`
   * **Variable value:** `0.0.0.0`
4. Kliknite na OK, sačuvajte i **potpuno ugasite pa ponovo pokrenite Ollama aplikaciju** na Windows-u (iz system tray-a).

### 2. Pronalaženje IP adrese Windows-a iz WSL-a
Iz vašeg WSL terminala saznajte IP adresu Windows domaćina pokretanjem:
```bash
cat /etc/resolv.conf | grep nameserver | awk '{print $2}'
```
*(Primer ispisa: `172.25.80.1`)*

### 3. Konfigurisanje Scribe-a u WSL-u
Uredite `~/.config/scribe/config.toml` u WSL-u i zamenite `<WINDOWS_IP>` adresom koju ste dobili u prethodnom koraku:
```toml
[scribe]
base_url = "http://172.25.80.1:11434/v1"  # Unesite vaš Windows IP ovde
model = "gemma2"
```

### 4. Alternativa za Windows 11 (Mirrored Networking)
Ako koristite Windows 11, možete uključiti deljeni mrežni režim. Kreirajte fajl `C:\Users\VašeIme\.wslconfig` sa sledećim sadržajem:
```ini
[wsl2]
networkingMode=mirrored
```
Nakon restarta WSL-a (`wsl --shutdown` iz PowerShell-a), Scribe u WSL-u će moći da pristupi Ollama-i na Windows-u preko jednostavnog `http://127.0.0.1:11434/v1` bez traženja IP adrese!
