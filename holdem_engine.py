from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from collections import Counter
import random


RANKS = "23456789TJQKA"
SUITS = "cdhs"  # clubs, diamonds, hearts, spades

RANK_TO_VALUE = {rank: i + 2 for i, rank in enumerate(RANKS)}
VALUE_TO_RANK = {value: rank for rank, value in RANK_TO_VALUE.items()}


@dataclass(frozen=True)
class Card:
    rank: int
    suit: str

    def __str__(self) -> str:
        return f"{VALUE_TO_RANK[self.rank]}{self.suit}"

    def __repr__(self) -> str:
        return str(self)


def parse_card(text: str) -> Card:
    text = text.strip()
    if len(text) != 2:
        raise ValueError(f"Invalid card: {text}")

    rank_char = text[0].upper()
    suit_char = text[1].lower()

    if rank_char not in RANK_TO_VALUE:
        raise ValueError(f"Invalid rank: {rank_char}")

    if suit_char not in SUITS:
        raise ValueError(f"Invalid suit: {suit_char}")

    return Card(RANK_TO_VALUE[rank_char], suit_char)


def parse_cards(text: str) -> list[Card]:
    """
    Example:
        parse_cards("As Ks Ah 7c 2d")
    """
    text = text.replace(",", " ")
    return [parse_card(part) for part in text.split()]


class Deck:
    def __init__(self, excluded: list[Card] | None = None, rng: random.Random | None = None):
        excluded = excluded or []
        excluded_set = set(excluded)

        self.cards = [
            Card(RANK_TO_VALUE[r], s)
            for r in RANKS
            for s in SUITS
            if Card(RANK_TO_VALUE[r], s) not in excluded_set
        ]

        self.rng = rng or random.Random()

    def shuffle(self) -> None:
        self.rng.shuffle(self.cards)

    def draw(self, n: int = 1) -> list[Card]:
        if n > len(self.cards):
            raise ValueError("Not enough cards left in deck")

        drawn = self.cards[:n]
        self.cards = self.cards[n:]
        return drawn


def check_no_duplicates(cards: list[Card]) -> None:
    if len(cards) != len(set(cards)):
        raise ValueError(f"Duplicate cards detected: {cards}")


def evaluate_five(cards: list[Card]) -> tuple:
    """
    Evaluates exactly 5 cards.

    Larger tuple = stronger hand.

    Categories:
        8 = straight flush
        7 = four of a kind
        6 = full house
        5 = flush
        4 = straight
        3 = three of a kind
        2 = two pair
        1 = one pair
        0 = high card
    """
    if len(cards) != 5:
        raise ValueError("evaluate_five requires exactly 5 cards")

    ranks = sorted([card.rank for card in cards], reverse=True)
    suits = [card.suit for card in cards]

    counts = Counter(ranks)
    unique_ranks = sorted(set(ranks), reverse=True)

    is_flush = len(set(suits)) == 1

    # Straight detection, including wheel: A-2-3-4-5
    is_straight = False
    straight_high = None

    if len(unique_ranks) == 5:
        if unique_ranks == [14, 5, 4, 3, 2]:
            is_straight = True
            straight_high = 5
        elif unique_ranks[0] - unique_ranks[-1] == 4:
            is_straight = True
            straight_high = unique_ranks[0]

    if is_straight and is_flush:
        return (8, straight_high)

    # Four of a kind
    four_ranks = [rank for rank, count in counts.items() if count == 4]
    if four_ranks:
        four = max(four_ranks)
        kicker = max(rank for rank in ranks if rank != four)
        return (7, four, kicker)

    # Full house
    three_ranks = sorted([rank for rank, count in counts.items() if count == 3], reverse=True)
    pair_ranks = sorted([rank for rank, count in counts.items() if count == 2], reverse=True)

    if three_ranks and pair_ranks:
        return (6, three_ranks[0], pair_ranks[0])

    if is_flush:
        return (5, tuple(ranks))

    if is_straight:
        return (4, straight_high)

    # Three of a kind
    if three_ranks:
        three = three_ranks[0]
        kickers = tuple(rank for rank in ranks if rank != three)
        return (3, three, kickers)

    # Two pair
    if len(pair_ranks) == 2:
        high_pair, low_pair = pair_ranks
        kicker = max(rank for rank in ranks if rank not in pair_ranks)
        return (2, high_pair, low_pair, kicker)

    # One pair
    if len(pair_ranks) == 1:
        pair = pair_ranks[0]
        kickers = tuple(rank for rank in ranks if rank != pair)
        return (1, pair, kickers)

    # High card
    return (0, tuple(ranks))


