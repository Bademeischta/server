import json
import os
import random
from flask import Flask, request, jsonify

app = Flask(__name__)

class Konto():
    def __init__(self):
        self.dateiname = "bankdaten_secure.json"
        self.daten = {"users": {}, "ips": {}}
        self.laden()

    def laden(self):
        if os.path.exists(self.dateiname):
            try:
                with open(self.dateiname, "r") as datei:
                    temp = json.load(datei)
                    if "users" in temp:
                        self.daten = temp
            except:
                pass

    def speichern(self):
        with open(self.dateiname, "w") as datei:
            json.dump(self.daten, datei)

bank = Konto()

@app.route('/')
def startseite():
    return open("index.html", "r", encoding="utf-8").read()

@app.route('/aktion', methods=['POST'])
def verarbeiten():
    req = request.json
    befehl = req.get('befehl')
    name = req.get('name')
    pw = req.get('pw')
    user_ip = request.remote_addr

    if befehl == "neu":
        if name != "Admin" and user_ip in bank.daten["ips"]:
            return jsonify({"text": "Nur 1 Konto pro PC erlaubt!"})
        if name in bank.daten["users"]:
            return jsonify({"text": "Name vergeben!"})
        
        bank.daten["users"][name] = {"geld": 0, "passwort": pw}
        if name != "Admin":
            bank.daten["ips"][user_ip] = name
        bank.speichern()
        return jsonify({"text": "Konto erstellt. Geh arbeiten!"})

    elif befehl == "login":
        if name in bank.daten["users"] and bank.daten["users"][name]["passwort"] == pw:
            return jsonify({"ok": True, "geld": bank.daten["users"][name]["geld"], "liste": mach_liste(name)})
        return jsonify({"text": "Login falsch!"})

    elif befehl == "arbeiten":
        verdienst = random.randint(10, 20)
        bank.daten["users"][name]["geld"] += verdienst
        bank.speichern()
        return jsonify({"ok": True, "text": f"Du hast hart gearbeitet: +{verdienst} €", "geld": bank.daten["users"][name]["geld"], "liste": mach_liste(name)})

    elif befehl == "cheat":
        if name != "Admin": return jsonify({"text": "Nur für Admin!"})
        ziel = req.get('ziel')
        betrag = int(req.get('betrag'))
        if ziel in bank.daten["users"]:
            bank.daten["users"][ziel]["geld"] += betrag
            bank.speichern()
            return jsonify({"ok": True, "text": "Cheat ausgeführt", "geld": bank.daten["users"][name]["geld"], "liste": mach_liste(name)})

    elif befehl == "spielen":
        spiel = req.get('spielArt')
        einsatz = int(req.get('einsatz'))
        konto = bank.daten["users"][name]["geld"]

        if konto < einsatz:
            return jsonify({"ok": True, "text": "Nicht genug Geld! Geh arbeiten!", "geld": konto, "liste": mach_liste(name)})

        bank.daten["users"][name]["geld"] -= einsatz
        gewinn = 0
        msg = ""

        if spiel == "muenze":
            tipp = req.get('tipp') # Kopf oder Zahl
            wurf = random.choice(["Kopf", "Zahl"])
            if tipp == wurf:
                gewinn = einsatz * 2
                msg = f"Gewonnen! Es war {wurf}."
            else:
                msg = f"Verloren! Es war {wurf}."

        elif spiel == "zahl":
            tipp = int(req.get('tipp'))
            zahl = random.randint(1, 5)
            if tipp == zahl:
                gewinn = einsatz * 5
                msg = f"TREFFER! Zahl war {zahl}."
            else:
                msg = f"Daneben. Zahl war {zahl}."

        elif spiel == "slots":
            symbole = ["🍒", "🍋", "💎", "7️⃣"]
            walzen = [random.choice(symbole) for _ in range(3)]
            msg = f"[{walzen[0]}] [{walzen[1]}] [{walzen[2]}] "
            
            if walzen[0] == walzen[1] == walzen[2]:
                if walzen[0] == "7️⃣":
                    gewinn = einsatz * 50 # JACKPOT
                    msg += " JACKPOT!!!"
                else:
                    gewinn = einsatz * 10
                    msg += " Gewonnen!"
            elif walzen[0] == walzen[1] or walzen[1] == walzen[2]:
                gewinn = int(einsatz * 1.5)
                msg += " Kleiner Gewinn."
            else:
                msg += " Nichts."

        bank.daten["users"][name]["geld"] += gewinn
        bank.speichern()
        
        return jsonify({"ok": True, "text": msg, "geld": bank.daten["users"][name]["geld"], "liste": mach_liste(name)})

def mach_liste(wer):
    html = ""
    for u, d in bank.daten["users"].items():
        if wer == "Admin":
            html += f"<b>{u}</b>: {d['geld']}€ (PW: {d['passwort']})<br>"
        else:
            html += f"<b>{u}</b>: {d['geld']}€<br>"
    return html

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)