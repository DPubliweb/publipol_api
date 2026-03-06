from flask import Flask, request, jsonify
from flask_cors import CORS
import os, uuid, psycopg2, smtplib
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)

# ------------------- VARIABLES ENV -------------------
API_KEY = os.getenv("API_KEY")

# Google service account pieces (env variables)
TYPE = os.getenv("TYPE")
PROJECT_ID = os.getenv("PROJECT_ID")
PRIVATE_KEY_ID = os.getenv("PRIVATE_KEY_ID")
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "").replace("\\n", "\n")
CLIENT_EMAIL = os.getenv("CLIENT_EMAIL")
CLIENT_ID = os.getenv("CLIENT_ID")
AUTH_URI = os.getenv("AUTH_URI")
TOKEN_URI = os.getenv("TOKEN_URI")
AUTH_PROVIDER_X509_CERT_URL = os.getenv("AUTH_PROVIDER_X509_CERT_URL")
CLIENT_X509_CERT_URL = os.getenv("CLIENT_X509_CERT_URL")

SHEET_ID = os.getenv("SHEET_ID")
WS_COMPTAGES_NAME = os.getenv("WS_COMPTAGES_NAME", "Comptages")
WS_COMMANDES_NAME = os.getenv("WS_COMMANDES_NAME", "Commandes")

# Email (Gmail SMTP)
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")  # mot de passe d'application Gmail
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")  # peut être plusieurs séparées par ','


# ------------------- GOOGLE SHEETS -------------------
def get_google_client():
    """Initialise le client gspread à la demande."""
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds_dict = {
            "type": TYPE,
            "project_id": PROJECT_ID,
            "private_key_id": PRIVATE_KEY_ID,
            "private_key": PRIVATE_KEY,
            "client_email": CLIENT_EMAIL,
            "client_id": CLIENT_ID,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "auth_provider_x509_cert_url": AUTH_PROVIDER_X509_CERT_URL,
            "client_x509_cert_url": CLIENT_X509_CERT_URL,
        }
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID)
        print("✅ Connexion Google Sheets OK", flush=True)
        return sheet
    except Exception as e:
        print("❌ Erreur connexion Google Sheets :", e, flush=True)
        return None


# ------------------- AUTH -------------------
@app.before_request
def authenticate():
    # Appliquer à /ciblage et /commande
    if request.path.startswith(("/ciblage", "/commande")):
        api_key = request.headers.get("x-api-key")
        if api_key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401


# ------------------- TEST REDSHIFT -------------------
@app.route("/test-redshift")
def test_redshift():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("REDSHIFT_DBNAME"),
            user=os.getenv("REDSHIFT_USER"),
            password=os.getenv("REDSHIFT_PASSWORD"),
            host=os.getenv("REDSHIFT_HOST"),
            port=os.getenv("REDSHIFT_PORT", 5439),
        )
        cur = conn.cursor()
        cur.execute("SELECT current_date;")
        result = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"status": "success ✅", "current_date": str(result[0])})
    except Exception as e:
        return jsonify({"status": "error ❌", "message": str(e)})


