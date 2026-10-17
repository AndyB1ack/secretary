from secretary.modes import ModeSwitcher, detect_mode_command


def test_commands():
    assert detect_mode_command("Обед, я один").mode == "private"
    assert detect_mode_command("Мира, еду домой!").mode == "evening"
    assert detect_mode_command("Моё рабочее время закончилось").mode == "evening"
    assert detect_mode_command("У меня сейчас обеденный перерыв").mode == "private"
    assert detect_mode_command("Всё, я могу идти домой").mode == "evening"
    assert detect_mode_command("Паника").confirm is False


def test_no_false_trigger():
    assert detect_mode_command("но нужна твоя помощь: я один не справлюсь") is None
    assert detect_mode_command("я сегодня еду домой поздно, после объекта в Холоне, там лифт") is None


def test_private_needs_confirmation():
    s = ModeSwitcher()
    mode, say, handled = s.handle("У меня обеденный перерыв", "work")
    assert mode is None and say and handled
    assert s.handle("да", "work")[0] == "private"


def test_confirmation_declined_or_ignored():
    s = ModeSwitcher()
    s.handle("Еду домой", "work")
    assert s.handle("нет, оговорился", "work") == (None, "Поняла, продолжаем.", True)
    s.handle("Еду домой", "work")
    mode, say, handled = s.handle("Сколько клемм на контроллере?", "work")
    assert mode is None and not handled  # обычный вопрос идёт к Мире, режим не меняется


def test_panic_is_instant():
    s = ModeSwitcher()
    assert s.handle("Паника", "private") == ("work", None, True)
