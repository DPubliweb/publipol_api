from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import uuid
import psycopg2
import json
import gspread
from google.oauth2.service_account import Credentials

# -----------------------------
# 🔐 Variables d’environnement
# -----------------------------
API_KEY = os.getenv("API_KEY")
REDSHIFT_DBNAME = os.getenv("REDSHIFT_DBNAME")
REDSHIFT_USER = os.getenv("REDSHIFT_USER")
REDSHIFT_PASSWORD = os.getenv("REDSHIFT_PASSWORD")
REDSHIFT_HOST = os.getenv("REDSHIFT_HOST")
REDSHIFT_PORT = int(os.getenv("REDSHIFT_PORT", 5439))
SHEET_ID = os.getenv("SHEET_ID")
WS_COMPTAGES_NAME = os.getenv("WS_COMPTAGES_NAME", "Comptages")
WS_COMMANDES_NAME = os.getenv("WS_COMMANDES_NAME", "Commandes")

# -----------------------------
# 🚀 Initialisation Flask
# -----------------------------
app = Flask(__name__)
CORS(app)

# -----------------------------
# 🔧 Connexion Google Sheets
# -----------------------------
def init_gsheet():
    try:
        creds_dict = {
            "type": os.getenv("GS_TYPE"),
            "project_id": os.getenv("GS_PROJECT_ID"),
            "private_key_id": os.getenv("GS_PRIVATE_KEY_ID"),
            "private_key": os.getenv("GS_PRIVATE_KEY").replace("\\n", "\n"),
            "client_email": os.getenv("GS_CLIENT_EMAIL"),
            "client_id": os.getenv("GS_CLIENT_ID"),
            "auth_uri": os.getenv("GS_AUTH_URI"),
            "token_uri": os.getenv("GS_TOKEN_URI"),
            "auth_provider_x509_cert_url": os.getenv("GS_AUTH_PROVIDER_X509_CERT_URL"),
            "client_x509_cert_url": os.getenv("GS_CLIENT_X509_CERT_URL"),
        }

        creds = Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gs_client = gspread.authorize(creds)
        sheet = gs_client.open_by_key(SHEET_ID)

        ws_comptages = sheet.worksheet(WS_COMPTAGES_NAME)
        ws_commandes = sheet.worksheet(WS_COMMANDES_NAME)

        print("✅ Connexion Google Sheets établie")
        return ws_comptages, ws_commandes
    except Exception as e:
        print("❌ Erreur Google Sheets:", e)
        return None, None


ws_comptages, ws_commandes = init_gsheet()

def log_to_sheet(worksheet, row_data):
    """Ajoute une ligne dans un onglet Google Sheet."""
    if worksheet is None:
        print("⚠️ Google Sheet non initialisé — ligne non écrite.")
        return
    try:
        worksheet.append_row(row_data, value_input_option="USER_ENTERED")
        print("✅ Log ajouté dans Google Sheet")
    except Exception as e:
        print("❌ Erreur lors de l’écriture dans Google Sheet:", e)

# -----------------------------
# 🔑 Middleware Authentification
# -----------------------------
@app.before_request
def authenticate():
    if request.path.startswith("/ciblage") or request.path.startswith("/commande"):
        api_key = request.headers.get("x-api-key")
        if api_key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401

# -----------------------------
# 🧪 Test Redshift
# -----------------------------
@app.route("/test-redshift")
def test_redshift():
    try:
        conn = psycopg2.connect(
            dbname=REDSHIFT_DBNAME,
            user=REDSHIFT_USER,
            password=REDSHIFT_PASSWORD,
            host=REDSHIFT_HOST,
            port=REDSHIFT_PORT,
        )
        cur = conn.cursor()
        cur.execute("SELECT current_date;")
        result = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"status": "success ✅", "current_date": result[0]})
    except Exception as e:
        return jsonify({"status": "error ❌", "message": str(e)})

