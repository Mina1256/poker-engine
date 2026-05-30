# Texas Hold'em Poker Engine

A lightweight Texas Hold'em poker engine with a FastAPI backend, hand evaluation logic, and a Monte Carlo-based bot. The project supports creating a poker game, submitting player actions, evaluating poker hands, and estimating win equity through simulations.

## Features

- Texas Hold'em card, deck, and hand-ranking system
- Supports 5-card, 6-card, and 7-card hand evaluation
- Detects all major poker hand categories:
  - Straight flush
  - Four of a kind
  - Full house
  - Flush
  - Straight
  - Three of a kind
  - Two pair
  - One pair
  - High card
- Handles Ace-low straights, such as A-2-3-4-5
- Monte Carlo equity estimation against one or more opponents
- Betting system with:
  - Check
  - Bet
  - Call
  - Raise
  - Fold
- FastAPI backend for browser or frontend integration
- Stateless API design where the frontend sends back the current game state
- CORS enabled for local testing and demos

## Project Structure

```text
.
├── app.py              # FastAPI backend and API game wrapper
├── holdem_engine.py    # Poker engine, card logic, hand evaluator, and equity simulator
└── README.md
```

## How It Works

The project is split into two main parts.

### `holdem_engine.py`

This file contains the core poker logic:

- `Card` represents a playing card.
- `Deck` creates, shuffles, and draws from a standard 52-card deck.
- `parse_card()` converts strings like `As` or `Td` into card objects.
- `evaluate_five()` ranks exactly five cards.
- `best_hand_rank()` checks every 5-card combination from 5, 6, or 7 cards and returns the strongest hand.
- `estimate_equity()` runs Monte Carlo simulations to estimate win, loss, tie, and equity rates.
- `HoldemGame` provides a command-line version of a simplified poker game.

### `app.py`

This file wraps the engine in a FastAPI backend.

It provides:

- A `/games` endpoint to create a new hand
- An `/action` endpoint to submit player actions
- A public game state that can be sent to a frontend
- A simple Monte Carlo bot that chooses actions based on estimated equity and pot odds

## Installation

Clone the repository:

```bash
git clone https://github.com/YOUR-USERNAME/YOUR-REPO-NAME.git
cd YOUR-REPO-NAME
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install fastapi uvicorn pydantic
```

## Running the API

Start the FastAPI server with:

```bash
uvicorn app:app --reload
```

Then open:

```text
http://127.0.0.1:8000
```

You should see:

```json
{
  "message": "Poker API is running."
}
```

## Live Demo

You can find an example of the API being used with a frontend here:

```text
https://www.minamikhail.ca/poker
```

## API Endpoints

### `GET /`

Health-check endpoint.

**Response:**

```json
{
  "message": "Poker API is running."
}
```

### `POST /games`

Creates a new poker hand.

**Example response:**

```json
{
  "game_state": {
    "...": "raw game state used by the backend"
  },
  "state": {
    "stage": "preflop",
    "pot": 0,
    "board": [],
    "hero": {
      "cards": ["As", "Kd"],
      "stack": 1000,
      "current_bet": 0,
      "folded": false
    },
    "bot": {
      "cards": ["7c", "8d"],
      "stack": 1000,
      "current_bet": 0,
      "folded": false
    },
    "to_call": 0,
    "legal_actions": ["check", "bet", "fold"],
    "game_over": false,
    "winner": null,
    "log": ["New hand started."]
  }
}
```

### `GET /games`

Browser-friendly test endpoint that creates a new game.

This is useful if you want to quickly test the API from a browser.

### `POST /action`

Submits an action for the hero player.

**Request body:**

```json
{
  "game_state": {
    "...": "the game_state returned by /games or the previous /action call"
  },
  "action": "bet",
  "amount": 50
}
```

Supported actions depend on the current game state.

When there is no bet to call:

```text
check, bet, fold
```

When facing a bet:

```text
call, raise, fold
```

For `bet`, `amount` means the amount to bet.

For `raise`, `amount` means the total bet size for the current betting round.

## Example Frontend Flow

1. Call `POST /games`.
2. Store the returned `game_state`.
3. Display the returned public `state`.
4. When the user clicks an action button, call `POST /action`.
5. Send the latest `game_state`, the chosen action, and an optional amount.
6. Replace the old game state with the new response.
7. Repeat until `game_over` is `true`.

## Example Python Usage

You can also use the poker engine directly without the API:

```python
from holdem_engine import parse_cards, best_hand_rank, rank_name, estimate_equity

cards = parse_cards("As Ks Qs Js Ts 2d 3c")
rank = best_hand_rank(cards)

print(rank)
print(rank_name(rank))
```

Estimate equity:

```python
from holdem_engine import parse_cards, estimate_equity

hero_hand = parse_cards("As Ks")
board = parse_cards("Qs Js 2d")

result = estimate_equity(
    hero_hand=hero_hand,
    board=board,
    num_opponents=1,
    simulations=10000,
    seed=42,
)

print(result)
```
