from flask import Flask, request, jsonify
import os
import uuid

app = Flask(__name__)

# ✅ Clé API lue depuis variable d'environnement Qoddi
API_KEY = os.getenv("API_KEY")

# ✅ Middleware de sécurité
@app.before_request
def check_api_key():
    key = request.headers.get("x-api-key")
    if not key or key != API_KEY:
        return jsonify({"error": "Unauthorized - Invalid or missing API Key"}), 401

# ✅ ROUTE 1 - /ciblage
@app.route("/ciblage", methods=["POST"])
def ciblage():
    data = request.get_json()
    if not data or "geo_selection" not in data:
        return jsonify({
            "error": "Missing required field",
            "missing_fields": ["geo_selection"]
        }), 400

    # Placeholder comptage
    return jsonify({
        "message": "Ciblage reçu",
        "count": 8500
    }), 200

# ✅ ROUTE 2 - /tarification
@app.route("/tarification", methods=["POST"])
def tarification():
    data = request.get_json()
    required_fields = ["contacts", "sms_count", "lp"]

    # ✅ Détection précise des champs manquants
    missing = [field for field in required_fields if field not in data]
    if missing:
        return jsonify({
            "error": "Missing required fields",
            "missing_fields": missing
        }), 400

    # 👇 Exemple de calcul (modifiable plus tard)
    montant = data["contacts"] * data["sms_count"] * 0.08
    if data["lp"]:
        montant += data["contacts"] * 0.02

    return jsonify({
        "tarif_total": round(montant, 2)
    }), 200

# ✅ ROUTE 3 - /commande
@app.route("/commande", methods=["POST"])
def commande():
    data = request.get_json()

    # Vérification des 3 sections principales
    required_sections = ["candidat", "mandataire", "lp"]
    missing_sections = [s for s in required_sections if s not in data]
    if missing_sections:
        return jsonify({
            "error": "Missing required section",
            "missing_sections": missing_sections
        }), 400

    # Validation champs obligatoires candidat
    required_candidat = ["nom", "prenom", "id_paralos", "adresse", "cp", "ville", "tel1", "email"]
    missing_candidat = [field for field in required_candidat if field not in data["candidat"]]

    # Validation champs obligatoires mandataire
    required_mandataire = ["nom", "prenom", "adresse", "cp", "ville", "tel1", "email"]
    missing_mandataire = [field for field in required_mandataire if field not in data["mandataire"]]

    # Si manque des champs dans une section
    if missing_candidat or missing_mandataire:
        return jsonify({
            "error": "Missing required fields",
            "candidat_missing": missing_candidat,
            "mandataire_missing": missing_mandataire
        }), 400

    # ✅ Génération ID commande unique
    commande_id = str(uuid.uuid4())

    return jsonify({
        "message": "Commande enregistrée",
        "commande_id": commande_id
    }), 200


if __name__ == "__main__":
    # ✅ Compatible Qoddi (port fixe 8002)
    app.run(host="0.0.0.0", port=8002)
