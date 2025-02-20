# nova-infoblox-discovery-scheduler

Tento repozitář obsahuje dva Python skripty pro automatizaci Infoblox network discovery:

1. **Scheduled Discovery Script** – aktualizuje tzv. *scheduled discovery task* sítěmi, které mají extensible atribut `Network_Discovery=True`, a (volitelně) spouští discovery dle naplánovaného režimu.  
2. **Current Discovery Script** – okamžitě aktualizuje a restartuje *current discovery task* se sítěmi, které mají atribut `Network_Discovery=True`. Tento skript také umožňuje filtrovat sítě podle specifikovaného network view (přes argument `--network_view` nebo `-nv`). Pokud je discovery již spuštěno (nebo pozastaveno či ve stavu END_PENDING), skript vyzve uživatele (nebo pokud je použito `--force`, automaticky) k úplnému ukončení discovery. Po úspěšném ukončení discovery je task aktualizován s novými sítěmi a znovu spuštěn.

Oba skripty zapisují veškeré události a chyby do souboru `discovery.log` a každá logovací zpráva je předponována:

- `SCHEDULED_DISCOVERY_SCRIPT` – pro scheduled discovery skript.
- `CURRENT_DISCOVERY_SCRIPT` – pro current discovery skript.

---

## Požadavky

- **Python 3.6+** (doporučujeme verzi 3.9 či novější)
- Knihovny uvedené v souboru `requirements.txt` (např. `requests`, `PyYAML`)
- Přístup k Infobloxu přes WAPI (Web API)

---

## Instalace

1. **Naklonujte repozitář:**

    ```bash
    git clone https://github.com/AlteproSolutions/nova-infoblox-discovery-scheduler.git
    cd nova-infoblox-discovery-scheduler
    ```

2. **Vytvořte a aktivujte virtuální prostředí:**

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3. **Nainstalujte požadované balíčky:**

    ```bash
    pip install -r requirements.txt
    ```

---

## Konfigurace

V kořenovém adresáři repozitáře je soubor `config.yaml`, který musí obsahovat následující parametry:

```yaml
INFOBLOX_API_URL: "https://10.40.0.46"         # Adresa Infoblox WAPI (např. https://IP_adresa nebo https://hostname)
INFOBLOX_API_USERNAME: "admin"                 # Uživatelské jméno s příslušnými právy
INFOBLOX_API_PASSWORD: "infoblox"              # Heslo k danému účtu
SCHEDULED_DISCOVERY_NETWORK_VIEW: "default"    # Infoblox network view (např. "default" nebo "GLOBAL")
SCHEDULED_DISCOVERY_DEFAULT_NETWORK: "192.168.0.0/24"  # Volitelná fallback síť – platná CIDR; použitá, pokud nejsou nalezeny žádné sítě
```

Vytvořte si kopii ze souboru config_template.yaml (pokud je k dispozici):

```bash
cp config_template.yaml config.yaml
nano config.yaml
```

Upravte hodnoty podle vašeho prostředí.

## Použití skriptů

### Scheduled Discovery Script

```Scheduled Discovery Script``` (scheduled_discovery.py) provádí tyto kroky:

- Načte konfiguraci z config.yaml.
- Vyhledá všechny network objekty, které mají Network_Discovery=True.
- Filtrováním podle hodnoty SCHEDULED_DISCOVERY_NETWORK_VIEW (definované v config) vybere odpovídající sítě.
- Pokud nejsou nalezeny žádné sítě odpovídající zvolenému view, skript se pokusí najít fallback síť (pokud je definována).
- Aktualizuje scheduled discovery task v Infobloxu těmito sítěmi.
- (Volitelně) může být skript použit pro automatické plánování přes cron.
- Logování probíhá do discovery.log s předponou SCHEDULED_DISCOVERY_SCRIPT.
- Ruční spuštění:

    ```bash
    python3 scheduled_discovery.py
    ```

### Current Discovery Script

```Current Discovery Script``` (current_discovery.py) provádí následující kroky:

- Načte konfiguraci z config.yaml.
- Přijímá povinný argument --network_view (nebo -nv), který určuje, které sítě mají být použity (např. "default" nebo "GLOBAL").
- Vyhledá všechny network objekty s Network_Discovery=True a filtruje je podle zadaného view.
- Zkontroluje stav current discovery tasku (kde discovery_task_oid == "current"). Pokud je stav RUNNING, PAUSED nebo END_PENDING, skript:
- Pokud není použit argument --force, vyzve uživatele, zda chce discovery ukončit.
- Pokud uživatel potvrdí (nebo pokud je použit --force), skript odešle příkaz END k úplnému ukončení discovery a čeká, dokud se stav nezmění (polling).
- Poté aktualizuje current discovery task s novými síťovými referencemi.
- Nakonec odešle příkaz START k spuštění nové discovery a ověří, zda stav přešel na RUNNING.
- Logování probíhá do discovery.log s předponou CURRENT_DISCOVERY_SCRIPT.

- Ruční spuštění:

```bash
python3 current_discovery.py -nv GLOBAL
```

Volitelný argument:

--force (nebo -f): Automaticky ukončí discovery bez interaktivního potvrzení, což je vhodné pro cron joby.
Příklad spuštění s vynucením:

```bash
python3 current_discovery.py -nv GLOBAL --force
```

## Automatické spuštění pomocí CRON

```Scheduled Discovery Script```

Otevřete crontab:

```bash
crontab -e
```

Přidejte řádek pro spuštění (např. každý den ve 03:00):

```bash
0 3 * * * cd /cesta/k/nova-infoblox-discovery-scheduler && /cesta/k/nova-infoblox-discovery-scheduler/.venv/bin/python scheduled_discovery.py
```

Nahraďte /cesta/k/nova-infoblox-discovery-scheduler absolutní cestou k repozitáři a /cesta/k/nova-infoblox-discovery-scheduler/.venv/bin/python plnou cestou k Python interpreteru.

```Current Discovery Script```

Otevřete crontab:

```bash
crontab -e
```

Přidejte řádek pro automatické spuštění s volbou --force:

```bash

0 4 * * * cd /cesta/k/nova-infoblox-discovery-scheduler && /cesta/k/nova-infoblox-discovery-scheduler/.venv/bin/python current_discovery.py -nv GLOBAL --force
```

## Logování

Všechny důležité události (včetně chyb) se zapisují do souboru discovery.log. Každý logovací záznam obsahuje:

- Časový záznam
- Úroveň (INFO, ERROR, atd.)
- Text zprávy (včetně případné traceback informace)

Příklady, jak zobrazit log:

```bash
cat discovery.log
```

nebo

```bash
tail -f discovery.log
```

pro kontinuální sledování.

## Chování skriptů v různých scénářích

```Scheduled Discovery Script```

### Standardní provoz:

Skript načte konfiguraci a vyhledá všechny network objekty s Network_Discovery=True. Filtruje objekty podle hodnoty SCHEDULED_DISCOVERY_NETWORK_VIEW definované v configu.
Pokud nejsou nalezeny žádné sítě odpovídající zvolenému view, skript se pokusí získat fallback síť (pokud je definována).
Poté aktualizuje scheduled discovery task s vybranými sítěmi a loguje úspěšný update.

### Chybové scénáře:

Pokud není nalezen scheduled discovery task nebo pokud aktualizace selže, skript zapíše chybu do logu a informuje uživatele, aby zkontroloval soubor discovery.log.

```Current Discovery Script```

### Standardní provoz:

Skript načte current discovery task a zkontroluje jeho stav. Pokud je stav RUNNING, PAUSED nebo END_PENDING, skript (pokud není použit --force) vyzve uživatele, zda chce ukončit discovery.
Po potvrzení (nebo pokud je --force použit) skript odešle příkaz END a čeká, dokud se discovery plně neukončí.
Následně aktualizuje current discovery task s novými síťovými referencemi a odešle příkaz START pro spuštění nové discovery.
Po několika sekundách ověří, že stav je RUNNING.

### Chybové scénáře:

Pokud discovery nelze ukončit (např. zůstává ve stavu END_PENDING), skript vyprší timeout a zapíše chybu do logu.
Pokud během startu nové discovery dojde k chybě, skript vypíše zprávu a informuje uživatele, aby zkontroloval discovery.log.
Použití --force:
Pokud je skript spuštěn s volbou --force, nebude vyžadovat interaktivní potvrzení a automaticky ukončí discovery, což je vhodné pro automatické spuštění (cron).

## Kontakt / Podpora

Pokud narazíte na problémy, kontaktujte <support@altepro.cz>