def best_hand_rank(cards: list[Card]) -> tuple:
    """
    Evaluates the best 5-card poker hand from 5, 6, or 7 cards.
    In Texas Hold'em, players usually have 7 cards:
        2 hole cards + 5 community cards.
    """
    if len(cards) < 5:
        raise ValueError("Need at least 5 cards to evaluate a poker hand")

    return max(evaluate_five(list(combo)) for combo in combinations(cards, 5))


def rank_name(rank: tuple) -> str:
    names = {
        8: "Straight Flush",
        7: "Four of a Kind",
        6: "Full House",
        5: "Flush",
        4: "Straight",
        3: "Three of a Kind",
        2: "Two Pair",
        1: "One Pair",
        0: "High Card",
    }
    return names[rank[0]]

def estimate_equity(
    hero_hand: list[Card],
    board: list[Card] | None = None,
    num_opponents: int = 1,
    simulations: int = 10_000,
    seed: int | None = None,
) -> dict:
    """
    Monte Carlo equity calculator for Texas Hold'em.

    Simulates random opponent hands and missing community cards,
    then estimates how often the hero hand wins/ties/loses.
    """
    board = board or []

    if len(hero_hand) != 2:
        raise ValueError("Hero must have exactly 2 hole cards")

    if len(board) > 5:
        raise ValueError("Board cannot have more than 5 cards")

    if num_opponents < 1:
        raise ValueError("Need at least 1 opponent")

    known_cards = hero_hand + board
    check_no_duplicates(known_cards)

    rng = random.Random(seed)

    wins = 0
    losses = 0
    ties = 0
    equity_sum = 0.0

    for _ in range(simulations):
        deck = Deck(excluded=known_cards, rng=rng)
        deck.shuffle()

        opponent_hands = [deck.draw(2) for _ in range(num_opponents)]
        completed_board = board + deck.draw(5 - len(board))

        hero_rank = best_hand_rank(hero_hand + completed_board)

        opponent_ranks = [
            best_hand_rank(opponent_hand + completed_board)
            for opponent_hand in opponent_hands
        ]

        all_ranks = [hero_rank] + opponent_ranks
        best_rank = max(all_ranks)

        if hero_rank == best_rank:
            winners = sum(1 for rank in all_ranks if rank == best_rank)

            if winners == 1:
                wins += 1
                equity_sum += 1.0
            else:
                ties += 1
                equity_sum += 1.0 / winners
        else:
            losses += 1

    return {
        "simulations": simulations,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": wins / simulations,
        "loss_rate": losses / simulations,
        "tie_rate": ties / simulations,
        "equity": equity_sum / simulations,
    }


@dataclass
class Player:
    name: str
    is_human: bool = False
    hole_cards: list[Card] | None = None
    stack: int = 1000
    folded: bool = False
    current_bet: int = 0

    def __post_init__(self):
        if self.hole_cards is None:
            self.hole_cards = []


