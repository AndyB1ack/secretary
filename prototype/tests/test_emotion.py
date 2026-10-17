from secretary.emotion import extract, strip


def test_extract_tags():
    assert extract("[весело] Ну ты даёшь!", "спокойно") == ("Ну ты даёшь!", "весело")
    assert extract("Я рада.", "нежно") == ("Я рада.", "нежно")
    assert extract("[непонятно] Привет.", "спокойно") == ("Привет.", "спокойно")
    assert strip("[грустно] Ох. [нежно] Иди сюда.") == "Ох. Иди сюда."
