# SCRIBE — Autonomous Research & Writing Agent

> Universal TUI agent that connects to **any** llama.cpp server and uses RAG + semantic memory to research, write, and remember — across sessions.

---

## Status Ocene: **420/1000** — Originalni plan je bio dobra osnova ali nedostajalo je: konkretni setup koraka, timeline, exit criteria, risk assessment, i GitHub-ready distribution model.

---

# Ažurirani Plan: Scribe v2

## Sadržaj

0. [Filozofski Temelj](#0-filozofski-temelj—-jezičke-igre-wittgenstein)
   - [Wittgenstein: Jezičke Igre](#01-zašto-jezik-nije-samo-inputoutput)
   - [Peirce: Semiotika](#09-peirceeva-semiotika—-znak-kao-proces-tumačenja)
1. [Pregled Sistema](#1-pregled-sistema)
2. [Arhitektura](#2-arhitektura)
3. [Komponente](#3-komponente)
4. [Faze Implementacije](#4-faze-implementacije)
5. [Distribution Model (GitHub)](#5-distribution-model-github)
6. [Konzolne Komande](#6-konzolne-komande)
7. [Konfiguracija](#7-konfiguracija)
8. [Exit Criteria](#8-exit-criteria)
9. [Risk Assessment](#9-risk-assessment)
10. [Timeline](#10-timeline)
11. [Resursi](#11-resursi)
12. [Diferenciranje od Sličnih Projekata](#12-diferenciranje-od-sličnih-projekata)
13. [GitHub Release Checklist](#13-github-release-checklist)

---

## Jezička Konvencija

> ⚠️ **Važno:** Sav kod, komentari, commit poruke, variable names, function names, file names — **SVE NA ENGLESKOM**.
>
> Srpski koristimo samo za我跟 ovde u konverzaciji — dogovaramo se na srpskom, zapisujemo na engleskom.

Ovo osigurava:
- Direktnu kompatibilnost sa open-source zajednicom
- Lakše preuzimanje koda od strane drugih developera
- Konzistentnost sa Python/Rich ekosistemom
- Automatski parsing i tooling

---

## 0. Filozofski Temelj — Jezičke Igre (Wittgenstein)

> *"Značenje nije skriveno u reči — značenje je u upotrebi."*
> — Ludvig Vitgenštajn, Kasni period

Ovo nije sekcija koju možete preskočiti. Ovo je **srž** dizajna Scribe-a.

### 0.1 Zašto jezik nije samo input/output

Standardni view LLM interakcije:
```
Čovek: "Istraži temu X"
LLM: "Evo rezultata..."
```

To je **pogrešan model**. Posmatra jezik kao prenos informacija — čovek šalje tekst, LLM vraća tekst.

Vitgenštajnova alternativa:
```
Čovek: [igra jezičku igru "istraživanje"]
LLM: [odgovara u okviru iste jezičke igre, sa pravilima šta znači "istraživati"]
```

Razlika: u prvom modelu, LLM može "nadograđivati" nejasnoće. U drugom, nejasnoće ne postoje jer su pravila jasna.

### 0.2 Šta je jezička igra?

Jezička igra je **skup pravila** koji definiše:

| Element | Pitanje | Primer za Scribe |
|---|---|---|
| **Uloge** | Ko sam ja, ko je LLM? | Ja sam istraživač → LLM je istraživački agent |
| **Cilj** | Šta je "uspešan potez"? | Hipoteza + protivargumenti + izvori |
| **Greška** | Šta ne valja? | Halucinacija, nepotvrđen izvor |
| **Završetak** | Kada je igra gotova? | Sva pitanja iz plana odgovorena |
| **Provera** | Ko proverava? | SME memory check, RAG citation |

### 0.3 Harness kao "gramatika ponašanja"

Harness nije samo tehnički sloj (agent, alati, memorija). **Harness je gramatika ponašanja modela.**

On kaže:
- Kada model sme odmah da odgovori
- Kada mora da traži dokaz
- Kada mora da koristi alat
- Kada sme da spekuliše
- Kada mora da prizna nesigurnost
- Kada mora da stane

### 0.4 Operativni rečnik Scribe-a

Scribe ima eksplicitan **rečnik komandi** — ne kao običan glossary, nego kao operativna gramatika:

```
ISTRAŽI = koristi web pretragu, pravi hipoteze, nalazi protivargumente,
           razdvoji dokaze od spekulacije, označi šta je neprovereno

OCENI = daj numerički skor (1-10), navedi kriterijume,
        identifikuj slabosti, predloži poboljšanje

NACRTaj = prikaži module sistema, tok podataka,
           minimalni MVP, rizike, sledeće korake

KNJIGA = struktura poglavlja + argument + stil + provera činjenica

AGENT = planira → koristi alate → vodi dnevnik → proverava rezultat → staje

MEMORIJA = odvoji: trajno (SME) / privremeno (RAG) / radno (kontekst) / epizodno (session)
```

### 0.5 Unutrašnji jezik modela

Za dugotrajne agentske zadatke, Scribe koristi strukturirani format koji model **razume kao jezičku igru**:

```
OBSERVATION: [šta je viđeno, šta se desilo]
CLAIM: [šta tvrdim da je tačno]
EVIDENCE: [na osnovu čega — izvor, logika, eksperiment]
UNCERTAINTY: [šta ne znam, šta može biti pogrešno]
PLAN: [šta radim sledeće, korak po korak]
ACTION: [poziv alata / komanda]
RESULT: [šta se desilo kao odgovor na ACTION]
REVISION: [šta menjam u PLAN-u na osnovu RESULT]
FINAL: [šta korisnik dobija kao gotov rezultat]
```

Ovo je **praktični Vitgenštajn**: dajemo modelu pravila jezičke igre mišljenja.

### 0.6 Čovek i LLM moraju deliti igru

Najbolji razgovor nastaje kad oboje znaju koju igru igraju:

| Nejasno | Jasno (jezička igra) |
|---|---|
| "Hajde da filozofiramo" | "Napravimo radnu hipotezu koju mogu testirati na mašini" |
| "Napiši knjigu" | "Struktura: whitepaper + blueprint + eksperimentalni protokol + narativni uvod" |
| "Popravi kod" | "Pronađi bug, napiši minimalni test koji reprodukuje problem, popravi, verifikuj" |

### 0.7 Glavna formula Scribe-a

```
LLM harness = sistem koji pretvara neodređeni prirodni jezik
               u stabilne jezičke igre
               sa pravilima, ulogama, alatima, proverama i završnim kriterijumima.
```

 Ili kraće:

> **Ne dizajniraš samo agenta. Dizajniraš jezik u kome agent može normalno da misli.**

### 0.8 Kako se ovo implementira u Scribe

| Sloj | Implementacija |
|---|---|
| **Skills** | Svaki skill definiše svoju jezičku igru — koje komande postoje, šta znače, kada se koriste |
| **System Prompt** | Template koji eksplicitno navodi trenutnu jezičku igru: "U ovoj sesiji, 'istraži' znači..." |
| **TUI** | Rich interfejs koji vizuelno signalizira koja je igra u toku (ikone, boje, progres) |
| **Checkpoint** | State uključuje i trenutnu jezičku igru — nastavak je moguć samo ako se igra razume |
| **SME Memory** | Pamti ne samo fakta, nego i koje su jezičke igre korišćene i sa kojim uspehom |

---

### 0.9 Peirceeva Semiotika — Znak kao Proces Tumačenja

> *"Znak nije stvar koja nešto znači — znak je proces koji proizvodi značenje kroz tumačenje."*
> — Charles Sanders Peirce

Peirce daje dublji okvir od Vitgenštajna za LLM harness. Dok Wittgenstein definiše pravila igre, Peirce opisuje **proces kroz koji znak dobija značenje**.

#### 0.9.1 Semioza — Lanac Tumačenja

Standardni model komunikacije:
```
čovek → prompt → model → odgovor → čovek
```

Peirceov model:
```
SIGN → INTERPRETANT → NEW SIGN → NEW INTERPRETANT → ...
```

Za LLM: svaki odgovor nije kraj, nego **sledeći znak u lancu semioze**.

#### 0.9.2 Peirceov Trojstvo Znaka

Svaki znak ima tri komponente:

| Component | Definition | LLM Example |
|---|---|---|
| **Representamen** | The sign itself (what you see/hear/read) | Prompt, response, command, tokens, file |
| **Object** | What the sign refers to | Task, topic, document, hypothesis, user intent |
| **Interpretant** | The meaning produced in the mind/system | How the model understands the task and decides what to do |

Critical insight: **meaning is not in the sign alone. Meaning emerges in interpretation.**

#### 0.9.3 Ikone, Indeksi, Simboli — Brutalno Korisno

Peirce classifies signs by their relationship to objects:

**Ikona** — liči na ono što predstavlja
- Maps, diagrams, flowcharts, architecture sketches
- LLM use: "Draw a blueprint", "Show module structure"
- In Scribe: visual representations of agent state

**Indeks** — pokazuje na nešto stvarno i povezano
- Citations, logs, timestamps, error messages, test results
- LLM use: grounds symbols in reality, fights hallucinations
- In Scribe: every claim must have an index (source, citation, evidence)

**Simbol** — znači po konvenciji
- Words, commands, tags, JSON schemas, module names
- In Scribe: the internal language markers (OBSERVATION, CLAIM, etc.)

**Rule: Without indices, symbols are just "magical thinking."**

#### 0.9.4 Abdukcija — Zaključivanje ka Najboljem Objašnjenju

Three types of reasoning:

| Type | Pattern | LLM Use |
|---|---|---|
| **Deduction** | Rule + Case → Result | Always valid if premises are true |
| **Induction** | Cases → Rule | Generalizing from examples |
| **Abduction** | Observation → Best Explanation | LLM constantly does this when interpreting vague prompts |

Scribe's abductive mode:
```
OBSERVATION: What do I see?

POSSIBLE EXPLANATIONS:
1. ...
2. ...
3. ...

BEST HYPOTHESIS: Which explanation best fits the evidence?

TEST: How do I verify?

REVISION: What changes if the test fails?
```

#### 0.9.5 Peirce Loop (SEMIOSIS)

The core agent loop in Peircean terms:

```
1. PARSE SIGN     — User prompt as representamen
2. IDENTIFY OBJECT — Map to actual task
3. GENERATE INTERPRETANTS — Possible interpretations
4. ABDUCE HYPOTHESIS — Find best explanation
5. GROUND WITH INDICES — Check sources, tools, logs
6. BUILD ICONIC MODEL — Diagram, structure, blueprint
7. PRODUCE SYMBOLIC RESPONSE — Text, command, plan
8. STORE NEW SIGN — Memory becomes next interpretant
```

#### 0.9.6 Tri Sredstva Značenja (Three Modes of Meaning)

Every LLM communication should involve all three:

| Mode | Purpose | Scribe Implementation |
|---|---|---|
| **Symbolic** | Language, categories, logic | Internal markers, system prompts, skill definitions |
| **Iconic** | Visualization, structure, mapping | Diagrams in TUI, blueprints, flowcharts |
| **Indexical** | Grounding in reality | Citations, RAG sources, tool outputs, logs |

**No index = possible hallucination.**

#### 0.9.7 Scribe kao Semiotička Mašina

> **Scribe is a semiotic engine: it takes the user's sign, produces an interpretant, grounds it in indices, builds an iconic model, and returns a symbolic response that can become the next sign in the chain.**

Memory in Scribe is not a text warehouse. It is a **semiotic graph**:
```
SIGN → INTERPRETANT → OBJECT → EVIDENCE → REVISION → NEXT SIGN
```

#### 0.9.8 Combining Wittgenstein + Peirce

| Philosopher | Focus | Contribution to Scribe |
|---|---|---|
| **Wittgenstein** | Language games, rules | Defines what commands mean (grammar of behavior) |
| **Peirce** | Semiosis, interpretation chain | Defines how meaning develops through dialogue |

Together:
> **Scribe defines language games (Wittgenstein) through which signs flow and gain meaning (Peirce), creating a stable interpretative chain where every symbol is grounded by indices, organized by icons, and stored for future semiosis.**

---

## 1. Pregled Sistema

**Scribe** je autonomous agent za istraživanje i pisanje koji:
- Se povezuje na **bilo koji** `llama-server` endpoint (lokalni ili remote)
- Koristi **RAG** (LanceDB + embedding model) za semantičku pretragu dokumenata
- Ima **SME** (Semantic Memory Engine) za kontinuitet između sesija
- Ima **Rich TUI** za lep interfejs u terminalu
- Modularan je —Skills sistem dozvoljava dodavanje novih sposobnosti

### Šta već postoji (ne pišemo od nule)

| Komponenta | Status | Lokacija |
|---|---|---|
| `llama.cpp` server | ✅ Radi na portu 18083 | `/home/user/llama.cpp/` |
| RAG (LanceDB + e5-small) | ✅ Radi lokalno na CPU | `~/.kon/tools/rag_*.py` |
| SME (semantička memorija) | ✅ Radi, LanceDB-backed | `~/.kon/sme/memory.lance/` |
| Skills sistem | ✅ Postoji, 14 skill-ova | `~/.agents/skills/` |
| KonfigTOML | ✅ Konfiguracija | `~/.kon/config.toml` |
| Self-Diary Layer | ✅ Metakognicija | `~/.kon/self_diary_layer.py` |
| systemd service | ✅ Radi, auto-restart | `gemma-4-12b-18083.service` |

### Ciljna publika

- Developeri koji imaju GPU i žele lokalnog AI agenta
- Istraživači koji hoće autonomous deep research bez cloud zavisnosti
- Pisci koji hoće da model pomaže u istraživanju i strukturiranju knjiga

---

## 2. Arhitektura

```
┌─────────────────────────────────────────────────────────────┐
│                        SCRIBE TUI                           │
│                    (Rich-based interface)                    │
├─────────────────────────────────────────────────────────────┤
│                      CORE KERNEL                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │   Session    │  │   Skills    │  │   Config    │      │
│  │   Manager    │  │   Loader    │  │   Manager   │      │
│  └─────────────┘  └─────────────┘  └─────────────┘      │
├─────────────────────────────────────────────────────────────┤
│                    LLM ADAPTER LAYER                        │
│  ┌─────────────────────────────────────────────────┐      │
│  │     OpenAI-compatible HTTP client (llama.cpp)    │      │
│  │  → Connects to ANY llama-server endpoint         │      │
│  │  → Supports custom models, context sizes        │      │
│  └─────────────────────────────────────────────────┘      │
├─────────────────────────────────────────────────────────────┤
│                      MEMORY LAYER                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  SME (Lance) │  │  RAG (Lance) │  │ Self-Diary   │   │
│  │  Cross-session│  │  Documents   │  │ Metacognition│   │
│  │  memory       │  │  semantic    │  │              │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                      TOOLS LAYER                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │ web_search│  │ web_fetch│  │  bash    │  │ file   │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Ključna razlika od originalnog plana

Umesto hardkodiranog povezivanja na Gemma 4, Scribe koristi **adapter pattern**:
- Bilo koji `llama-server` endpoint (lokalni ili remote)
- Bilo koji model koji server podržava
- Konfiguracija preko `config.toml` ili CLI argumenata

---

## 3. Komponente

### 3.1 LLM Adapter

```python
# Pseudocode — llm_adapter.py
class LLMAdapter:
    def __init__(self, base_url: str, api_key: str = "not-needed"):
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def complete(self, messages: list[dict], **kwargs) -> str:
        response = self.client.chat.completions.create(
            model="whatever",
            messages=messages,
            **kwargs
        )
        return response.choices[0].message.content

    def streaming_complete(self, messages: list[dict], callback, **kwargs):
        # yield chunks to Rich progress bar
        pass
```

**Povezuje se na:**
- `http://127.0.0.1:18083/v1` (lokalni)
- `http://remote-server:port/v1` (remote)
- `http://localhost:11434/v1` (Ollama)
- `http://localhost:1234/v1` (LM Studio)

### 3.2 Session Manager

Manages state between calls:
- Current model and endpoint
- SME embeddings for cross-session search
- Checkpoint for resuming interrupted tasks
- **Auto-recall at startup:** Queries SME for last session and presents summary to user

**Session Start Behavior:**
```
1. Load last session ID from state
2. Query SME: "last session summary"
3. Display: "Last time you worked on [topic]..."
4. Wait for user confirmation
5. Continue from checkpoint OR start fresh
```

### 3.3 Skills Loader

Modularan sistem — svaki skill je folder sa `SKILL.md` fajlom.

```
skills/
├── deep-research/      # Multi-step research protocol
├── writer/             # Prose drafting
├── rag-library/       # RAG document Q&A
├── wiki-memory/        # WIKI filesystem memory
├── web-research/      # Quick web research
└── ...
```

### 3.4 RAG System

Već postoji i radi:
- LanceDB + `intfloat/multilingual-e5-small` embedding
- CLI: `python3 ~/.kon/tools/rag_ingest.py <file>` za dodavanje dokumenata
- CLI: `python3 ~/.kon/tools/rag_search.py --query "..."` za pretragu

### 3.5 SME (Semantic Memory Engine)

**Već postoji:**
- LanceDB-backed SME za cross-session memoriju
- CLI: `mcp_call(tool="sme_recall", arguments={"query": "...", "limit": 5})`
- CLI: `sme_add("...")` posle svakog zadatka

**Session Start Auto-Recall:**
- At session start, Scribe automatically queries SME for the last session
- Displays: "Previous session was about [topic]. Status: [status]. Continue where we left off?"
- User can confirm to continue or start fresh
- This ensures seamless continuity across sessions without manual memory search

**Memory Flow:**
```
Session Start
    ↓
SME auto-recall (last session summary)
    ↓
Scribe displays: "Last time you worked on [X]..."
    ↓
User confirms or starts new topic
    ↓
During session: SME embeddings added
    ↓
Session End: SME summary stored
```

### 3.6 Rich TUI

Rich biblioteka za:
- Progress barove tokom generisanja
- Boje i stilizovanje
- Tabele za prikaz rezultata
- Panel layout

---

## 4. Faze Implementacije

### Faza 1: Core Infrastructure ✅

**Cilj:** Izolovati postojeće komponente u modularnu strukturu.

| Task | Status | Opis |
|---|---|---|
| LLM Adapter | ✅ Postoji | `OpenAI()` klijent sa llama.cpp endpoint-om |
| Config Manager | ✅ Postoji | `~/.kon/config.toml` |
| Skills Loader | ✅ Postoji | `~/.agents/skills/` |
| Basic TUI Shell | 🔲 TODO | `rich.Console` sa input/output |

**Exit Criteria Faze 1:**
- `python3 -c "from scribe.llm_adapter import LLMAdapter; print('OK')"` radi
- Može se povezati na bilo koji `llama-server` endpoint
- `scribe-llm --help` prikazuje dostupne komande

---

### Faza 2: Memory Integration ✅

**Cilj:** Povezati postojeće RAG i SME sisteme.

| Task | Status | Opis |
|---|---|---|
| RAG CLI wrapper | ✅ Postoji | `~/.kon/tools/rag_search.py` |
| RAG Ingest CLI | ✅ Postoji | `~/.kon/tools/rag_ingest.py` |
| SME recall | ✅ Postoji | MCP tool `sme_recall` |
| SME add | ✅ Postoji | Posle svakog zadatka |
| Checkpoint System | 🔲 TODO | JSON snapshot posle svakog koraka |

**Exit Criteria Faze 2:**
- `scribe-llm memory --search "tema"` vraća relevantne sesije
- `scribe-llm rag --ingest ./dokument.pdf` dodaje dokument u RAG
- `scribe checkpoint --save` čuva trenutno stanje
- **Auto-recall at session start** — new session automatically shows "Last time you worked on [X]..."

---

### Faza 3: Research & Writing Skills 🔲

**Cilj:** ImplementiratiSkills za autonomni rad.

| Task | Status | Opis |
|---|---|---|
| `deep-research` skill | 🔲 TODO | Multi-step iterativno pretraživanje |
| `writer` skill | 🔲 TODO | Drafting sa stilom i tonom |
| `book-builder` skill | 🔲 TODO | Konverzija istraživanja u poglavlja |
| `web-research` skill | 🔲 TODO | Brza Perplexity-style pretraga |

**Exit Criteria Faze 3:**
- `scribe research "tema"` pokreće autonomni research loop
- `scribe write --book "naslov"` generiše strukturu knjige
- Model ostaje u temi 10+ koraka bez gubljenja konteksta

---

### Faza 4: Poliranje TUI 🔲

**Cilj:** Finalna Rich TUI sa svim vizuelnim elementima.

| Task | Status | Opis |
|---|---|---|
| Progress barovi | 🔲 TODO | Rich `Progress()` za svaki API poziv |
| Boje i tema | 🔲 TODO | Gruvbox-dark kao default |
| Animacije | 🔲 TODO | Typing effect, spinner tokom pisanja |
| Checkpoint recovery | 🔲 TODO | Nastavak prekinutog zadatka |

**Exit Criteria Faze 4:**
- `scribe-llm run --task "duuga lista podzadataka"` radi satima bez padanja
- Posle restart, `scribe resume` nastavlja tamo gde je stao
- Drift detekcija prepoznaje kad model odstupi i restartuje sesiju

---

## 5. Distribution Model (GitHub)

### Repozitorijum Struktura

```
scribe/
├── README.md                  # Quick start, setup, usage
├── LICENSE                    # MIT
├── pyproject.toml             # Python package metadata
├── scribe/                    # Main package
│   ├── __init__.py
│   ├── llm_adapter.py         # Connect to any llama-server
│   ├── session.py             # Session & checkpoint management
│   ├── config.py              # Config loading from TOML
│   ├── skills.py              # Skills loader & registry
│   ├── memory/
│   │   ├── sme.py             # SME integration
│   │   └── rag.py             # RAG integration
│   ├── tools/
│   │   ├── web_search.py
│   │   ├── web_fetch.py
│   │   └── bash.py
│   ├── ui/
│   │   ├── console.py         # Rich Console setup
│   │   ├── progress.py        # Progress bars
│   │   └── theme.py           # Gruvbox-dark theme
│   └── skills/                # Built-in skills
│       ├── deep-research/
│       ├── writer/
│       └── wiki-memory/
├── scripts/
│   ├── install.sh             # Setup dependencies
│   ├── start-server.sh        # Example llama-server launcher
│   └── migrate-kon.sh         # Migrate from existing Kon setup
├── config/
│   └── config.example.toml    # Example configuration
└── tests/
    ├── test_llm_adapter.py
    ├── test_session.py
    └── test_rag.py
```

### GitHub-ready Features

1. **One-command install:**
   ```bash
   pip install scribe-llm
   scribe-llm init  # Wizard: set llama-server URL, model, port
   ```

2. **Migracija sa Kon-a:**
   ```bash
   scribe migrate-kon  # Importuje ~/.kon/config.toml, skills, memory
   ```

3. **Remote server support:**
   ```bash
   SCRIBE_BASE_URL=http://remote:18083 scribe-llm chat
   ```

4. **Dokumentacija:**
   - Quick start u README
   - `scribe-llm --help` za CLI reference
   - `scribe skills list` za dostupne skills
   - Wiki za advanced usage

---

## 6. Konzolne Komande

```bash
# Osnovne komande
scribe-llm chat                    # Interaktivni chat
scribe-llm chat --stream           # Streaming odgovori
scribe-llm chat --model gemma-3    # Specifičan model

# Istraživanje
scribe research "tema"         # Autonomous deep research
scribe-llm web "pitanje"          # Brza web pretraga
scribe-llm rag --search "query"    # Pretraga dokumenata
scribe-llm rag --ingest ./file.pdf # Dodaj dokument

# Pamćenje
scribe-llm memory --recall "tema"  # Pretraži prethodne sesije
scribe-llm memory --export        # Export SME baze

# Pisanje
scribe write "naslov"         # Generiši strukturu knjige
scribe draft --chapter 1       # Napiši poglavlje

# Sistem
scribe checkpoint --save       # Sačuvaj stanje
scribe checkpoint --list       # Lista svih checkpoint-ova
scribe resume <id>            # Nastavi od checkpoint-a
scribe skills --list          # Lista dostupnih skill-ova

# Konfiguracija
scribe-llm config --show          # Prikaži trenutnu konfiguraciju
scribe-llm config --set base_url  # Postavi novu vrednost
scribe-llm config --edit          # Otvori config u editoru
```

---

## 7. Konfiguracija

### `config.toml`

```toml
[scribe]
# LLM Endpoint — bilo koji llama-server, Ollama, LM Studio
base_url = "http://127.0.0.1:18083/v1"
model = "gemma-4-12B-it-Q4_K_M.gguf"  # Model name (poizvoljan string)
api_key = "not-needed"  # llama.cpp ne zahteva ključ

# System prompt
system_prompt = "You are Scribe, an autonomous research and writing agent..."

# Memorija
sme_enabled = true
rag_enabled = true

[scribe.rag]
# RAG podešavanje
embedding_model = "intfloat/multilingual-e5-small"
index_dir = "~/.scribe/rag"

[scribe.sme]
# SME podešavanje
db_path = "~/.scribe/sme"

[scribe.ui]
# TUI podešavanje
theme = "gruvbox-dark"
show_progress = true
streaming = true

[scribe.limits]
# Ograničenja
max_context_tokens = 131072
max_response_tokens = 8192
request_timeout_seconds = 600
```

### Environment Variables

```bash
SCRIBE_BASE_URL=http://remote:18083/v1  # Override config
SCRIBE_MODEL=gemma-3                    # Override model
SCRIBE_API_KEY=sk-...                   # Ako server zahteva ključ
SCRIBE_CONFIG=./config.toml            # Custom config path
```

---

## 8. Exit Criteria

### Faza 1 (Core)
- [ ] `import scribe; scribe.LLMAdapter("http://127.0.0.1:18083/v1").complete([{"role":"user","content":"Hi"}])` vraća odgovor
- [ ] `scribe-llm --help` prikazuje sve komande
- [ ] Može se povezati na remote endpoint

### Faza 2 (Memory)
- [ ] `scribe-llm memory --recall "deep learning"` vraća relevantne sesije iz SME
- [ ] `scribe-llm rag --ingest ./book.pdf` dodaje i pretraga vraća tačne rezultate
- [ ] Checkpoint se čuva u JSON fajl

### Faza 3 (Skills)
- [ ] `scribe research "transformer attention"` radi 10+ iteracija autonomno
- [ ] `scribe write "AI knjiga"` generiše strukturu sa poglavljima
- [ ] Skills se mogu dodavati bez restarta

### Faza 4 (Poliranje)
- [ ] TUI prikazuje Rich progress bar tokom generisanja
- [ ] Posle `kill -9`, `scribe resume` nastavlja zadatak
- [ ] Drift detekcija restartuje sesiju kad model odstupi

---

## 9. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| GPU OOM kad modelu treba >12GB | High | High | Strogo limitirati GPU layers (`-ngl` flag), koristiti Q4 ili Q6 kvantizaciju |
| Model drift — model "zaboravi" zadatak | Medium | Medium | Checkpoint svakih 5 minuta, SME recall na početku svake sesije |
| RAG pretraga spora na velikim dokumentima | Low | Low | Chunking na 512 tokena, limitirati rezultate |
| llama-server puca pod opterećenjem | Medium | Medium | systemd service sa auto-restart, monitoring |
| Context overflow kad se napuni 131k tokena | Medium | Low | Kompakcija, summarizacija starog konteksta |
| Skills konflikt (dva skills za istu stvar) | Low | Low | Skills registry sa priority sistemom |

---

## 10. Timeline

```
Nedelja 1-2: Faza 1 (Core Infrastructure)
  - Izolovati llm_adapter iz Kon sistema
  - Napraviti scribe CLI sa click-om
  - Integrisati Rich TUI shell
  - Test: connect na različite endpoints

Nedelja 3-4: Faza 2 (Memory)
  - Povezati SME na scribe.session
  - Wrapper za rag_search/rag_ingest
  - Checkpoint sistem (JSON snapshot)
  - Test: preživi kill -9, nastavi

Nedelja 5-6: Faza 3 (Skills)
  - Portovati deep-research iz Kon-a
  - Portovati writer skill
  - Implementirati book-builder
  - Test: autonomni research 10+ koraka

Nedelja 7-8: Faza 4 (Poliranje)
  - Rich progress barovi, animacije
  - Drift detekcija
  - Dokumentacija, README
  - GitHub release

UKUPNO: ~8 nedelja (intenzivan rad) / ~12 nedelja (parcialni rad)
```

---

## 11. Resursi

### Hardverska ograničenja

| Resurs | Limit | Napomena |
|---|---|---|
| GPU VRAM | 12 GB | RTX 3060 — strogo `-ngl 99` ili manje |
| RAM | 32 GB | Swap ako treba više za velike modele |
| Context | 131072 tokens | Maximum za Gemma 4 12B |
| Disk | ~50 GB | Za modele, RAG bazu, SME bazu |

### Softverski stack

| Komponenta | Verzija | Napomena |
|---|---|---|
| Python | 3.10+ | Koristi `uv` za package management |
| llama.cpp | latest | Build from source sa CUDA podrškom |
| LanceDB | 0.4+ | Za RAG i SME |
| Rich | 13+ | Za TUI |
| sentence-transformers | 2.2+ | Za embedding |
| systemd | (system) | Za service management |

---

## 12. Diferenciranje od Sličnih Projekata

| Feature | Scribe |相似ni projekti |
|---|---|---|
| **Universal LLM adapter** | ✅ Bilo koji llama-server | Obično hardkodiran model |
| **RAG + SME zajedno** | ✅ Obe memorije integrisane | Obično samo RAG |
| **Skills sistem** | ✅ Modularni, GitHub-ready | Fixed capability set |
| **Autonomni loops** | ✅ Self-healing, checkpoint | Jedan poziv = jedan odgovor |
| **TUI sa Rich** | ✅ Progress barovi, boje | Plain text |
| **Cross-session memory** | ✅ SME pamti sve sesije | Gubi kontekst |

---

## 13. GitHub Release Checklist

- [ ] `pyproject.toml` sa正确nim metadata
- [ ] README.md sa Quick Start ( < 5 minuta do prvog pokretanja)
- [ ] `scripts/install.sh` za dependency setup
- [ ] `scripts/start-server.sh` kao primer za llama-server
- [ ] `config/config.example.toml` sa svim opcijama
- [ ] LICENSE (MIT)
- [ ] `tests/` sa osnovnim unit testovima
- [ ] Demo video ili GIF u README

---

*Plan ažuriran: 2026-06-08*
*Baziran na postojećem Kon sistemu od @pedjaurosevic*
