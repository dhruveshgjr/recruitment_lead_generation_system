from hiringleads.security import make_unsubscribe_token, parse_unsubscribe_token


def test_unsubscribe_token_round_trip():
    token = make_unsubscribe_token(12345)
    assert parse_unsubscribe_token(token) == 12345


def test_tampering_is_rejected():
    token = make_unsubscribe_token(12345)
    payload, sig = token.split(".", 1)
    tampered = f"{payload[:-1]}A.{sig}"
    assert parse_unsubscribe_token(tampered) is None


def test_malformed_token_is_rejected():
    assert parse_unsubscribe_token("not-a-token") is None
