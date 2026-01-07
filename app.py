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
            "https://www.googleapis.com/auth/drive"
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
            "client_x509_cert_url": CLIENT_X509_CERT_URL
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
    # Appliquer à /ciblage et /commande (comme avant)
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
            port=os.getenv("REDSHIFT_PORT", 5439)
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
                # affiche la requête complétée pour debug
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
                ws.append_row([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    str(geo_selection),
                    age_min,
                    age_max,
                    count
                ])
                print("✅ Comptage ajouté au Google Sheet.", flush=True)
            except Exception as sheet_error:
                print("❌ Erreur ajout Google Sheet :", sheet_error, flush=True)

        return jsonify({
            "status": "success ✅",
            "count": count,
            "age_min": age_min,
            "age_max": age_max,
            "geo_selection_received": geo_selection
        })

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

        # Connexion SMTP SSL Gmail
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, [r.strip() for r in receivers.split(",")], msg.as_string())
        print("✅ Email envoyé via Gmail SMTP", flush=True)
        return True
    except Exception as e:
        print("❌ Erreur envoi email :", e, flush=True)
        return False
    
def normalize_commande_payload(data: dict) -> dict:
    """
    Accepte payload legacy OU nouveau payload Paralos
    et retourne une structure normalisée
    """
    normalized = {}

    normalized["candidat"] = data.get("candidat", {})
    normalized["mandataire"] = data.get("mandataire", {})
    normalized["lp"] = data.get("lp", {})

    # --- total contacts ---
    if "comptage" in data:
        normalized["total_contacts"] = int(data["comptage"].get("total", 0))
        normalized["geo_selection"] = data["comptage"].get("geo_selection", [])
        normalized["age_min"] = data["comptage"].get("age_min")
        normalized["age_max"] = data["comptage"].get("age_max")
    elif "tarif" in data:
        normalized["total_contacts"] = int(data["tarif"].get("contacts", 0))
        normalized["geo_selection"] = data.get("geo_selection", [])
        normalized["age_min"] = None
        normalized["age_max"] = None
    else:
        normalized["total_contacts"] = 0
        normalized["geo_selection"] = []

    # --- coverage / dry run ---
    normalized["coverage"] = float(data.get("coverage", 1.0))
    normalized["dry_run"] = bool(
        data.get("dry_run") or data.get("dry-run", False)
    )

    # --- liens LP ---
    lp = normalized["lp"]
    normalized["lp_links"] = {
        "photo": lp.get("lien_photo"),
        "pf": lp.get("lien_pf") or lp.get("lien_profession_de_foi"),
        "bv": lp.get("lien_bv") or lp.get("lien_bulletin_vote"),
    }

    return normalized


@app.route("/commande", methods=["POST"])
def commande():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing body"}), 400

    payload = normalize_commande_payload(data)

    candidat = payload["candidat"]
    mandataire = payload["mandataire"]
    lp_links = payload["lp_links"]

    total_contacts = payload["total_contacts"]
    geo_selection = payload["geo_selection"]
    coverage = payload["coverage"]
    dry_run = payload["dry_run"]

    if not candidat or not mandataire:
        return jsonify({"error": "Missing candidat or mandataire"}), 400

    commande_id = str(uuid.uuid4())
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ------------------- GOOGLE SHEET -------------------
    sheet = get_google_client()
    if sheet:
        try:
            ws = sheet.worksheet(WS_COMMANDES_NAME)
            ws.append_row([
                created_at,
                commande_id,
                candidat.get("nom"), candidat.get("prenom"),
                mandataire.get("nom"), mandataire.get("prenom"),
                total_contacts,
                coverage,
                dry_run,
                str(geo_selection),
                lp_links["photo"],
                lp_links["pf"],
                lp_links["bv"],
                candidat.get("id_paralos")
            ])
            print("✅ Commande ajoutée au Google Sheet.", flush=True)
        except Exception as e:
            print("❌ Erreur Google Sheet :", e, flush=True)

    # ------------------- EMAIL -------------------
    subject = f"[Publipol] Commande {commande_id} – {candidat.get('prenom')} {candidat.get('nom')}"
    body = f"""
Nouvelle commande reçue

ID : {commande_id}
Candidat : {candidat.get('prenom')} {candidat.get('nom')}
Mandataire : {mandataire.get('prenom')} {mandataire.get('nom')}
Contacts : {total_contacts}
Coverage : {coverage}
Dry-run : {dry_run}

Zones : {geo_selection}

Liens LP:
- Photo : {lp_links['photo']}
- Profession de foi : {lp_links['pf']}
- Bulletin : {lp_links['bv']}
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