# ------------------- CIBLAGE -------------------
@app.route("/ciblage", methods=["POST"])
def ciblage():
    data = request.get_json() or {}
    geo_selection = data.get("geo_selection", [])
    age_min = int(data.get("age_min", 18))
    age_max = int(data.get("age_max", 120))

    if not isinstance(geo_selection, list) or not geo_selection:
        return jsonify({"error": "geo_selection must be a non-empty array"}), 400

    code_bdv_list, code_commune_list, code_circo_list = [], [], []
    for code in geo_selection:
        if code.startswith("BV"):
            code_bdv_list.append(code.replace("BV", ""))
        elif code.startswith("COM"):
            code_commune_list.append(code.replace("COM", ""))
        elif code.startswith("C"):
            code_circo_list.append(code.replace("C", ""))
        else:
            print(f"⚠ Code non reconnu : {code}", flush=True)

    params, where_parts = [], []
    if code_bdv_list:
        placeholders = ", ".join(["%s"] * len(code_bdv_list))
        where_parts.append(f"code_bdv IN ({placeholders})")
        params.extend(code_bdv_list)
    if code_commune_list:
        placeholders = ", ".join(["%s"] * len(code_commune_list))
        where_parts.append(f"code_commune IN ({placeholders})")
        params.extend(code_commune_list)
    if code_circo_list:
        placeholders = ", ".join(["%s"] * len(code_circo_list))
        where_parts.append(f"code_circo IN ({placeholders})")
        params.extend(code_circo_list)

    if not where_parts:
        return jsonify({"error": "Aucun identifiant géographique valide"}), 400

    where_geo = f"({' OR '.join(where_parts)})"
    params.extend([age_min, age_max])

    query = f"""
        SELECT COUNT(DISTINCT tel_mobile)
        FROM paralos_data
        WHERE {where_geo}
        AND age BETWEEN %s AND %s;
    """

    try:
        conn = psycopg2.connect(
            dbname=os.getenv("REDSHIFT_DBNAME"),
            user=os.getenv("REDSHIFT_USER"),
            password=os.getenv("REDSHIFT_PASSWORD"),
            host=os.getenv("REDSHIFT_HOST"),
            port=int(os.getenv("REDSHIFT_PORT", 5439)),
        )
        with conn:
            with conn.cursor() as cur:
                try:
                    print("SQL FINAL :", cur.mogrify(query, tuple(params)).decode(), flush=True)
                except Exception:
                    print("SQL (mogrify non disponible)", flush=True)

                cur.execute(query, tuple(params))
                result = cur.fetchone()
                count = result[0] if result else 0
                print(f"✅ Résultat du comptage : {count}", flush=True)

        # Ajouter le comptage au Google Sheet
        sheet = get_google_client()
        if sheet:
            try:
                ws = sheet.worksheet(WS_COMPTAGES_NAME)
                ws.append_row(
                    [
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        str(geo_selection),
                        age_min,
                        age_max,
                        count,
                    ]
                )
                print("✅ Comptage ajouté au Google Sheet.", flush=True)
            except Exception as sheet_error:
                print("❌ Erreur ajout Google Sheet :", sheet_error, flush=True)

        return jsonify(
            {
                "status": "success ✅",
                "count": count,
                "age_min": age_min,
                "age_max": age_max,
                "geo_selection_received": geo_selection,
            }
        )

    except Exception as e:
        print("❌ Erreur Redshift :", str(e), flush=True)
        return jsonify({"status": "error ❌", "message": str(e)}), 500


# ------------------- COMMANDE -------------------
def send_email(subject: str, body: str, sender: str, password: str, receivers: str):
    """Envoie un email via Gmail SMTP SSL. `receivers` peut être une string avec virgules."""
    try:
        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = receivers
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, [r.strip() for r in receivers.split(",")], msg.as_string())

        print("✅ Email envoyé via Gmail SMTP", flush=True)
        return True
    except Exception as e:
        print("❌ Erreur envoi email :", e, flush=True)
        return False


def _pick(d: dict, *keys, default=""):
    """Retourne la première valeur non vide trouvée parmi keys dans d."""
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return default