# -----------------------------
# 📍 Route CIBLAGE
# -----------------------------
@app.route("/ciblage", methods=["POST"])
def ciblage():
    data = request.get_json() or {}

    geo_selection = data.get("geo_selection", [])
    age_min = int(data.get("age_min", 18))
    age_max = int(data.get("age_max", 120))

    if not isinstance(geo_selection, list) or len(geo_selection) == 0:
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
            print(f"⚠ Code non reconnu: {code}")

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
        return jsonify({"error": "Aucun identifiant géographique valide dans geo_selection"}), 400

    where_geo = " OR ".join(where_parts)
    where_geo = f"({where_geo})"
    params.extend([age_min, age_max])

    query = f"""
        SELECT COUNT(DISTINCT tel_mobile)
        FROM paralos_data
        WHERE {where_geo}
        AND age BETWEEN %s AND %s;
    """

    print("DEBUG SQL:", query)

    try:
        conn = psycopg2.connect(
            dbname=REDSHIFT_DBNAME,
            user=REDSHIFT_USER,
            password=REDSHIFT_PASSWORD,
            host=REDSHIFT_HOST,
            port=REDSHIFT_PORT,
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                result = cur.fetchone()
                count = result[0] if result else 0

        # 🧾 Log dans Google Sheet
        log_to_sheet(
            ws_comptages,
            [
                str(uuid.uuid4()),
                request.remote_addr,
                json.dumps(geo_selection),
                age_min,
                age_max,
                count,
            ],
        )

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
        print("ERROR executing ciblage query:", str(e))
        return jsonify({"status": "error ❌", "message": str(e)}), 500

# -----------------------------
# 🧾 Route COMMANDE
# -----------------------------
@app.route("/commande", methods=["POST"])
def commande():
    data = request.get_json()

    if (
        "candidat" not in data
        or "mandataire" not in data
        or "lp" not in data
        or "comptage" not in data
    ):
        return (
            jsonify(
                {
                    "error": "Structure invalide. Format attendu: candidat{}, mandataire{}, lp{}, comptage{}"
                }
            ),
            400,
        )

    candidat = data["candidat"]
    mandataire = data["mandataire"]
    lp = data["lp"]
    comptage = data["comptage"]

    dry_run = bool(data.get("dry_run", False))
    coverage = float(data.get("coverage", 1.0))
    if not (0 <= coverage <= 1):
        return jsonify({"error": "coverage doit être compris entre 0 et 1"}), 400

    required_candidat = ["nom", "prenom", "id_paralos", "adresse", "cp", "ville", "tel1", "email"]
    required_mandataire = ["nom", "prenom", "adresse", "cp", "ville", "tel1", "email"]
    required_lp = ["lien_photo", "lien_pf", "lien_bv"]
    required_comptage = ["total", "geo_selection", "age_min", "age_max"]

    for field in required_candidat:
        if field not in candidat:
            return jsonify({"error": f"Missing champ candidat.{field}"}), 400

    for field in required_mandataire:
        if field not in mandataire:
            return jsonify({"error": f"Missing champ mandataire.{field}"}), 400

    for field in required_lp:
        if field not in lp:
            return jsonify({"error": f"Missing champ lp.{field}"}), 400

    for field in required_comptage:
        if field not in comptage:
            return jsonify({"error": f"Missing champ comptage.{field}"}), 400

    total_contacts = int(comptage["total"])
    if total_contacts <= 0:
        return jsonify({"error": "comptage.total doit être supérieur à 0"}), 400

    commande_id = str(uuid.uuid4())

    # 🧾 Log Google Sheet
    log_to_sheet(
        ws_commandes,
        [
            commande_id,
            candidat["nom"],
            candidat["prenom"],
            mandataire["nom"],
            mandataire["prenom"],
            dry_run,
            coverage,
            total_contacts,
            json.dumps(comptage),
        ],
    )

    return jsonify(
        {
            "commande_id": commande_id,
            "statut": "reçue",
            "dry_run": dry_run,
            "coverage": coverage,
            "total_contacts": total_contacts,
            "details": {
                "candidat": {
                    "nom": candidat["nom"],
                    "prenom": candidat["prenom"],
                    "id_paralos": candidat["id_paralos"],
                },
                "mandataire": {
                    "nom": mandataire["nom"],
                    "prenom": mandataire["prenom"],
                },
                "lp": lp,
                "comptage": comptage,
            },
        }
    )

# -----------------------------
# 🚀 Démarrage
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8002))
    app.run(host="0.0.0.0", port=port, debug=True)
