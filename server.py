import json
import os
import random
import time
import html
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIGURATION & GLOBALS ---
DATA_FILE = "bankdaten_secure.json"
MAX_CHAT_HISTORY = 10

# Game Constants
JOBS = {
    "tellerwaescher": {"name": "Tellerwäscher", "req_level": 1, "salary": 15, "xp": 10, "cooldown": 10},
    "zeitung": {"name": "Zeitungsjunge", "req_level": 3, "salary": 40, "xp": 25, "cooldown": 30},
    "informatiker": {"name": "Informatiker", "req_level": 5, "salary": 120, "xp": 60, "cooldown": 60},
    "bankier": {"name": "Bankier", "req_level": 10, "salary": 500, "xp": 200, "cooldown": 120}
}

ITEMS = {
    "glücksbringer": {"name": "Hasenpfote", "price": 500, "desc": "+5% Gewinnchance bei Crime", "type": "buff_crime", "value": 0.05},
    "laptop": {"name": "Hacker-Laptop", "price": 2000, "desc": "Sicherere Überfälle (Geringere Jail-Chance)", "type": "buff_safe", "value": 0.10},
    "anwalt": {"name": "Guter Anwalt", "price": 5000, "desc": "Halbiert Gefängniszeit", "type": "buff_jail", "value": 0.5}
}

# In-Memory Globals (Simulation)
stock_market = {
    "price": 100.0,
    "trend": 0,
    "last_update": time.time()
}

chat_history = []

# --- DATA MANAGEMENT ---
class Database:
    def __init__(self):
        self.filename = DATA_FILE
        self.data = {"users": {}, "ips": {}}
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r") as f:
                    temp = json.load(f)
                    if "users" in temp:
                        self.data = temp
            except:
                pass

    def save(self):
        with open(self.filename, "w") as f:
            json.dump(self.data, f)

    def get_user(self, name):
        return self.data["users"].get(name)

    def create_user(self, name, pw, ip):
        if name in self.data["users"]:
            return False, "Name vergeben!"

        # IP Check disabled for testing/ease of use, or enable if strict
        # if ip in self.data["ips"]: return False, "IP schon registriert!"

        self.data["users"][name] = {
            "passwort": pw,
            "geld": 100.0, # Startbonus
            "xp": 0,
            "level": 1,
            "inventory": [],
            "stocks": 0,
            "cooldowns": {}, # 'work': timestamp, 'crime': timestamp, 'jail_until': timestamp
            "stats": {"wins": 0, "games": 0},
            "blackjack": None, # Active game state
            "crash": None # Active game state
        }
        self.data["ips"][ip] = name
        self.save()
        return True, "User erstellt."

db = Database()

# --- HELPER FUNCTIONS ---
def update_stock_market():
    # Update price occasionally
    now = time.time()
    if now - stock_market["last_update"] > 5: # Every 5 seconds allowed to change
        change = random.uniform(-0.05, 0.05) # +/- 5%
        stock_market["price"] *= (1 + change)
        if stock_market["price"] < 1: stock_market["price"] = 1.0
        stock_market["last_update"] = now

def check_levelup(user):
    # Formula: Level = 1 + sqrt(XP / 50) roughly
    # Or simple thresholds. Let's use thresholds.
    current_level = user["level"]
    # Required XP for next level: 100 * Level
    req_xp = 100 * current_level
    if user["xp"] >= req_xp:
        user["level"] += 1
        user["xp"] -= req_xp # Carry over or reset? Let's subtract to make it 'tiers'
        return True
    return False

def get_user_buffs(user):
    buffs = {"crime_chance": 0, "jail_safety": 0, "jail_time_red": 0}
    inv = user.get("inventory", [])
    for item_key in inv:
        item = ITEMS.get(item_key)
        if item:
            if item["type"] == "buff_crime": buffs["crime_chance"] += item["value"]
            if item["type"] == "buff_safe": buffs["jail_safety"] += item["value"]
            if item["type"] == "buff_jail": buffs["jail_time_red"] = max(buffs["jail_time_red"], item["value"])
    return buffs

