# Polymarket Copytrading Bot Improvement Plan

This plan outlines the steps to enhance the functionality, reliability, and profitability of the Polymarket copytrading bot.

## 1. Architectural Improvements

### 1.1 Support for Multiple Traders
- **Goal**: Copy trades from multiple successful wallets instead of just one.
- **Action**: Update `config.py` to support `TRADER_WALLETS` (comma-separated list).
- **Action**: Update `main.py` listeners to handle multiple addresses.

### 1.2 Structured Risk Management
- **Goal**: Protect the bankroll from excessive losses.
- **Action**: Create `scripts/constraints/risk_manager.py`.
- **Features**:
    - `MAX_TOTAL_EXPOSURE`: Cap the total USDC in active positions.
    - `MAX_PER_TRADER_EXPOSURE`: Limit how much can be allocated to a single trader's picks.
    - `MAX_PER_MARKET_EXPOSURE`: Avoid being over-leveraged in one market.
    - `SLIPPAGE_LIMIT`: Reject trades if the price moves too far.

## 2. Execution Enhancements

### 2.1 Robust Order Placement
- **Goal**: Ensure orders are filled and handle API failures gracefully.
- **Action**: Refactor `scripts/make_orders.py`.
- **Features**:
    - **Retry Logic**: Exponential backoff for transient network/API errors.
    - **Slippage Protection**: Add a `max_slippage` parameter to `make_order`.
    - **Order Tracking**: Log all order IDs and their status.

### 2.2 Improved Sizing Logic
- **Goal**: Align trade sizes with the bot's bankroll and strategy.
- **Action**: Update `scripts/constraints/sizing.py`.
- **Features**:
    - `PROPORTIONAL_SIZING`: Copy the same *percentage* of the bankroll that the target trader used.
    - `FIXED_SIZING`: Use a fixed USDC amount regardless of the trader's size.
    - Enforce `STAKE_MIN` and `STAKE_MAX` consistently.

## 3. Monitoring and Reliability

### 3.1 Advanced Logging
- **Goal**: Better visibility into the bot's decisions and errors.
- **Action**: Use Python's `logging` module to save logs to `bot.log`.
- **Action**: Include timestamps, trader address, and market details in every log.

### 3.2 Notifications
- **Goal**: Real-time alerts on mobile.
- **Action**: Add a Telegram notification handler.
- **Alerts**: New trades, filled orders, errors, and daily PnL summaries.

## 4. Maintenance and Quality

### 4.1 Type Safety and Testing
- **Goal**: Prevent bugs through better code structure.
- **Action**: Add type hints to all functions.
- **Action**: Create a `tests/` directory and add unit tests for sizing and risk logic.

### 4.2 Dependency Management
- **Goal**: Keep the environment clean.
- **Action**: Update `requirements.txt` with any new necessary libraries.

---

## Next Steps (Phased Implementation)

1. **Phase 1 (Reliability)**: Refactor `make_orders.py` and implement structured logging.
2. **Phase 2 (Strategy)**: Enhance `sizing.py` and implement the `RiskManager`.
3. **Phase 3 (Scaling)**: Support multiple traders and add Telegram notifications.
4. **Phase 4 (Testing)**: Add unit tests and type hints.
