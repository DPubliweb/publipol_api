from flask import Flask, request, jsonify
from flask_cors import CORS
import os, uuid, psycopg2
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ------------------- VARIABLES ENV -------------------
API_KEY = os.getenv("API_KEY")

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

# ------------------- GOOGLE SHEETS -------------------
def get_google_client():
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
        return client.open_by_key(SHEET_ID)
    except Exception as e:
        print("❌ Erreur connexion Google Sheets :", e, flush=True)
        return None

# ------------------- AUTH -------------------
@app.before_request
def authenticate():
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
        return jsonify({"status": "success ✅", "current_date": result[0]})
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
                print("SQL FINAL :", cur.mogrify(query, tuple(params)).decode(), flush=True)
                cur.execute(query, tuple(params))
                result = cur.fetchone()
                count = result[0] if result else 0
                print(f"✅ Résultat du comptage : {count}", flush=True)

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
@app.route("/commande", methods=["POST"])
def commande():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing body"}), 400

    # Vérifie la structure
    for key in ["candidat", "mandataire", "lp", "comptage"]:
        if key not in data:
            return jsonify({"error": f"Missing section: {key}"}), 400

    candidat = data["candidat"]
    mandataire = data["mandataire"]
    lp = data["lp"]
    comptage = data["comptage"]

    dry_run = bool(data.get("dry_run", False))
    coverage = float(data.get("coverage", 1.0))
    if not (0 <= coverage <= 1):
        return jsonify({"error": "coverage doit être entre 0 et 1"}), 400

    required_candidat = ["nom", "prenom", "id_paralos", "adresse", "cp", "ville", "tel1", "email"]
    required_mandataire = ["nom", "prenom", "adresse", "cp", "ville", "tel1", "email"]
    required_lp = ["lien_photo", "lien_pf", "lien_bv"]
    required_comptage = ["total", "geo_selection", "age_min", "age_max"]

    for section, fields in {
        "candidat": required_candidat,
        "mandataire": required_mandataire,
        "lp": required_lp,
        "comptage": required_comptage
    }.items():
        for f in fields:
            if f not in data[section]:
                return jsonify({"error": f"Missing field {section}.{f}"}), 400

    total_contacts = int(comptage["total"])
    commande_id = str(uuid.uuid4())
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 🔹 Écriture dans le Google Sheet
    sheet = get_google_client()
    if sheet:
        try:
            ws = sheet.worksheet(WS_COMMANDES_NAME)
            ws.append_row([
                created_at,
                commande_id,
                candidat["nom"], candidat["prenom"],
                mandataire["nom"], mandataire["prenom"],
                total_contacts,
                coverage,
                dry_run,
                str(comptage["geo_selection"]),
                comptage["age_min"], comptage["age_max"],
                lp["lien_photo"], lp["lien_pf"], lp["lien_bv"]
            ])
            print("✅ Commande ajoutée au Google Sheet.", flush=True)
        except Exception as sheet_error:
            print("❌ Erreur ajout commande Sheet:", sheet_error, flush=True)

    return jsonify({
        "commande_id": commande_id,
        "statut": "reçue",
        "dry_run": dry_run,
        "coverage": coverage,
        "details": {
            "candidat": candidat,
            "mandataire": mandataire,
            "lp": lp,
            "comptage": comptage
        }
    })

# ------------------- MAIN -------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8002))
    app.run(host="0.0.0.0", port=port, debug=True)
