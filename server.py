import json
import os
import random
import time
from flask import Flask, request, jsonify

app = Flask(__name__)

BUSINESSES = {
    "stift": {"name": "Stifte-Verleih", "cost": 100, "income": 1},
    "kiosk": {"name": "Pausen-Kiosk", "cost": 1000, "income": 15},
    "mafia": {"name": "Pausenhof-Mafia", "cost": 5000, "income": 100}
}

def create_deck():
    suits = ["♥", "♦", "♠", "♣"]
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    deck = []
    for s in suits:
        for r in ranks:
            deck.append({"suit": s, "rank": r})
    random.shuffle(deck)
    return deck

def calc_score(hand):
    score = 0
    aces = 0
    for card in hand:
        r = card["rank"]
        if r in ["J", "Q", "K"]:
            score += 10
        elif r == "A":
            aces += 1
            score += 11
        else:
            score += int(r)

    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score

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

def mach_liste(wer):
    html = ""
    # Sort by money descending
    sorted_users = sorted(bank.daten["users"].items(), key=lambda x: x[1].get("geld", 0), reverse=True)

    for u, d in sorted_users:
        if wer == "Admin":
            html += f"<b>{u}</b>: {d['geld']}€ (PW: {d['passwort']})<br>"
        else:
            html += f"<b>{u}</b>: {d['geld']}€<br>"
    return html

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

        bank.daten["users"][name] = {
            "geld": 0,
            "passwort": pw,
            "buildings": {},
            "last_collected": time.time()
        }
        if name != "Admin":
            bank.daten["ips"][user_ip] = name
        bank.speichern()
        return jsonify({"text": "Konto erstellt. Geh arbeiten!"})

    elif befehl == "login":
        if name in bank.daten["users"] and bank.daten["users"][name]["passwort"] == pw:
            # Migration check
            if "buildings" not in bank.daten["users"][name]:
                bank.daten["users"][name]["buildings"] = {}
                bank.daten["users"][name]["last_collected"] = time.time()
                bank.speichern()

            # Check if active blackjack game exists, if so return it?
            # For simplicity, we might clear it or let the user resume.
            # Let's just return success.
            bj_state = bank.daten["users"][name].get("blackjack", None)

            return jsonify({
                "ok": True,
                "geld": bank.daten["users"][name]["geld"],
                "liste": mach_liste(name),
                "buildings": bank.daten["users"][name]["buildings"],
                "blackjack": bj_state
            })
        return jsonify({"text": "Login falsch!"})

    elif befehl == "arbeiten":
        verdienst = random.randint(10, 20)
        bank.daten["users"][name]["geld"] += verdienst
        bank.speichern()
        return jsonify({"ok": True, "text": f"Du hast hart gearbeitet: +{verdienst} €", "geld": bank.daten["users"][name]["geld"], "liste": mach_liste(name)})

    elif befehl == "kaufen":
        item = req.get('item')
        if item not in BUSINESSES:
            return jsonify({"text": "Gibt es nicht!"})

        cost = BUSINESSES[item]["cost"]
        user_data = bank.daten["users"][name]

        if user_data["geld"] < cost:
             return jsonify({"text": "Nicht genug Geld!", "geld": user_data["geld"]})

        user_data["geld"] -= cost
        if "buildings" not in user_data: user_data["buildings"] = {}

        user_data["buildings"][item] = user_data["buildings"].get(item, 0) + 1
        bank.speichern()

        return jsonify({
            "ok": True,
            "text": f"Gekauft: {BUSINESSES[item]['name']}",
            "geld": user_data["geld"],
            "buildings": user_data["buildings"]
        })

    elif befehl == "abholen":
        user_data = bank.daten["users"][name]
        now = time.time()
        last = user_data.get("last_collected", now)
        diff = now - last

        if diff > 86400: diff = 86400 # Max 24h

        income_per_sec = 0
        buildings = user_data.get("buildings", {})
        for b_key, count in buildings.items():
            if b_key in BUSINESSES:
                income_per_sec += BUSINESSES[b_key]["income"] * count

        earned = int(income_per_sec * diff)

        if earned > 0:
            user_data["geld"] += earned
            user_data["last_collected"] = now
            bank.speichern()
            msg = f"Einnahmen abgeholt: {earned}€"
        else:
            user_data["last_collected"] = now
            bank.speichern()
            msg = "Nichts zu holen."

        return jsonify({
            "ok": True,
            "text": msg,
            "geld": user_data["geld"],
            "liste": mach_liste(name)
        })

    # --- BLACKJACK LOGIC ---
    elif befehl == "bj_start":
        einsatz = int(req.get('einsatz'))
        user_data = bank.daten["users"][name]

        if user_data.get("blackjack"):
            return jsonify({"text": "Spiel läuft schon!", "blackjack": user_data["blackjack"]})

        if user_data["geld"] < einsatz:
            return jsonify({"text": "Nicht genug Geld!"})

        user_data["geld"] -= einsatz
        deck = create_deck()

        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]

        state = {
            "deck": deck,
            "player": player_hand,
            "dealer": dealer_hand,
            "bet": einsatz,
            "status": "playing"
        }

        user_data["blackjack"] = state
        bank.speichern()

        # Check Natural Blackjack
        p_score = calc_score(player_hand)
        if p_score == 21:
            # Auto win 3:2 unless dealer also has 21 (Push) - simplificatin: instant win
            gewinn = int(einsatz * 2.5)
            user_data["geld"] += gewinn
            del user_data["blackjack"]
            bank.speichern()
            return jsonify({
                "ok": True,
                "text": "BLACKJACK!!",
                "geld": user_data["geld"],
                "blackjack": {
                    "player": player_hand,
                    "dealer": dealer_hand, # Show all
                    "status": "finished",
                    "result": "win"
                }
            })

        return jsonify({
            "ok": True,
            "blackjack": {
                "player": player_hand,
                "dealer": [dealer_hand[0], {"suit": "?", "rank": "?"}], # Hide 2nd card
                "status": "playing",
                "score": p_score
            },
            "geld": user_data["geld"]
        })

    elif befehl == "bj_hit":
        user_data = bank.daten["users"][name]
        state = user_data.get("blackjack")
        if not state: return jsonify({"text": "Kein Spiel!"})

        deck = state["deck"]
        # Ensure deck isn't empty? (Unlikely for one hand but good practice)
        if not deck: deck = create_deck()

        new_card = deck.pop()
        state["player"].append(new_card)
        p_score = calc_score(state["player"])

        if p_score > 21:
            # BUST
            del user_data["blackjack"]
            bank.speichern()
            return jsonify({
                "ok": True,
                "text": f"Bust! ({p_score})",
                "blackjack": {
                    "player": state["player"],
                    "dealer": state["dealer"],
                    "status": "finished",
                    "result": "lose",
                    "score": p_score
                }
            })

        bank.speichern()
        return jsonify({
            "ok": True,
            "blackjack": {
                "player": state["player"],
                "dealer": [state["dealer"][0], {"suit": "?", "rank": "?"}],
                "status": "playing",
                "score": p_score
            }
        })

    elif befehl == "bj_stand":
        user_data = bank.daten["users"][name]
        state = user_data.get("blackjack")
        if not state: return jsonify({"text": "Kein Spiel!"})

        deck = state["deck"]
        dealer_hand = state["dealer"]
        p_score = calc_score(state["player"])

        # Dealer draws until 17
        while calc_score(dealer_hand) < 17:
            if not deck: deck = create_deck() # resupply
            dealer_hand.append(deck.pop())

        d_score = calc_score(dealer_hand)

        del user_data["blackjack"] # Game over

        msg = ""
        result = ""
        gewinn = 0

        if d_score > 21:
            msg = "Dealer Bust! Du gewinnst!"
            result = "win"
            gewinn = state["bet"] * 2
        elif d_score > p_score:
            msg = f"Dealer hat {d_score}. Du verlierst."
            result = "lose"
        elif d_score < p_score:
            msg = f"Du hast {p_score}, Dealer hat {d_score}. Sieg!"
            result = "win"
            gewinn = state["bet"] * 2
        else:
            msg = "Unentschieden (Push)."
            result = "push"
            gewinn = state["bet"]

        user_data["geld"] += gewinn
        bank.speichern()

        return jsonify({
            "ok": True,
            "text": msg,
            "geld": user_data["geld"],
            "blackjack": {
                "player": state["player"],
                "dealer": dealer_hand,
                "status": "finished",
                "result": result,
                "d_score": d_score,
                "p_score": p_score
            }
        })
    # --- END BLACKJACK ---

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