class HoldemGame:
    def __init__(
        self,
        player_names: list[str],
        human_name: str = "Hero",
        seed: int | None = None,
        bot_simulations: int = 2_000,
    ):
        if len(player_names) < 2:
            raise ValueError("Need at least 2 players")

        self.rng = random.Random(seed)
        self.bot_simulations = bot_simulations

        self.players = [
            Player(name=name, is_human=(name == human_name))
            for name in player_names
        ]

        self.deck: Deck | None = None
        self.board: list[Card] = []
        self.pot = 0

    def start_hand(self) -> None:
        self.deck = Deck(rng=self.rng)
        self.deck.shuffle()

        self.board = []
        self.pot = 0

        for player in self.players:
            player.hole_cards = []
            player.folded = False
            player.current_bet = 0

        for _ in range(2):
            for player in self.players:
                player.hole_cards.extend(self.deck.draw(1))

    def deal_flop(self) -> None:
        self._require_deck()
        self.board.extend(self.deck.draw(3))

    def deal_turn(self) -> None:
        self._require_deck()
        self.board.extend(self.deck.draw(1))

    def deal_river(self) -> None:
        self._require_deck()
        self.board.extend(self.deck.draw(1))

    def betting_round(self, stage: str) -> None:
        """
        Simplified betting round.

        Supports:
            check, bet, call, raise, fold

        Does not yet support:
            blinds, all-in side pots, minimum raise rules
        """
        print(f"\n=== {stage.upper()} BETTING ROUND ===")

        for player in self.players:
            player.current_bet = 0

        current_bet = 0
        acted = set()

        while True:
            active_players = [p for p in self.players if not p.folded and p.stack > 0]

            if len(active_players) <= 1:
                return

            round_done = all(
                p.name in acted and p.current_bet == current_bet
                for p in active_players
            )

            if round_done:
                return

            for player in active_players:
                if player.folded:
                    continue

                call_amount = current_bet - player.current_bet

                if player.name in acted and call_amount == 0:
                    continue

                self.print_game_state(stage, player)

                if player.is_human:
                    action, amount = self.get_human_action(player, call_amount, current_bet)
                else:
                    action, amount = self.get_bot_action(player, call_amount, current_bet)

                print(f"{player.name} chooses: {action}", end="")
                if amount is not None:
                    print(f" {amount}")
                else:
                    print()

                if action == "fold":
                    player.folded = True
                    acted.add(player.name)

                elif action == "check":
                    if call_amount != 0:
                        print("Cannot check. You must call, raise, or fold.")
                        continue
                    acted.add(player.name)

                elif action == "call":
                    if call_amount <= 0:
                        print("Nothing to call. Checking instead.")
                        acted.add(player.name)
                    else:
                        self.collect_bet(player, call_amount)
                        acted.add(player.name)

                elif action == "bet":
                    if current_bet != 0:
                        print("There is already a bet. Use raise instead.")
                        continue
                    if amount is None or amount <= 0:
                        print("Invalid bet amount.")
                        continue

                    self.collect_bet(player, amount)
                    current_bet = player.current_bet
                    acted = {player.name}

                elif action == "raise":
                    if amount is None or amount <= current_bet:
                        print("Raise amount must be greater than current bet.")
                        continue

                    extra_needed = amount - player.current_bet
                    self.collect_bet(player, extra_needed)
                    current_bet = player.current_bet
                    acted = {player.name}

                else:
                    print("Unknown action.")
                    continue

                active_players = [p for p in self.players if not p.folded and p.stack > 0]
                if len(active_players) <= 1:
                    return

    def get_human_action(self, player: Player, call_amount: int, current_bet: int):
        print(f"\nYour cards: {player.hole_cards}")
        print(f"Your stack: {player.stack}")
        print(f"Pot: {self.pot}")

        if call_amount == 0:
            print("Available actions: check, bet, fold")
        else:
            print(f"Call amount: {call_amount}")
            print("Available actions: call, raise, fold")

        while True:
            raw = input("Action: ").strip().lower()

            parts = raw.split()
            action = parts[0] if parts else ""

            amount = None
            if len(parts) > 1:
                try:
                    amount = int(parts[1])
                except ValueError:
                    print("Amount must be a number.")
                    continue

            if action in {"check", "call", "fold"}:
                return action, amount

            if action in {"bet", "raise"}:
                if amount is None:
                    print(f"Use format like: {action} 50")
                    continue
                return action, amount

            print("Invalid action.")

    def get_bot_action(self, player: Player, call_amount: int, current_bet: int):
        """
        Monte Carlo poker bot.

        It estimates showdown equity against the remaining active opponents,
        then uses pot odds and simple thresholds to choose an action.
        """

        active_opponents = [
            p for p in self.players
            if p is not player and not p.folded and p.stack > 0
        ]

        num_opponents = max(1, len(active_opponents))

        result = estimate_equity(
            hero_hand=player.hole_cards,
            board=self.board,
            num_opponents=num_opponents,
            simulations=self.bot_simulations,
            seed=self.rng.randint(0, 10**9),
        )

        equity = result["equity"]

        print(
            f"{player.name} Monte Carlo equity: "
            f"{equity:.1%} vs {num_opponents} opponent(s)"
        )

        # Case 1: Nobody has bet yet
        if call_amount == 0:
            # Very strong hand/equity: bet larger
            if equity >= 0.75 and player.stack >= 60:
                return "bet", 60

            # Good hand/equity: small value bet
            if equity >= 0.60 and player.stack >= 30:
                return "bet", 30

            # Weak/medium hand: check
            return "check", None

        # Case 2: Bot is facing a bet
        if call_amount > player.stack:
            return "fold", None

        # Pot odds:
        # If call_amount = 20 and pot = 100,
        # break_even_equity = 20 / 120 = 16.7%
        break_even_equity = call_amount / (self.pot + call_amount)

        # Strong edge over pot odds: raise
        if equity >= break_even_equity + 0.25:
            raise_size = 40
            raise_to = current_bet + raise_size
            extra_needed = raise_to - player.current_bet

            if extra_needed <= player.stack:
                return "raise", raise_to

        # Profitable or close call
        if equity >= break_even_equity:
            return "call", None

        # Bad call
        return "fold", None

    def collect_bet(self, player: Player, amount: int) -> None:
        if amount <= 0:
            raise ValueError("Bet amount must be positive")

        if amount > player.stack:
            raise ValueError("This simplified engine does not support all-in yet")

        player.stack -= amount
        player.current_bet += amount
        self.pot += amount

    def active_players(self) -> list[Player]:
        return [p for p in self.players if not p.folded]

    def award_pot_if_only_one_left(self) -> bool:
        active = self.active_players()

        if len(active) == 1:
            winner = active[0]
            winner.stack += self.pot
            print(f"\n{winner.name} wins the pot of {self.pot} because everyone else folded.")
            self.pot = 0
            return True

        return False

    def showdown_and_award(self) -> None:
        if len(self.board) != 5:
            raise ValueError("Need full board before showdown")

        print("\n=== SHOWDOWN ===")
        print("Board:", self.board)

        results = []

        for player in self.players:
            if player.folded:
                continue

            rank = best_hand_rank(player.hole_cards + self.board)
            results.append((player, rank))

            print(f"{player.name}: {player.hole_cards} -> {rank_name(rank)} {rank}")

        best_rank = max(rank for _, rank in results)
        winners = [player for player, rank in results if rank == best_rank]

        split_amount = self.pot // len(winners)
        remainder = self.pot % len(winners)

        for i, winner in enumerate(winners):
            payout = split_amount + (remainder if i == 0 else 0)
            winner.stack += payout

        if len(winners) == 1:
            print(f"\nWinner: {winners[0].name}, winning pot of {self.pot}")
        else:
            names = ", ".join(w.name for w in winners)
            print(f"\nSplit pot between: {names}")

        self.pot = 0

    def play_hand(self) -> None:
        self.start_hand()

        print("\n=== NEW HAND ===")

        for player in self.players:
            if player.is_human:
                print(f"Your cards: {player.hole_cards}")

        self.betting_round("pre-flop")
        if self.award_pot_if_only_one_left():
            self.print_stacks()
            return

        self.deal_flop()
        print("\nFLOP:", self.board)
        self.betting_round("flop")
        if self.award_pot_if_only_one_left():
            self.print_stacks()
            return

        self.deal_turn()
        print("\nTURN:", self.board)
        self.betting_round("turn")
        if self.award_pot_if_only_one_left():
            self.print_stacks()
            return

        self.deal_river()
        print("\nRIVER:", self.board)
        self.betting_round("river")
        if self.award_pot_if_only_one_left():
            self.print_stacks()
            return

        self.showdown_and_award()
        self.print_stacks()

    def print_game_state(self, stage: str, current_player: Player) -> None:
        print("\n--------------------")
        print(f"Stage: {stage}")
        print(f"Board: {self.board}")
        print(f"Pot: {self.pot}")
        print(f"Current player: {current_player.name}")

        for player in self.players:
            status = "folded" if player.folded else "active"
            print(
                f"{player.name}: stack={player.stack}, "
                f"round_bet={player.current_bet}, status={status}"
            )

    def print_stacks(self) -> None:
        print("\n=== STACKS ===")
        for player in self.players:
            print(f"{player.name}: {player.stack}")

    def _require_deck(self) -> None:
        if self.deck is None:
            raise RuntimeError("Call start_hand() first")
    
if __name__ == "__main__":
    game = HoldemGame(
        player_names=["Hero", "Bot1", "Bot2"],
        human_name="Hero",
        seed=42,
        bot_simulations=2_000,
    )

    game.play_hand()