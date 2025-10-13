import os
import uuid
import logging
from flask import Flask, request, jsonify

app = Flask(__name__)

PORT = 8002
API_KEY = os.environ.get("API_KEY", "")

# Logger configuration
logging.basicConfig(
    filename='webhook.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

# Middleware de sécurité
@app.before_request
def check_api_key():
    if request.path == "/":
        return  # Autoriser le check health
    api_key = request.headers.get("X-API-Key")
    if api_key != API_KEY:
        logging.warning("Requête non autorisée : clé API invalide")
        return jsonify({"message": "Clé API invalide"}), 401

@app.route("/", methods=["GET"])
def index():
    return "PUBLIPOL API Webhook actif"

@app.route("/ciblage", methods=["POST"])
def ciblage():
    try:
        data = request.get_json()

        required_fields = ["geo_selection"]
        for field in required_fields:
            if field not in data:
                msg = f"Champ requis manquant : {field}"
                logging.error(f"[/ciblage] {msg}")
                return jsonify({"message": msg}), 400

        logging.info(f"[/ciblage] Données reçues : {data}")
        # Valeur fictive à adapter plus tard avec vraie base
        total_contacts = 8500

        return jsonify({
            "message": "Ciblage reçu avec succès",
            "total_contacts": total_contacts
        })
    except Exception as e:
        logging.exception("Erreur ciblage")
        return jsonify({"message": "Erreur interne"}), 500

@app.route("/commande", methods=["POST"])
def commande():
    try:
        data = request.get_json()

        required_fields = ["candidat", "mandataire", "lp", "lien_photo", "lien_profession_de_foi", "lien_bulletin_vote"]
        for field in required_fields:
            if field not in data:
                msg = f"Champ requis manquant : {field}"
                logging.error(f"[/commande] {msg}")
                return jsonify({"message": msg}), 400

        logging.info(f"[/commande] Données reçues : {data}")
        commande_id = f"CMD-{uuid.uuid4().hex[:8].upper()}"

        return jsonify({
            "commande_id": commande_id,
            "statut": "validée",
            "message": "Commande enregistrée avec succès."
        })
    except Exception as e:
        logging.exception("Erreur commande")
        return jsonify({"message": "Erreur interne"}), 500

@app.route("/facture", methods=["POST"])
def facture():
    try:
        data = request.get_json()

        required_fields = ["numero_facture", "lien_facture", "total_ht_euro", "volume_sms"]
        for field in required_fields:
            if field not in data:
                msg = f"Champ requis manquant : {field}"
                logging.error(f"[/facture] {msg}")
                return jsonify({"message": msg}), 400

        logging.info(f"[/facture] Données reçues : {data}")

        return jsonify({"message": "Facture enregistrée avec succès."})
    except Exception as e:
        logging.exception("Erreur facture")
        return jsonify({"message": "Erreur interne"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)