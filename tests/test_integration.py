import asyncio
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Add scripts to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))

# Create a mock config object for testing
mock_config_obj = MagicMock()
mock_config_obj.LOG_LEVEL = "INFO"
mock_config_obj.SUPABASE_URL = "https://example.supabase.co"
mock_config_obj.SUPABASE_KEY = "dummy_key"
mock_config_obj.STAKE_WHALE_PCT = 0.01  # 1%
mock_config_obj.STAKE_MIN = 5.0
mock_config_obj.STAKE_MAX = 50.0
mock_config_obj.BANKROLL = 1000.0
mock_config_obj.DRY_RUN = True
mock_config_obj.TRADER_WALLETS = ["0xtrader1"]
mock_config_obj.POLY_FUNDER = "0xbotwallet"
mock_config_obj.DEFAULT_SLIPPAGE = 0.01
mock_config_obj.MAX_RETRY_ATTEMPTS = 1

# Patch BEFORE importing main
with patch('config.get_config', return_value=mock_config_obj):
    from main import handle_new_trade

@pytest.mark.asyncio
async def test_full_trade_flow():
    """
    Test the flow from a new trade event through sizing, risk checks, and mock execution.
    """
    # 1. Prepare a mock trade payload (similar to what Supabase sends)
    payload = {
        "data": {
            "record": {
                "proxy_wallet": "0xtrader1",
                "usdc_size": 1000,  # Trader bet 1000
                "side": "BUY",
                "asset": "0xtoken123",
                "title": "Test Market",
                "price": 0.5,
                "transaction_hash": "0xabc123"
            }
        }
    }

    # 2. Mock external dependencies inside main.py
    with patch('main.get_current_exposures', return_value=(100, {"0xtoken123": 0})), \
         patch('main.make_order', return_value={"success": True, "orderID": "MOCK_ID"}) as mock_make_order:
        
        # 3. Trigger the handler
        result = await handle_new_trade(payload)

        # 4. Verify sizing: 1% of 1000 is 10.0
        # 5. Verify the order was attempted
        mock_make_order.assert_called_once()
        args, kwargs = mock_make_order.call_args
        assert kwargs['size'] == 20.0  # 10 USDC / 0.5 price = 20 units
        assert kwargs['price'] == 0.5
        assert kwargs['token_id'] == "0xtoken123"
        assert result["success"] is True

    print("\n✅ Integration Test Passed: Flow from Event -> Sizing -> Risk -> Order confirmed!")

if __name__ == "__main__":
    asyncio.run(test_full_trade_flow())