# --- ROUTES ---

@app.route('/')
def index():
    return open("index.html", "r", encoding="utf-8").read()

@app.route('/api/auth', methods=['POST'])
def auth():
    data = request.json
    cmd = data.get("cmd")
    name = data.get("name")
    pw = data.get("pw")
    ip = request.remote_addr

    if cmd == "register":
        success, msg = db.create_user(name, pw, ip)
        return jsonify({"ok": success, "msg": msg})

    elif cmd == "login":
        user = db.get_user(name)
        if user and user["passwort"] == pw:
            return jsonify({"ok": True, "msg": "Willkommen zurück!"})
        return jsonify({"ok": False, "msg": "Falsche Daten!"})

@app.route('/api/data', methods=['POST'])
def get_data():
    name = request.json.get("name")
    pw = request.json.get("pw")
    user = db.get_user(name)

    if not user or user["passwort"] != pw:
        return jsonify({"ok": False})

    update_stock_market()

    # Check Jail
    jail_until = user["cooldowns"].get("jail_until", 0)
    is_jailed = time.time() < jail_until

    # Leaderboard (Top 5 Money)
    sorted_users = sorted(db.data["users"].items(), key=lambda x: x[1]["geld"], reverse=True)[:5]
    leaderboard = [{"name": k, "geld": int(v["geld"]), "level": v["level"]} for k,v in sorted_users]

    return jsonify({
        "ok": True,
        "user": {
            "geld": user["geld"],
            "xp": user["xp"],
            "level": user["level"],
            "inventory": user["inventory"],
            "stocks": user.get("stocks", 0),
            "is_jailed": is_jailed,
            "jail_time": int(max(0, jail_until - time.time()))
        },
        "stock": {
            "price": stock_market["price"]
        },
        "chat": chat_history,
        "leaderboard": leaderboard
    })

@app.route('/api/work', methods=['POST'])
def work():
    name = request.json.get("name")
    user = db.get_user(name)
    job_key = request.json.get("job")

    if not user: return jsonify({"ok": False})

    # Check Jail
    if time.time() < user["cooldowns"].get("jail_until", 0):
         return jsonify({"ok": False, "msg": "Du bist im Gefängnis!"})

    job = JOBS.get(job_key)
    if not job: return jsonify({"ok": False, "msg": "Job existiert nicht."})

    if user["level"] < job["req_level"]:
        return jsonify({"ok": False, "msg": f"Level {job['req_level']} benötigt!"})

    last_work = user["cooldowns"].get(f"work_{job_key}", 0)
    if time.time() < last_work + job["cooldown"]:
        return jsonify({"ok": False, "msg": "Warte auf Cooldown!"})

    # Success
    user["geld"] += job["salary"]
    user["xp"] += job["xp"]
    user["cooldowns"][f"work_{job_key}"] = time.time()

    leveled_up = check_levelup(user)
    db.save()

    msg = f"Gearbeitet! +{job['salary']}€, +{job['xp']} XP."
    if leveled_up: msg += " LEVEL UP!"

    return jsonify({"ok": True, "msg": msg, "leveled_up": leveled_up})

