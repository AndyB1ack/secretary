from secretary.modes import detect_mode_command


def test_commands():
    assert detect_mode_command("Обед, я один") == "private"
    assert detect_mode_command("Мира, еду домой!") == "evening"
    assert detect_mode_command("Паника") == "work"


def test_no_false_trigger():
    assert detect_mode_command("но нужна твоя помощь: я один не справлюсь") is None
    assert detect_mode_command("я сегодня еду домой поздно, после объекта в Холоне") is None
