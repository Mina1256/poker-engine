from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from holdem_engine import (
    Deck,
    parse_card,
    best_hand_rank,
    rank_name,
    estimate_equity,
)


# ============================================================
# App setup
# ============================================================

app = FastAPI()

# Force CORS headers on every response.
# This is intentionally permissive for testing/demo.
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


@app.middleware("http")
async def force_cors(request: Request, call_next):
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=CORS_HEADERS)

    try:
        response = await call_next(request)
    except Exception as e:
        response = JSONResponse(
            status_code=500,
            content={"detail": str(e)},
        )

    for key, value in CORS_HEADERS.items():
        response.headers[key] = value

    return response


SHOW_BOT_CARDS = True


# ============================================================
# Request models
# ============================================================

class ActionRequest(BaseModel):
    game_state: dict[str, Any]
    action: str
    amount: int | None = None


# ============================================================
# Helpers
# ============================================================

def cards_to_strings(cards):
    return [str(card) for card in cards]


def strings_to_cards(cards):
    return [parse_card(card) for card in cards]


@dataclass
class ApiPlayer:
    name: str
    stack: int = 1000
    hole_cards: list | None = None
    folded: bool = False
    current_bet: int = 0

    def __post_init__(self):
        if self.hole_cards is None:
            self.hole_cards = []


# ============================================================
# Stateless poker game
# ============================================================

@dataclass
class ApiHoldemGame:
    seed: int | None = None
    bot_simulations: int = 300

    def __post_init__(self):
        self.rng = random.Random(self.seed)

        self.hero = ApiPlayer(name="Hero", stack=1000)
        self.bot = ApiPlayer(name="Bot", stack=1000)
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

    def get_public_state(self):
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

        # If user calls, betting round is complete.
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
    # Process action
    # --------------------------------------------------------

    def process_action(self, player: ApiPlayer, action: str, amount: int | None):
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

            # amount means total round bet, not extra amount.
            if amount <= self.current_bet:
                raise ValueError("Raise amount must be greater than current bet.")

            extra_needed = amount - player.current_bet
            self.collect_bet(player, extra_needed)
            self.current_bet = player.current_bet
            self.log.append(f"{player.name} raises to {amount}.")
            return

        raise ValueError(f"Unknown action: {action}")

    def collect_bet(self, player: ApiPlayer, amount: int):
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
    # Raw state serialization
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
        game = cls(seed=None, bot_simulations=data.get("bot_simulations", 300))

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
        game.bot_simulations = data.get("bot_simulations", 300)

        return game


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
        bot_simulations=300,
    )

    return {
        "game_state": game.to_dict(),
        "state": game.get_public_state(),
    }


# Optional browser test endpoint.
# Lets you visit /games in the browser and see a game.
@app.get("/games")
def create_game_from_browser():
    return create_game()


@app.post("/action")
def submit_action(request: ActionRequest):
    try:
        game = ApiHoldemGame.from_dict(request.game_state)
        game.apply_user_action(request.action, request.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing game state field: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid game state: {e}")

    return {
        "game_state": game.to_dict(),
        "state": game.get_public_state(),
    }