@app.route('/api/crime', methods=['POST'])
def crime():
    name = request.json.get("name")
    user = db.get_user(name)
    risk_type = request.json.get("type") # 'robbery', 'hack'

    if not user: return jsonify({"ok": False})

    # Check Jail
    if time.time() < user["cooldowns"].get("jail_until", 0):
         return jsonify({"ok": False, "msg": "Du bist im Gefängnis!"})

    # Global Crime Cooldown
    last_crime = user["cooldowns"].get("crime", 0)
    if time.time() < last_crime + 60:
         return jsonify({"ok": False, "msg": "Füße stillhalten! (Cooldown)"})

    buffs = get_user_buffs(user)

    if risk_type == "bank":
        # Bank Robbery: High Risk, High Reward
        base_chance = 0.30 + buffs["crime_chance"] # 30% base
        potential_win = random.randint(500, 2000)
        jail_seconds = 60
    elif risk_type == "hack":
        # Hacking: Medium Risk, Medium Reward
        base_chance = 0.50 + buffs["crime_chance"] # 50% base
        potential_win = random.randint(100, 500)
        jail_seconds = 30
    else:
        return jsonify({"ok": False})

    user["cooldowns"]["crime"] = time.time()

    if random.random() < base_chance:
        # Success
        user["geld"] += potential_win
        user["xp"] += 50
        leveled_up = check_levelup(user)
        db.save()
        return jsonify({"ok": True, "msg": f"Erfolg! Du hast {potential_win}€ erbeutet!", "win": True})
    else:
        # Fail
        # Check if saved by safety buff? No, buff increases chance.
        # Penalty: Lose cash or Jail
        # 50/50 between Jail and Cash Loss?
        # Buff 'jail_safety' reduces jail chance if caught? No, let's just do simple jail.

        jail_time = jail_seconds
        if buffs["jail_time_red"] > 0:
            jail_time = int(jail_time * (1.0 - buffs["jail_time_red"]))

        user["cooldowns"]["jail_until"] = time.time() + jail_time
        loss = int(user["geld"] * 0.1) # Lose 10% cash on arrest
        user["geld"] -= loss
        db.save()
        return jsonify({"ok": True, "msg": f"Erwischt! {jail_time}s Knast und -{loss}€ Anwaltskosten.", "win": False})

@app.route('/api/shop', methods=['POST'])
def shop():
    name = request.json.get("name")
    item_key = request.json.get("item")
    user = db.get_user(name)

    if not user: return jsonify({"ok": False})

    item = ITEMS.get(item_key)
    if not item: return jsonify({"ok": False, "msg": "Item nicht gefunden."})

    if user["geld"] < item["price"]:
        return jsonify({"ok": False, "msg": "Nicht genug Geld!"})

    if item_key in user["inventory"]:
        return jsonify({"ok": False, "msg": "Hast du schon!"})

    user["geld"] -= item["price"]
    user["inventory"].append(item_key)
    db.save()
    return jsonify({"ok": True, "msg": f"{item['name']} gekauft!"})

@app.route('/api/stock', methods=['POST'])
def stock_trade():
    name = request.json.get("name")
    action = request.json.get("action") # 'buy', 'sell'
    amount = int(request.json.get("amount", 0))
    user = db.get_user(name)

    if not user or amount <= 0: return jsonify({"ok": False})

    update_stock_market()
    current_price = stock_market["price"]

    if action == "buy":
        cost = current_price * amount
        if user["geld"] >= cost:
            user["geld"] -= cost
            user.setdefault("stocks", 0)
            user["stocks"] += amount
            db.save()
            return jsonify({"ok": True, "msg": f"{amount} Coins gekauft."})
        else:
            return jsonify({"ok": False, "msg": "Zu wenig Geld."})

    elif action == "sell":
        if user.get("stocks", 0) >= amount:
            gain = current_price * amount
            user["stocks"] -= amount
            user["geld"] += gain
            db.save()
            return jsonify({"ok": True, "msg": f"{amount} Coins verkauft."})
        else:
            return jsonify({"ok": False, "msg": "Nicht genug Coins."})

    return jsonify({"ok": False})

@app.route('/api/chat', methods=['POST'])
def chat():
    name = request.json.get("name")
    msg = request.json.get("msg")

    if not name or not msg: return jsonify({"ok": False})

    clean_msg = html.escape(msg)
    chat_history.append({"name": name, "msg": clean_msg, "time": time.strftime("%H:%M")})

    if len(chat_history) > MAX_CHAT_HISTORY:
        chat_history.pop(0)

    return jsonify({"ok": True})

@app.route('/api/transfer', methods=['POST'])
def transfer():
    sender_name = request.json.get("name")
    receiver_name = request.json.get("receiver")
    amount = int(request.json.get("amount", 0))

    sender = db.get_user(sender_name)
    receiver = db.get_user(receiver_name)

    if not sender or not receiver:
        return jsonify({"ok": False, "msg": "User nicht gefunden."})

    if amount <= 0:
        return jsonify({"ok": False, "msg": "Ungültiger Betrag."})

    if sender["geld"] < amount:
        return jsonify({"ok": False, "msg": "Nicht genug Geld."})

    sender["geld"] -= amount
    receiver["geld"] += amount
    db.save()
    return jsonify({"ok": True, "msg": f"{amount}€ an {receiver_name} gesendet."})

