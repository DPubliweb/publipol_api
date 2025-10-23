from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import uuid
import psycopg2


API_KEY = os.getenv("API_KEY")

app = Flask(__name__)
CORS(app)

# Middleware for API key authentication
@app.before_request
def authenticate():
    if request.path.startswith('/ciblage') or request.path.startswith('/commande'):
        api_key = request.headers.get('x-api-key')
        if api_key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401

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
    

@app.route("/ciblage", methods=["POST"])
def ciblage():
    data = request.get_json() or {}

    geo_selection = data.get("geo_selection", [])
    age_min = int(data.get("age_min", 18))
    age_max = int(data.get("age_max", 120))

    if not isinstance(geo_selection, list) or len(geo_selection) == 0:
        return jsonify({"error": "geo_selection must be a non-empty array"}), 400

    code_bdv_list = []
    code_commune_list = []
    code_circo_list = []

    # Détection automatique selon le prefixe
    for code in geo_selection:
        if code.startswith("BV"):  # Bureau de vote
            code_bdv_list.append(code)
        elif code.startswith("COM"):  # Commune
            code_commune_list.append(code.replace("COM", ""))  # On retire "COM"
        elif code.startswith("C"):  # Circonscription (ex: C01005)
            code_circo_list.append(code.replace("C", ""))  # On retire "C"
        else:
            print(f"⚠ Code non reconnu: {code}")

    params = []
    where_parts = []

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

    params.append(age_min)
    params.append(age_max)

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
            port=int(os.getenv("REDSHIFT_PORT", 5439))
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                result = cur.fetchone()
                count = result[0] if result else 0

        return jsonify({
            "status": "success ✅",
            "count": count,
            "age_min": age_min,
            "age_max": age_max,
            "geo_selection_received": geo_selection
        })
    except Exception as e:
        print("ERROR executing ciblage query:", str(e))
        return jsonify({"status": "error ❌", "message": str(e)}), 500



@app.route("/commande", methods=["POST"])
def commande():
    data = request.get_json()

    # Vérification structure conforme doc Paralos + comptage obligatoire
    if "candidat" not in data or "mandataire" not in data or "lp" not in data or "comptage" not in data:
        return jsonify({"error": "Structure invalide. Format attendu: candidat{}, mandataire{}, lp{}, comptage{}"}), 400

    candidat = data["candidat"]
    mandataire = data["mandataire"]
    lp = data["lp"]
    comptage = data["comptage"]

    # Champs requis
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

    # Validation comptage.total
    total_contacts = int(comptage["total"])
    if total_contacts <= 0:
        return jsonify({"error": "comptage.total doit être supérieur à 0"}), 400

    commande_id = str(uuid.uuid4())

    return jsonify({
        "commande_id": commande_id,
        "statut": "reçue",
        "total_contacts": total_contacts,
        "details": {
            "candidat": {
                "nom": candidat["nom"],
                "prenom": candidat["prenom"],
                "id_paralos": candidat["id_paralos"]
            },
            "mandataire": {
                "nom": mandataire["nom"],
                "prenom": mandataire["prenom"]
            },
            "lp": lp,
            "comptage": comptage
        }
    })



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8002))  # valeur par défaut 8002 en local
    app.run(host="0.0.0.0", port=port, debug=True)

