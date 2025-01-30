# nova-infoblox-discovery-scheduler

Tento repozitář obsahuje Python skript pro automatizované plánování (scheduled discovery) v prostředí Infoblox.

Skript:

1. Načte konfiguraci z `config.yaml` (URL a přihlašovací údaje k Infobloxu).
2. Vyhledá všechny síťové objekty, které mají extensible atribut `Net_Discovery=True`.
3. Aktualizuje tzv. **scheduled discovery task** v Infobloxu těmito sítěmi.
4. Volitelně může spustit plánované discovery a zkontrolovat jeho stav.
5. Zapisuje průběh a chyby do souboru `discovery.log`.

## Požadavky

- Python 3.6+ (doporučujeme verzi 3.9 či novější)
- Knihovny uvedené v `requirements.txt` (např. `requests`, `PyYAML`, atd.)
- Přístup k Infobloxu přes WAPI (webové API)

## Instalace

1. Naklonujte (nebo stáhněte) tento repozitář:

    ```bash
    git clone https://github.com/uzivatel/nova-infoblox-discovery-scheduler.git
    cd nova-infoblox-discovery-scheduler
    ```

2. (Doporučeno) Vytvořte a aktivujte virtuální prostředí:

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3. Nainstalujte požadované balíčky:

    ```bash
    pip install -r requirements.txt
    ```

## Konfigurace

V kořenovém adresáři je soubor config.yaml, který musí obsahovat následující parametry:

```yaml
INFOBLOX_API_URL: "https://10.40.0.46" #adresa Infoblox WAPI (obvykle ve tvaru https://IP_adresa nebo <https://hostname>)
INFOBLOX_API_USERNAME: "admin" #uživatelské jméno s právy pro správu
INFOBLOX_API_PASSWORD: "infoblox" #heslo k danému účtu
```

Vytvorte si kopii ze souboru config_template.yaml a doplnte:

```bash
cp config_template.yaml config.yaml
nano config.yaml
```

## Ruční spuštění

Pokud máte vše nainstalováno, můžete skript scheduler.py spustit ručně:

```bash
python3 scheduler.py
```

1. Skript si načte konfiguraci z config.yaml.
2. Najde scheduled discovery task a sítě s Net_Discovery=True.
3. Provede aktualizaci scheduled discovery.
4. Do souboru discovery.log zapíše průběh a případné chyby.

## Automaticke spuštění pomocí CRON

Pro pravidelné (např. denní) spouštění lze využít systém cron:

1. Otevřete crontab:

    ```bash
    crontab -e
    ```

2. Přidejte řádek definující, kdy a jak spouštět skript. Např. pro spuštění každý den ve 03:00:

    ```bash
    0 3 * * * /cesta/k/python /cesta/k/repozitari/nova-infoblox-discovery-scheduler/scheduler.py
    ```

    /cesta/k/python nahraďte plnou cestou k Pythonu (např. /usr/bin/python3 nebo /home/uzivatel/nova-infoblox-discovery-scheduler/.venv/bin/python).

    /cesta/k/repozitari/... nahraďte absolutní cestou, kde je umístěn skript scheduler.py.

3. Uložte změny a cron zajistí pravidelný běh skriptu. Pokud používáte virtuální prostředí, je vhodné uvést cestu ke skriptu včetně aktivovaného venv, např.:

    ```bash
    0 3 * * * cd /home/uzivatel/nova-infoblox-discovery-scheduler && /home/uzivatel/nova-infoblox-discovery-scheduler/.venv/bin/python scheduler.py
    ```

Tím docílíte, že se spustí v kontextu virtuálního prostředí.

## Logovaní

Všechny důležité události, včetně chyb, se zapisují do souboru discovery.log. Formát logu obsahuje:

- Časový záznam
- Úroveň (INFO, ERROR, apod.)
- Text zprávy a případnou traceback

### Kontrola logu

bash

```bash
cat discovery.log
```

nebo

```bash
tail -f discovery.log
```

pro kontinuální sledování.