# --- CASINO GAMES ---

# Helper for Deck
def get_deck():
    ranks = ['2','3','4','5','6','7','8','9','10','J','Q','K','A']
    suits = ['♥','♦','♠','♣']
    deck = [{'r':r, 's':s} for r in ranks for s in suits]
    random.shuffle(deck)
    return deck

def calc_hand(hand):
    score = 0
    aces = 0
    for card in hand:
        r = card['r']
        if r in ['J','Q','K']: score += 10
        elif r == 'A':
            score += 11
            aces += 1
        else: score += int(r)
    while score > 21 and aces:
        score -= 10
        aces -= 1
    return score

@app.route('/api/game/blackjack', methods=['POST'])
def blackjack():
    name = request.json.get("name")
    action = request.json.get("action") # 'start', 'hit', 'stand'
    bet = int(request.json.get("bet", 0))
    user = db.get_user(name)

    if not user: return jsonify({"ok": False})

    if action == "start":
        if user["blackjack"]: return jsonify({"ok": False, "msg": "Spiel läuft schon."})
        if bet <= 0 or user["geld"] < bet: return jsonify({"ok": False, "msg": "Einsatz ungültig."})

        user["geld"] -= bet
        deck = get_deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]

        user["blackjack"] = {
            "deck": deck, "player": player, "dealer": dealer, "bet": bet, "status": "playing"
        }

        # Check Instant Blackjack
        if calc_hand(player) == 21:
            win = bet * 2.5
            user["geld"] += win
            user["blackjack"]["status"] = "win"
            user["blackjack"]["msg"] = "BLACKJACK!"
            state = user["blackjack"]
            user["blackjack"] = None # End
            db.save()
            return jsonify({"ok": True, "state": state})

        db.save()
        # Hide dealer second card
        visible_state = user["blackjack"].copy()
        visible_state["dealer"] = [visible_state["dealer"][0], {"r":"?", "s":"?"}]
        del visible_state["deck"]
        return jsonify({"ok": True, "state": visible_state})

    elif action == "hit":
        if not user["blackjack"]: return jsonify({"ok": False})
        state = user["blackjack"]
        state["player"].append(state["deck"].pop())
        score = calc_hand(state["player"])

        if score > 21:
            # Bust
            state["status"] = "lose"
            state["msg"] = "BUST! Über 21."
            user["blackjack"] = None
            db.save()
            return jsonify({"ok": True, "state": state})

        db.save()
        visible_state = state.copy()
        visible_state["dealer"] = [visible_state["dealer"][0], {"r":"?", "s":"?"}]
        del visible_state["deck"]
        return jsonify({"ok": True, "state": visible_state})

    elif action == "stand":
        if not user["blackjack"]: return jsonify({"ok": False})
        state = user["blackjack"]

        # Dealer plays
        while calc_hand(state["dealer"]) < 17:
            state["dealer"].append(state["deck"].pop())

        p_score = calc_hand(state["player"])
        d_score = calc_hand(state["dealer"])

        win_amount = 0
        if d_score > 21 or p_score >= d_score:
            state["status"] = "win"
            state["msg"] = "Gewonnen!"
            win_amount = state["bet"] * 2
        else:
            state["status"] = "lose"
            state["msg"] = "Bank gewinnt."

        user["geld"] += win_amount
        user["blackjack"] = None
        db.save()

        # Return full state including dealer cards
        del state["deck"]
        return jsonify({"ok": True, "state": state})

    return jsonify({"ok": False})

