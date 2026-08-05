from validation.cause.damasha import parse_mixed_text, windows


def test_parse_boundary_and_strip_tags() -> None:
    human = " ".join(["human"] * 45)
    ai = " ".join(["machine"] * 50)
    record = parse_mixed_text(f"{human}<AI_Start>{ai}</AI_End>", 7)
    assert record is not None
    assert record.boundary_word == 45
    assert "<AI" not in record.mixed


def test_parse_rejects_short_segments() -> None:
    assert parse_mixed_text("short<AI_Start>also short</AI_End>", 0) is None


def test_windows_anchor_tail() -> None:
    text = " ".join(f"w{i}" for i in range(205))
    result = windows(text, size=80, step=40)
    assert result[0][:2] == (0, 80)
    assert result[-1][:2] == (125, 205)