def normalize_commande_payload(data: dict) -> dict:
    """
    Normalise le payload selon les champs EXACTS de ton screenshot:
      - candidat: nom, prenom, id_paralos, adresse, cp, ville, tel1, tel2, email
      - mandataire: nom, prenom, adresse, cp, ville, tel1, tel2, email
      - lp: active, type_lp, lien_photo, lien_profession_de_foi, lien_bulletin_vote
      - tarif: contacts, sms, lp, montant, opt_out
      - age_filter: min, max, include_unknown_age
      - geo_selection
      - coverage
      - dry-run
    Et garde une compatibilité minimale avec quelques alias legacy (telephone/tel/phone, lien_pf/lien_bv, etc.)
    """
    normalized = {}

    # ------------------- CANDIDAT -------------------
    candidat_in = data.get("candidat", {}) or {}
    candidat = {
        "nom": _pick(candidat_in, "nom", default=""),
        "prenom": _pick(candidat_in, "prenom", default=""),
        "id_paralos": _pick(candidat_in, "id_paralos", "id", default=""),
        "adresse": _pick(candidat_in, "adresse", "address", default=""),
        "cp": _pick(candidat_in, "cp", "postal_code", "code_postal", default=""),
        "ville": _pick(candidat_in, "ville", "city", default=""),
        "tel1": _pick(candidat_in, "tel1", "telephone", "tel", "phone", default=""),
        "tel2": _pick(candidat_in, "tel2", "telephone_2", "tel2", default=""),
        "email": _pick(candidat_in, "email", default=""),
    }
    normalized["candidat"] = candidat

    # ------------------- MANDATAIRE -------------------
    mandataire_in = data.get("mandataire", {}) or {}
    mandataire = {
        "nom": _pick(mandataire_in, "nom", default=""),
        "prenom": _pick(mandataire_in, "prenom", default=""),
        "adresse": _pick(mandataire_in, "adresse", "address", default=""),
        "cp": _pick(mandataire_in, "cp", "postal_code", "code_postal", default=""),
        "ville": _pick(mandataire_in, "ville", "city", default=""),
        "tel1": _pick(mandataire_in, "tel1", "telephone", "tel", "phone", default=""),
        "tel2": _pick(mandataire_in, "tel2", "telephone_2", "tel2", default=""),
        "email": _pick(mandataire_in, "email", default=""),
    }
    normalized["mandataire"] = mandataire

    # ------------------- LP -------------------
    lp_in = data.get("lp", {}) or {}
    lp = {
        "active": bool(lp_in.get("active", False)),
        "type_lp": _pick(lp_in, "type_lp", default="standard"),
        "lien_photo": _pick(lp_in, "lien_photo", default=""),
        "lien_profession_de_foi": _pick(lp_in, "lien_profession_de_foi", "lien_pf", default=""),
        "lien_bulletin_vote": _pick(lp_in, "lien_bulletin_vote", "lien_bv", default=""),
    }
    normalized["lp"] = lp

    # ------------------- TARIF -------------------
    tarif_in = data.get("tarif", {}) or {}
    tarif = {
        "contacts": int(tarif_in.get("contacts", 0) or 0),
        "sms": float(tarif_in.get("sms", 1.0) or 1.0),      # dans ton screenshot: coveragePercentage/100
        "lp": bool(tarif_in.get("lp", lp.get("active", False))),
        "montant": tarif_in.get("montant", ""),
        "opt_out": bool(tarif_in.get("opt_out", False)),
    }
    normalized["tarif"] = tarif

    # ------------------- AGE FILTER -------------------
    age_in = data.get("age_filter", {}) or {}
    age_filter = {
        "min": age_in.get("min", None),
        "max": age_in.get("max", None),
        "include_unknown_age": bool(age_in.get("include_unknown_age", False)),
    }
    normalized["age_filter"] = age_filter

    # ------------------- AUTRES -------------------
    geo_selection = data.get("geo_selection", []) or []
    if not isinstance(geo_selection, list):
        geo_selection = [geo_selection]
    normalized["geo_selection"] = geo_selection

    # coverage: dans ton screenshot c’est le même ratio que tarif.sms
    # on privilégie coverage si présent, sinon tarif.sms
    try:
        normalized["coverage"] = float(data.get("coverage", tarif.get("sms", 1.0)))
    except Exception:
        normalized["coverage"] = float(tarif.get("sms", 1.0))

    # dry-run (clé avec tiret)
    normalized["dry_run"] = bool(data.get("dry_run") or data.get("dry-run", False))

    # total_contacts (pour compat: réutilise tarif.contacts)
    normalized["total_contacts"] = int(tarif.get("contacts", 0))

    return normalized