@app.route('/api/game/roulette', methods=['POST'])
def roulette():
    name = request.json.get("name")
    bet_amount = int(request.json.get("bet", 0))
    bet_type = request.json.get("type") # 'number', 'color', 'dozen'
    bet_value = request.json.get("value") # 'red', 'black', '1-12', number 0-36

    user = db.get_user(name)
    if not user or user["geld"] < bet_amount or bet_amount <= 0:
        return jsonify({"ok": False, "msg": "Ungültiger Einsatz."})

    user["geld"] -= bet_amount

    # Spin
    result = random.randint(0, 36)

    # Colors
    red_nums = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    color = "green"
    if result in red_nums: color = "red"
    elif result != 0: color = "black"

    winnings = 0
    won = False

    if bet_type == "number":
        if int(bet_value) == result:
            winnings = bet_amount * 35
            won = True
    elif bet_type == "color":
        if bet_value == color:
            winnings = bet_amount * 2
            won = True
    elif bet_type == "dozen":
        # 1-12, 13-24, 25-36
        if bet_value == "1-12" and 1 <= result <= 12: won = True
        elif bet_value == "13-24" and 13 <= result <= 24: won = True
        elif bet_value == "25-36" and 25 <= result <= 36: won = True

        if won: winnings = bet_amount * 3

    if won:
        user["geld"] += winnings
        msg = f"Gewonnen! Zahl war {result} ({color})."
    else:
        msg = f"Verloren. Zahl war {result} ({color})."

    db.save()
    return jsonify({"ok": True, "result": result, "color": color, "winnings": winnings, "msg": msg})

@app.route('/api/game/crash', methods=['POST'])
def crash():
    name = request.json.get("name")
    action = request.json.get("action") # 'start', 'cashout'
    user = db.get_user(name)

    if not user: return jsonify({"ok": False})

    if action == "start":
        bet = int(request.json.get("bet", 0))
        if bet <= 0 or user["geld"] < bet:
             return jsonify({"ok": False, "msg": "Geldproblem."})

        user["geld"] -= bet

        # Calculate crash point
        # Distribution: 5% @ 1.00x, heavy tail
        # simple algo: multiplier = 0.99 / (1 - U) ... if U is [0,1)
        u = random.random()
        crash_point = max(1.0, 0.96 / (1.0 - u))
        crash_point = min(crash_point, 100.0) # Cap at 100x

        # We need to store when game started to prevent "time travel" cheating
        user["crash"] = {
            "bet": bet,
            "crash_point": crash_point,
            "start_time": time.time()
        }
        db.save()

        # Client doesn't know crash_point
        return jsonify({"ok": True, "start_time": user["crash"]["start_time"]})

    elif action == "cashout":
        if not user.get("crash"): return jsonify({"ok": False, "msg": "Kein Spiel."})

        game = user["crash"]
        claimed_mult = float(request.json.get("multiplier", 1.0))

        # Validate time roughly (allow some latency buffer)
        # Assuming linear growth speed or exp growth.
        # Let's say frontend grows multiplier: M = 1 + 0.3 * t  (linear for simplicity)
        # Or exponential M = e^(0.1 * t)
        # We'll trust the claimed_mult IF it is <= crash_point.
        # The frontend animation "stops" at crash_point.
        # If user claims > crash_point, they busted.

        actual_crash = game["crash_point"]

        if claimed_mult > actual_crash:
            # BUST (should happen if user didn't click in time, but maybe lag)
            user["crash"] = None
            db.save()
            return jsonify({"ok": True, "win": False, "crash_point": actual_crash, "msg": f"Crashed @ {actual_crash:.2f}x"})

        # Win
        winnings = int(game["bet"] * claimed_mult)
        user["geld"] += winnings
        user["crash"] = None
        db.save()
        return jsonify({"ok": True, "win": True, "crash_point": actual_crash, "winnings": winnings, "msg": f"Cashout @ {claimed_mult:.2f}x"})

    return jsonify({"ok": False})

@app.route('/api/game/crash/result', methods=['POST'])
def crash_result():
    # Only called if client animation finishes and user didn't cash out
    name = request.json.get("name")
    user = db.get_user(name)
    if user and user.get("crash"):
        cp = user["crash"]["crash_point"]
        user["crash"] = None
        db.save()
        return jsonify({"ok": True, "crash_point": cp})
    return jsonify({"ok": False})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
