from flask import Flask, request, jsonify
from flask_cors import CORS
import os, uuid, psycopg2
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

app = Flask(__name__)
CORS(app)

API_KEY = os.getenv("API_KEY")

# ---------------- GOOGLE SHEETS CONFIGURATION (retardée) ---------------- #
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SERVICE_ACCOUNT_INFO = {
    "type": os.getenv("TYPE"),
    "project_id": os.getenv("PROJECT_ID"),
    "private_key_id": os.getenv("PRIVATE_KEY_ID"),
    "private_key": os.getenv("PRIVATE_KEY", "").replace("\\n", "\n"),
    "client_email": os.getenv("CLIENT_EMAIL"),
    "client_id": os.getenv("CLIENT_ID"),
    "auth_uri": os.getenv("AUTH_URI"),
    "token_uri": os.getenv("TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("AUTH_PROVIDER_X509_CERT_URL"),
}
SHEET_ID = os.getenv("SHEET_ID")
WS_COMPTAGES_NAME = os.getenv("WS_COMPTAGES_NAME", "Comptages")
WS_COMMANDES_NAME = os.getenv("WS_COMMANDES_NAME", "Commandes")

def get_sheet():
    """Crée une connexion Google Sheets à la demande"""
    try:
        creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
        gclient = gspread.authorize(creds)
        sheet = gclient.open_by_key(SHEET_ID)
        return sheet
    except Exception as e:
        print("❌ Erreur connexion Google Sheets :", e, flush=True)
        return None
# ------------------------------------------------------------------------- #


# ---------------- AUTHENTIFICATION ---------------- #
@app.before_request
def authenticate():
    if request.path.startswith(("/ciblage", "/commande")):
        api_key = request.headers.get("x-api-key")
        if api_key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401


# ---------------- TEST REDSHIFT ---------------- #
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
        return jsonify({"status": "success ✅", "current_date": result[0]})
    except Exception as e:
        return jsonify({"status": "error ❌", "message": str(e)})


# ---------------- ROUTE CIBLAGE ---------------- #
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
        return jsonify({"error": "Aucun identifiant géographique valide dans geo_selection"}), 400

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

        # --- Ajout à Google Sheets (connexion à la demande) ---
        sheet = get_sheet()
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
                print("✅ Comptage ajouté à Google Sheet avec succès.", flush=True)
            except Exception as sheet_error:
                print("❌ Erreur écriture Google Sheet :", sheet_error, flush=True)
        else:
            print("⚠ Google Sheet non disponible.", flush=True)
        # ------------------------------------------------------

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
        print("ERROR Redshift :", str(e), flush=True)
        return jsonify({"status": "error ❌", "message": str(e)}), 500


# ---------------- MAIN ---------------- #
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8002))
    app.run(host="0.0.0.0", port=port, debug=True)