@app.route("/commande", methods=["POST"])
def commande():

    data = request.get_json() or {}
    payload = normalize_commande_payload(data)

    candidat = payload.get("candidat", {})
    mandataire = payload.get("mandataire", {})
    lp = payload.get("lp", {})
    tarif = payload.get("tarif", {})
    age_filter = payload.get("age_filter", {})

    geo_selection = payload.get("geo_selection", [])
    coverage = payload.get("coverage", "")
    dry_run = payload.get("dry_run", False)
    total_contacts = payload.get("total_contacts", 0)

    commande_id = str(uuid.uuid4())
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ------------------- GOOGLE SHEETS -------------------
    sheet = get_google_client()

    if sheet:

        # ------------------- SHEET COMMANDES -------------------
        try:

            ws = sheet.worksheet(WS_COMMANDES_NAME)

            row_data = [[
                created_at,
                commande_id,

                # candidat
                candidat.get("nom", ""),
                candidat.get("prenom", ""),
                candidat.get("id_paralos", ""),
                candidat.get("adresse", ""),
                candidat.get("cp", ""),
                candidat.get("ville", ""),
                candidat.get("tel1", ""),
                candidat.get("tel2", ""),
                candidat.get("email", ""),

                # mandataire
                mandataire.get("nom", ""),
                mandataire.get("prenom", ""),
                mandataire.get("adresse", ""),
                mandataire.get("cp", ""),
                mandataire.get("ville", ""),
                mandataire.get("tel1", ""),
                mandataire.get("tel2", ""),
                mandataire.get("email", ""),

                # lp
                lp.get("active", False),
                lp.get("type_lp", "standard"),
                lp.get("lien_photo", ""),
                lp.get("lien_profession_de_foi", ""),
                lp.get("lien_bulletin_vote", ""),

                # tarif
                total_contacts,
                tarif.get("sms", ""),
                tarif.get("lp", ""),
                tarif.get("montant", ""),
                tarif.get("opt_out", ""),

                # age filter
                age_filter.get("min", ""),
                age_filter.get("max", ""),
                age_filter.get("include_unknown_age", ""),

                # autres
                str(geo_selection),
                coverage,
                dry_run
            ]]

            values = ws.col_values(1)
            next_row = len(values) + 1

            ws.update(f"A{next_row}", row_data)

            print("✅ Commande ajoutée au sheet Commandes", flush=True)

        except Exception as e:
            print("❌ Erreur sheet Commandes :", e, flush=True)

        #  ------------------- SHEET PUBLIPOL -------------------
        try:

            ws_publipol = sheet.worksheet("Publipol")

            opt_out_value = "OUI" if tarif.get("opt_out", False) else "NON"

            publipol_row = [[
                datetime.now().strftime("%d/%m/%Y"),

                f"{candidat.get('prenom','')} {candidat.get('nom','')}",
                candidat.get("tel1", ""),
                candidat.get("email", ""),

                f"{mandataire.get('prenom','')} {mandataire.get('nom','')}",
                mandataire.get("tel1", ""),
                mandataire.get("email", ""),

                "Devis à FAIRE",
                opt_out_value,

                candidat.get("id_paralos", ""),
                total_contacts,
                "Oui",
                tarif.get("montant", ""),
                str(geo_selection)
            ]]

            values = ws_publipol.col_values(1)
            next_row = len(values) + 1

            ws_publipol.update(f"A{next_row}", publipol_row)

            print("✅ Commande ajoutée au sheet Publipol", flush=True)

        except Exception as e:
            print("❌ Erreur sheet Publipol :", e, flush=True)

    # ------------------- EMAIL -------------------
    subject = f"[Publipol] Commande {commande_id}"

    body = f"""
Nouvelle commande reçue

ID : {commande_id}
Créée le : {created_at}

CANDIDAT
Nom : {candidat.get('prenom','')} {candidat.get('nom','')}
id_paralos : {candidat.get('id_paralos','')}
Adresse : {candidat.get('adresse','')}, {candidat.get('cp','')} {candidat.get('ville','')}
Tel1 : {candidat.get('tel1','')}
Tel2 : {candidat.get('tel2','')}
Email : {candidat.get('email','')}

MANDATAIRE
Nom : {mandataire.get('prenom','')} {mandataire.get('nom','')}
Adresse : {mandataire.get('adresse','')}, {mandataire.get('cp','')} {mandataire.get('ville','')}
Tel1 : {mandataire.get('tel1','')}
Tel2 : {mandataire.get('tel2','')}
Email : {mandataire.get('email','')}

LP
Active : {lp.get('active', False)}
Type : {lp.get('type_lp','standard')}

TARIF
Contacts : {total_contacts}
SMS : {tarif.get('sms','')}
Montant : {tarif.get('montant','')}
Opt-out : {tarif.get('opt_out','')}

Zones : {geo_selection}
Coverage : {coverage}
Dry-run : {dry_run}
"""

    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER:
        send_email(subject, body, EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER)

    return jsonify({
        "commande_id": commande_id,
        "status": "ok",
        "normalized": payload
    })


# ------------------- MAIN -------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8002))
    app.run(host="0.0.0.0", port=port, debug=True)
