from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from holdem_engine import (
    Deck,
    Player,
    parse_card,
    best_hand_rank,
    rank_name,
    estimate_equity,
)


# ============================================================
# App setup
# ============================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "https://your-frontend-domain.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# For debugging, set True to reveal bot cards.
# For a real poker UI, set this to False.
SHOW_BOT_CARDS = True


# ============================================================
# Encryption setup
# ============================================================

FERNET_KEY = os.environ.get("FERNET_KEY")

if FERNET_KEY is None:
    # Local development fallback.
    # In production/Vercel, set FERNET_KEY as an environment variable.
    FERNET_KEY = Fernet.generate_key().decode()
    print("WARNING: No FERNET_KEY found. Generated temporary local key.")

fernet = Fernet(FERNET_KEY.encode())


# ============================================================
# Request models
# ============================================================

class ActionRequest(BaseModel):
    state_token: str
    action: str
    amount: int | None = None


# ============================================================
# Card serialization helpers
# ============================================================

def cards_to_strings(cards):
    return [str(card) for card in cards]


def strings_to_cards(cards):
    return [parse_card(card) for card in cards]


# ============================================================
# Stateless poker game
# ============================================================

@dataclass
class ApiHoldemGame:
    seed: int | None = None
    bot_simulations: int = 2000

    def __post_init__(self):
        self.rng = random.Random(self.seed)

        self.hero = Player(name="Hero", is_human=True, stack=1000)
        self.bot = Player(name="Bot", is_human=False, stack=1000)
        self.players = [self.hero, self.bot]

        self.deck: Deck | None = None
        self.board = []
        self.pot = 0
        self.stage = "preflop"
        self.current_bet = 0
        self.game_over = False
        self.winner = None
        self.log = []

        self.start_hand()

    def start_hand(self):
        self.deck = Deck(rng=self.rng)
        self.deck.shuffle()

        self.board = []
        self.pot = 0
        self.stage = "preflop"
        self.current_bet = 0
        self.game_over = False
        self.winner = None
        self.log = []

        for player in self.players:
            player.hole_cards = []
            player.folded = False
            player.current_bet = 0

        for _ in range(2):
            for player in self.players:
                player.hole_cards.extend(self.deck.draw(1))

        self.log.append("New hand started.")

    # --------------------------------------------------------
    # Public state returned to frontend
    # --------------------------------------------------------

    def get_state(self):
        call_amount = max(0, self.current_bet - self.hero.current_bet)

        return {
            "stage": self.stage,
            "pot": self.pot,
            "board": cards_to_strings(self.board),
            "hero": {
                "cards": cards_to_strings(self.hero.hole_cards),
                "stack": self.hero.stack,
                "current_bet": self.hero.current_bet,
                "folded": self.hero.folded,
            },
            "bot": {
                "cards": cards_to_strings(self.bot.hole_cards)
                if SHOW_BOT_CARDS or self.game_over
                else ["??", "??"],
                "stack": self.bot.stack,
                "current_bet": self.bot.current_bet,
                "folded": self.bot.folded,
            },
            "to_call": call_amount,
            "legal_actions": self.legal_actions(),
            "game_over": self.game_over,
            "winner": self.winner,
            "log": self.log[-20:],
        }

    def legal_actions(self):
        if self.game_over:
            return []

        call_amount = max(0, self.current_bet - self.hero.current_bet)

        if call_amount == 0:
            return ["check", "bet", "fold"]

        return ["call", "raise", "fold"]

    # --------------------------------------------------------
    # Apply user action
    # --------------------------------------------------------

    def apply_user_action(self, action: str, amount: int | None = None):
        if self.game_over:
            raise ValueError("Game is already over.")

        action = action.lower().strip()

        if action not in self.legal_actions():
            raise ValueError(f"Illegal action right now: {action}")

        self.process_action(self.hero, action, amount)

        if self.check_fold_win():
            return

        # If user calls, the betting round is complete.
        if action == "call":
            self.end_betting_round()
            return

        # Bot responds to user check/bet/raise.
        self.bot_respond()

        if self.check_fold_win():
            return

        # If bets are matched, move to next street.
        if self.hero.current_bet == self.bot.current_bet:
            self.end_betting_round()

    # --------------------------------------------------------
    # Process individual action
    # --------------------------------------------------------

    def process_action(self, player: Player, action: str, amount: int | None):
        call_amount = max(0, self.current_bet - player.current_bet)

        if action == "fold":
            player.folded = True
            self.log.append(f"{player.name} folds.")
            return

        if action == "check":
            if call_amount != 0:
                raise ValueError("Cannot check while facing a bet.")
            self.log.append(f"{player.name} checks.")
            return

        if action == "call":
            if call_amount <= 0:
                raise ValueError("Nothing to call.")
            self.collect_bet(player, call_amount)
            self.log.append(f"{player.name} calls {call_amount}.")
            return

        if action == "bet":
            if self.current_bet != 0:
                raise ValueError("There is already a bet. Use raise.")
            if amount is None or amount <= 0:
                raise ValueError("Bet amount must be positive.")
            self.collect_bet(player, amount)
            self.current_bet = player.current_bet
            self.log.append(f"{player.name} bets {amount}.")
            return

        if action == "raise":
            if amount is None:
                raise ValueError("Raise needs an amount.")

            # Here amount means total round bet, not extra amount.
            if amount <= self.current_bet:
                raise ValueError("Raise amount must be greater than current bet.")

            extra_needed = amount - player.current_bet
            self.collect_bet(player, extra_needed)
            self.current_bet = player.current_bet
            self.log.append(f"{player.name} raises to {amount}.")
            return

        raise ValueError(f"Unknown action: {action}")

    def collect_bet(self, player: Player, amount: int):
        if amount <= 0:
            raise ValueError("Bet amount must be positive.")

        if amount > player.stack:
            raise ValueError("All-in is not supported yet in this simplified version.")

        player.stack -= amount
        player.current_bet += amount
        self.pot += amount

    # --------------------------------------------------------
    # Bot logic
    # --------------------------------------------------------

    def bot_respond(self):
        call_amount = max(0, self.current_bet - self.bot.current_bet)
        action, amount = self.get_monte_carlo_bot_action(call_amount)
        self.process_action(self.bot, action, amount)

    def get_monte_carlo_bot_action(self, call_amount: int):
        result = estimate_equity(
            hero_hand=self.bot.hole_cards,
            board=self.board,
            num_opponents=1,
            simulations=self.bot_simulations,
            seed=random.randint(0, 10**9),
        )

        equity = result["equity"]
        self.log.append(f"Bot estimated equity: {equity:.1%}.")

        # Nobody has bet yet.
        if call_amount == 0:
            if equity >= 0.75 and self.bot.stack >= 60:
                return "bet", 60

            if equity >= 0.60 and self.bot.stack >= 30:
                return "bet", 30

            return "check", None

        # Bot is facing a bet.
        if call_amount > self.bot.stack:
            return "fold", None

        break_even_equity = call_amount / (self.pot + call_amount)

        # Raise if bot has a big edge.
        if equity >= break_even_equity + 0.25:
            raise_to = self.current_bet + 40
            extra_needed = raise_to - self.bot.current_bet

            if extra_needed <= self.bot.stack:
                return "raise", raise_to

        # Call if profitable.
        if equity >= break_even_equity:
            return "call", None

        return "fold", None

    # --------------------------------------------------------
    # Round progression
    # --------------------------------------------------------

    def check_fold_win(self):
        active = [p for p in self.players if not p.folded]

        if len(active) == 1:
            winner = active[0]
            winner.stack += self.pot

            self.winner = winner.name
            self.game_over = True

            self.log.append(
                f"{winner.name} wins {self.pot} because the other player folded."
            )

            self.pot = 0
            return True

        return False

    def end_betting_round(self):
        for player in self.players:
            player.current_bet = 0

        self.current_bet = 0

        if self.stage == "preflop":
            self.board.extend(self.deck.draw(3))
            self.stage = "flop"
            self.log.append("Flop dealt.")

        elif self.stage == "flop":
            self.board.extend(self.deck.draw(1))
            self.stage = "turn"
            self.log.append("Turn dealt.")

        elif self.stage == "turn":
            self.board.extend(self.deck.draw(1))
            self.stage = "river"
            self.log.append("River dealt.")

        elif self.stage == "river":
            self.showdown()

    def showdown(self):
        hero_rank = best_hand_rank(self.hero.hole_cards + self.board)
        bot_rank = best_hand_rank(self.bot.hole_cards + self.board)

        self.log.append(f"Hero has {rank_name(hero_rank)}.")
        self.log.append(f"Bot has {rank_name(bot_rank)}.")

        if hero_rank > bot_rank:
            self.hero.stack += self.pot
            self.winner = "Hero"
            self.log.append(f"Hero wins {self.pot}.")
        elif bot_rank > hero_rank:
            self.bot.stack += self.pot
            self.winner = "Bot"
            self.log.append(f"Bot wins {self.pot}.")
        else:
            split = self.pot // 2
            remainder = self.pot % 2

            self.hero.stack += split + remainder
            self.bot.stack += split

            self.winner = "Split"
            self.log.append(f"Split pot of {self.pot}.")

        self.pot = 0
        self.game_over = True
        self.stage = "showdown"

    # --------------------------------------------------------
    # Serialization for encrypted state token
    # --------------------------------------------------------

    def to_dict(self):
        return {
            "hero": {
                "stack": self.hero.stack,
                "hole_cards": cards_to_strings(self.hero.hole_cards),
                "folded": self.hero.folded,
                "current_bet": self.hero.current_bet,
            },
            "bot": {
                "stack": self.bot.stack,
                "hole_cards": cards_to_strings(self.bot.hole_cards),
                "folded": self.bot.folded,
                "current_bet": self.bot.current_bet,
            },
            "deck": cards_to_strings(self.deck.cards),
            "board": cards_to_strings(self.board),
            "pot": self.pot,
            "stage": self.stage,
            "current_bet": self.current_bet,
            "game_over": self.game_over,
            "winner": self.winner,
            "log": self.log,
            "bot_simulations": self.bot_simulations,
        }

    @classmethod
    def from_dict(cls, data):
        game = cls(seed=None, bot_simulations=data.get("bot_simulations", 2000))

        game.hero.stack = data["hero"]["stack"]
        game.hero.hole_cards = strings_to_cards(data["hero"]["hole_cards"])
        game.hero.folded = data["hero"]["folded"]
        game.hero.current_bet = data["hero"]["current_bet"]

        game.bot.stack = data["bot"]["stack"]
        game.bot.hole_cards = strings_to_cards(data["bot"]["hole_cards"])
        game.bot.folded = data["bot"]["folded"]
        game.bot.current_bet = data["bot"]["current_bet"]

        game.deck.cards = strings_to_cards(data["deck"])
        game.board = strings_to_cards(data["board"])
        game.pot = data["pot"]
        game.stage = data["stage"]
        game.current_bet = data["current_bet"]
        game.game_over = data["game_over"]
        game.winner = data["winner"]
        game.log = data["log"]

        return game


# ============================================================
# Token helpers
# ============================================================

def encode_game(game: ApiHoldemGame) -> str:
    raw = json.dumps(game.to_dict()).encode()
    return fernet.encrypt(raw).decode()


def decode_game(token: str) -> ApiHoldemGame:
    try:
        raw = fernet.decrypt(token.encode())
        data = json.loads(raw.decode())
        return ApiHoldemGame.from_dict(data)
    except InvalidToken:
        raise HTTPException(status_code=400, detail="Invalid game token.")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not decode game state.")


# ============================================================
# Endpoints
# ============================================================

@app.get("/")
def root():
    return {"message": "Poker API is running."}


@app.post("/games")
def create_game():
    game = ApiHoldemGame(
        seed=random.randint(0, 10**9),
        bot_simulations=2000,
    )

    return {
        "state_token": encode_game(game),
        "state": game.get_state(),
    }


@app.post("/action")
def submit_action(request: ActionRequest):
    game = decode_game(request.state_token)

    try:
        game.apply_user_action(request.action, request.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "state_token": encode_game(game),
        "state": game.get_state(),
    }