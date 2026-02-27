from decimal import Decimal

from app.tools._core.similarity_logic import evaluate_similarity


def test_evaluate_similarity_handles_decimal_amounts() -> None:
    transaction = {
        "amount": 100.0,
        "merchant_id": "m1",
        "card_id": "c1",
    }
    similar_transactions = [
        {
            "transaction_id": "t2",
            "amount": Decimal("95.00"),
            "merchant_id": "m1",
            "card_id": "c1",
        }
    ]

    result = evaluate_similarity(transaction=transaction, similar_transactions=similar_transactions)

    assert result.overall_score > 0
    assert len(result.matches) == 1
    assert result.matches[0].match_id == "t2"
