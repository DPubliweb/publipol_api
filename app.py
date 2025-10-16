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
    

from flask import Flask, request, jsonify
import psycopg2
import os

# ... ton app existant ...

@app.route("/ciblage", methods=["POST"])
def ciblage():
    data = request.get_json() or {}

    # Récupère les listes (attendues comme arrays). Si absent -> None
    communes = data.get("code_commune")
    bdvs = data.get("code_bdv")
    circos = data.get("code_circo")

    # Age par défaut si absent
    age_min = int(data.get("age_min", 18))
    age_max = int(data.get("age_max", 120))

    # Validation minimale : au moins une des 3 listes doit être fournie et non vide
    provided = []
    if communes:
        if not isinstance(communes, list) or len(communes) == 0:
            return jsonify({"error": "code_commune must be a non-empty array if provided"}), 400
        provided.append(("code_commune", communes))
    if bdvs:
        if not isinstance(bdvs, list) or len(bdvs) == 0:
            return jsonify({"error": "code_bdv must be a non-empty array if provided"}), 400
        provided.append(("code_bdv", bdvs))
    if circos:
        if not isinstance(circos, list) or len(circos) == 0:
            return jsonify({"error": "code_circo must be a non-empty array if provided"}), 400
        provided.append(("code_circo", circos))

    if not provided:
        return jsonify({"error": "Provide at least one of: code_commune, code_bdv, code_circo (arrays)"}), 400

    # Construction sécurisée du WHERE (IN ...) avec paramètres
    where_parts = []
    params = []

    for col, codes in provided:
        placeholders = ", ".join(["%s"] * len(codes))
        where_parts.append(f"{col} IN ({placeholders})")
        params.extend(codes)

    # joint les clauses par OR et entoure de parenthèses
    where_geo = " OR ".join(where_parts)
    where_geo = f"({where_geo})"

    # ajoute les bornes d'age
    params.append(age_min)
    params.append(age_max)

    query = f"""
        SELECT COUNT(DISTINCT tel_mobile)
        FROM paralos_data
        WHERE {where_geo}
        AND age BETWEEN %s AND %s;
    """

    # (optionnel) log de debug (dans tes logs Qoddi)
    print("DEBUG SQL:", query)
    print("DEBUG PARAMS:", params)

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
            "filters": {
                "code_commune": communes or [],
                "code_bdv": bdvs or [],
                "code_circo": circos or []
            }
        })
    except Exception as e:
        # log server-side pour debug
        print("ERROR executing ciblage query:", str(e))
        return jsonify({"status": "error ❌", "message": str(e)}), 500


@app.route("/commande", methods=["POST"])
def commande():
    data = request.get_json()

    required_fields = [
        # Candidat
        "candidat_nom", "candidat_prenom", "candidat_id_paralos",
        "candidat_adresse", "candidat_cp", "candidat_ville",
        "candidat_tel1", "candidat_email",
        # Mandataire
        "mandataire_nom", "mandataire_prenom",
        "mandataire_adresse", "mandataire_cp", "mandataire_ville",
        "mandataire_tel1", "mandataire_email",
        # LP
        "lp_active", "type_lp", "photo_url", "profession_de_foi_url", "bulletin_url",
        # Tarification
        "nombre_contacts", "sms_count", "prix_total"
    ]

    missing_fields = [f for f in required_fields if f not in data]
    if missing_fields:
        return jsonify({"error": f"Missing fields: {', '.join(missing_fields)}"}), 400

    commande_id = str(uuid.uuid4())

    return jsonify({
        "commande_id": commande_id,
        "statut": "reçue",
        "details": {
            "candidat": {
                "nom": data["candidat_nom"],
                "prenom": data["candidat_prenom"]
            },
            "mandataire": {
                "nom": data["mandataire_nom"],
                "prenom": data["mandataire_prenom"]
            },
            "lp": {
                "active": data["lp_active"],
                "type_lp": data["type_lp"]
            },
            "tarification": {
                "contacts": data["nombre_contacts"],
                "sms": data["sms_count"],
                "prix": data["prix_total"]
            }
        }
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8002))  # valeur par défaut 8002 en local
    app.run(host="0.0.0.0", port=port, debug=True)

